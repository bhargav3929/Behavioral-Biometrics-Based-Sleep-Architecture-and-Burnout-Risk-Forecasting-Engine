"""Deterministic chronobiology engine. Runs BEFORE Groq, and the AI never changes its numbers.

Every formula here is also written out in the "audit" block of each result, with each day's
intermediate values, so a reviewer can verify the math by hand.
"""
from __future__ import annotations

import math
import re

from . import config

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
FULL_DAY = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
PRESETS = [
    "Standard Knowledge Worker",
    "Shift / Night Worker",
    "Student / Exam Week",
    "Teenager / Adolescent (13–17)",
    "Parent / Caregiver",
    "Pregnant / Postpartum",
    "Athlete / Heavy Training",
    "Custom Context...",
]
DEFAULT_CONTEXT = PRESETS[0]

HALF_LIFE_H = 5.0
REPAY_RATE = 0.5          # surplus sleep repays only half as much debt as a deficit creates
DEBT_FULL_SCALE_H = 14.0  # 14 h of accumulated debt = a debt score of 100
WEIGHTS = {"sleep_debt": 0.35, "caffeine": 0.15, "screen": 0.15, "consistency": 0.20, "architecture": 0.15}

CLOCK_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


class BadInput(Exception):
    def __init__(self, problems: list[str]):
        super().__init__(problems[0] if problems else "Invalid log")
        self.problems = problems


# ----------------------------------------------------------------------------- clocks
def parse_clock(v) -> float | None:
    if not isinstance(v, str):
        return None
    m = CLOCK_RE.match(v.strip())
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return None
    return h + mi / 60.0


def fmt_clock(h: float) -> str:
    total = int(round((h % 24) * 60)) % 1440
    return f"{total // 60:02d}:{total % 60:02d}"


def circ_mean(hours: list[float]) -> float:
    s = sum(math.sin(h / 24 * 2 * math.pi) for h in hours)
    c = sum(math.cos(h / 24 * 2 * math.pi) for h in hours)
    return (math.atan2(s, c) / (2 * math.pi) * 24) % 24


def circ_dev(h: float, mean: float) -> float:
    return ((h - mean + 12) % 24) - 12


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def sd(xs: list[float]) -> float:
    if not xs:
        return 0.0
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


def r2(x: float) -> float:
    return round(float(x), 2)


# ----------------------------------------------------------------------------- parsing
def _num(v):
    """Return (value, status) where status is 'ok', 'missing' or 'bad'."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None, "missing"
    if isinstance(v, bool):
        return None, "bad"
    if isinstance(v, (int, float)):
        x = float(v)
    elif isinstance(v, str):
        try:
            x = float(v.strip())
        except ValueError:
            return None, "bad"
    else:
        return None, "bad"
    return (x, "ok") if math.isfinite(x) else (None, "bad")


COLS = ["day", "sleep_hours", "bedtime", "wake_time", "screen_hours", "caffeine_mg", "last_caffeine"]
ALIASES = {
    "day": "day", "date": "day",
    "sleep": "sleep_hours", "sleep_hours": "sleep_hours", "sleep(hrs)": "sleep_hours", "hours": "sleep_hours",
    "bed": "bedtime", "bedtime": "bedtime",
    "wake": "wake_time", "wake_time": "wake_time", "waketime": "wake_time",
    "screen": "screen_hours", "screen_hours": "screen_hours", "screen_time": "screen_hours",
    "caffeine": "caffeine_mg", "caffeine_mg": "caffeine_mg",
    "last_caffeine": "last_caffeine", "last": "last_caffeine", "cutoff": "last_caffeine",
}


def parse_log_text(text: str) -> dict:
    """Turn pasted CSV / tab text into {'context': str|None, 'days': [dict]}. No range checks here."""
    context = None
    title = None
    rows: list[list[str]] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^#?\s*(context|title|order)\s*[:=]\s*(.+)$", line, re.I)
        if m:
            if m.group(1).lower() == "context":
                context = m.group(2).strip()
            continue
        if line.startswith("#"):
            continue
        delim = "\t" if "\t" in line else ";" if line.count(";") >= 3 else "|" if line.count("|") >= 3 else ","
        rows.append([c.strip() for c in line.split(delim)])
    if not rows:
        raise BadInput(["The pasted log is empty. Paste one line per day: day, sleep, bedtime, wake, screen, caffeine, last caffeine."])
    order = list(COLS)
    first = [c.lower().replace(" ", "_") for c in rows[0]]
    if any(c in ALIASES for c in first) and not any(re.match(r"^-?\d+(\.\d+)?$", c) for c in rows[0][:1]):
        mapped = [ALIASES.get(c) for c in first]
        if sum(1 for c in mapped if c) >= 4:
            order = mapped
            rows = rows[1:]
    days = []
    for r in rows:
        if order == COLS and len(r) == len(COLS) - 1 and _num(r[0])[1] == "ok":
            r = [FULL_DAY[len(days) % 7]] + r  # no day label given
        d = {}
        for i, col in enumerate(order):
            if col and i < len(r):
                d[col] = r[i]
        d.setdefault("day", FULL_DAY[len(days) % 7])
        days.append(d)
    return {"context": context, "days": days}


# ----------------------------------------------------------------------------- profile
def resolve_profile(context: str, custom: str = "") -> dict:
    """Combine the preset pill and any free text into baselines and a caffeine ceiling."""
    text = f"{context or ''} {custom or ''}".lower()
    target = config.TARGET_SLEEP_HOURS
    safe = config.SAFE_CAFFEINE_MG

    age = None
    for pat in (r"(\d{1,2})\s*[- ]?\s*(?:years?|yrs?|yr)\s*[- ]?\s*old", r"\bage[d]?\s*[:=]?\s*(\d{1,2})\b",
                r"\b(\d{1,2})\s*(?:yo|y/o|y\.o\.)(?!\w)", r"\b(\d{1,2})\s*(?:years?|yrs?)\b"):
        m = re.search(pat, text)
        if m and 1 <= int(m.group(1)) <= 110:
            age = int(m.group(1))
            break
    adult_school = re.search(r"graduate school|grad school|law school|medical school|business school|nursing school|"
                             r"night school|driving school|school teacher|teaches", text)
    teen_kw = re.search(r"\b(teen|teens|teenager|adolescent|kid|kids|child|children|schoolboy|schoolgirl|minor)\b|"
                        r"\bhigh school\b|\bmiddle school\b|\bschool\b", text)
    if age is not None:
        teen = age < 18
    else:
        teen = bool(teen_kw) and not adult_school
    pregnant = bool(re.search(r"pregnan|postpartum|post-partum|breastfeed|lactat|expecting", text)) or \
        bool(re.search(r"\bnursing\b", text) and not re.search(r"nursing (?:school|student|home|degree|shift)", text))
    shift = bool(re.search(r"night shift|\bshift\b|night worker|graveyard|rotating|nocturnal|night nurse", text))
    sensitive = bool(re.search(r"palpitation|anxiety|anxious|panic|arrhythm|heart condition|hypertension|"
                               r"high blood pressure|migraine", text))
    athlete = bool(re.search(r"athlete|heavy training|marathon|training", text))
    student = bool(re.search(r"student|exam", text))
    parent = bool(re.search(r"parent|caregiver|newborn|infant|baby", text))

    baseline = target
    reasons = []
    limit = safe
    if teen:
        baseline = max(9.0, target + 1.0)
        limit = min(limit, 100.0)
        reasons.append("Adolescent: sleep baseline raised to 9.0 h and caffeine ceiling lowered to 100 mg/day (AAP guidance).")
    elif athlete:
        baseline = target + 0.5
        reasons.append("Heavy training: sleep baseline raised by 0.5 h for recovery.")
    if pregnant:
        limit = min(limit, 200.0)
        reasons.append("Pregnancy / postpartum: caffeine ceiling lowered to 200 mg/day (ACOG guidance).")
    if sensitive:
        limit = min(limit, 200.0)
        reasons.append("Caffeine-sensitive context (palpitations / anxiety): caffeine ceiling lowered to 200 mg/day.")
    if shift:
        reasons.append("Shift / night work: daytime sleep anchors are expected; only erratic day/night flip-flopping is penalised.")

    key = ("teen" if teen else "pregnant" if pregnant else "shift" if shift else "athlete" if athlete
           else "student" if student else "parent" if parent else "standard")
    return {
        "key": key, "label": context or DEFAULT_CONTEXT, "custom_text": custom or "",
        "age": age, "teen": teen, "pregnant": pregnant, "shift": shift, "sensitive": sensitive,
        "athlete": athlete, "student": student, "parent": parent,
        "baseline_sleep": r2(baseline), "caffeine_limit": r2(limit), "reasons": reasons,
    }


# ----------------------------------------------------------------------------- validation
def validate(body) -> dict:
    """Check a raw request body. Raises BadInput with every problem found; returns normalised input."""
    if not isinstance(body, dict):
        raise BadInput(["Send a JSON object with a 'days' list (7 to 14 days)."])

    context = body.get("context")
    custom = body.get("custom_context") or ""
    days_raw = body.get("days")
    if days_raw is None and isinstance(body.get("log_text"), str):
        parsed = parse_log_text(body["log_text"])
        days_raw = parsed["days"]
        context = context or parsed["context"]
    if not isinstance(days_raw, list):
        raise BadInput(["Send a 'days' list with one entry per day (7 to 14 days)."])
    context = str(context or DEFAULT_CONTEXT).strip()[:200]
    custom = str(custom).strip()[:300]

    n = len(days_raw)
    if n < 7:
        raise BadInput([f"Only {n} day(s) were logged. Log at least 7 days so weekly patterns can be measured."])
    if n > 14:
        raise BadInput([f"{n} days were logged. Log at most 14 days (use the most recent two weeks)."])

    problems: list[str] = []
    days: list[dict] = []
    notes: list[str] = []
    derived_note = False
    for i, raw in enumerate(days_raw):
        if not isinstance(raw, dict):
            problems.append(f"Day {i + 1}: each day must be an object with sleep, screen and caffeine values.")
            continue
        label = str(raw.get("day") or FULL_DAY[i % 7]).strip()[:12] or FULL_DAY[i % 7]
        tag = f"Day {i + 1} ({label})"
        vals = {}
        for key, nice in (("sleep_hours", "sleep hours"), ("screen_hours", "screen hours"), ("caffeine_mg", "caffeine mg")):
            x, st = _num(raw.get(key))
            if st == "missing":
                problems.append(f"{tag}: {nice} is missing.")
            elif st == "bad":
                problems.append(f"{tag}: {nice} must be a number.")
            else:
                vals[key] = x
        sleep, screen, caf = vals.get("sleep_hours"), vals.get("screen_hours"), vals.get("caffeine_mg")
        if sleep is not None and sleep < 0:
            problems.append(f"{tag}: sleep hours cannot be negative ({sleep:g}).")
        if screen is not None and screen < 0:
            problems.append(f"{tag}: screen hours cannot be negative ({screen:g}).")
        if caf is not None and caf < 0:
            problems.append(f"{tag}: caffeine cannot be negative ({caf:g} mg).")
        if sleep is not None and sleep > 24:
            problems.append(f"{tag}: {sleep:g} h of sleep is more than the 24 hours in a day.")
        if screen is not None and screen > 24:
            problems.append(f"{tag}: {screen:g} h of screen time is more than the 24 hours in a day.")
        if sleep is not None and screen is not None and 0 <= sleep <= 24 and 0 <= screen <= 24 and sleep + screen > 24.0:
            problems.append(f"{tag}: {sleep:g} h sleep + {screen:g} h screen = {sleep + screen:g} h, "
                            "which cannot fit in one 24-hour day.")
        if caf is not None and caf > 1200:
            problems.append(f"{tag}: {caf:g} mg of caffeine in one day is in the acute-toxicity range (over 1,200 mg). "
                            "Please re-check the number. If it is real, seek medical advice instead of using this tool.")

        bed_raw, wake_raw, last_raw = raw.get("bedtime"), raw.get("wake_time"), raw.get("last_caffeine")
        bed_blank = bed_raw is None or str(bed_raw).strip() == ""
        wake_blank = wake_raw is None or str(wake_raw).strip() == ""
        bed = wake = last = None
        if bed_blank and wake_blank:
            pass  # derived below from the sleep hours
        else:
            if bed_blank:
                problems.append(f"{tag}: bedtime is missing.")
            else:
                bed = parse_clock(str(bed_raw))
                if bed is None:
                    problems.append(f"{tag}: bedtime \"{bed_raw}\" is not a valid 24-hour HH:MM time.")
            if wake_blank:
                problems.append(f"{tag}: wake time is missing.")
            else:
                wake = parse_clock(str(wake_raw))
                if wake is None:
                    problems.append(f"{tag}: wake time \"{wake_raw}\" is not a valid 24-hour HH:MM time.")
        last_blank = last_raw is None or str(last_raw).strip() in ("", "-", "--", "none", "None")
        if last_blank:
            if caf is not None and caf > 0:
                problems.append(f"{tag}: last caffeine time is needed when caffeine is above 0 mg.")
        else:
            last = parse_clock(str(last_raw))
            if last is None:
                problems.append(f"{tag}: last caffeine \"{last_raw}\" is not a valid 24-hour HH:MM time.")
        days.append({"day": label, "sleep": sleep, "screen": screen, "caffeine": caf,
                     "bed": bed, "wake": wake, "last": last, "bed_blank": bed_blank and wake_blank})

    if not problems and all(d["sleep"] == 0 and d["screen"] == 0 and d["caffeine"] == 0 for d in days):
        problems.append("Every day is 0 for sleep, screen time and caffeine. That looks like an empty or incomplete log. "
                        "Enter your real numbers and try again.")
    if problems:
        raise BadInput(problems)

    for d in days:
        if d["bed_blank"]:
            d["wake"] = 7.0
            d["bed"] = (7.0 - d["sleep"]) % 24
            if not derived_note:
                derived_note = True
                notes.append("Bedtime and wake time were not given for some days, so they were estimated "
                             "from sleep hours (wake 07:00). Circadian consistency is less reliable.")
        window = (d["wake"] - d["bed"]) % 24
        if window == 0:
            window = d["sleep"]
        d["window"] = window
        if d["sleep"] > window + 0.75:
            notes.append(f"{d['day']}: {d['sleep']:g} h of sleep is longer than the bed-to-wake window "
                         f"({window:.1f} h). Midpoints use the clock times you gave.")
    profile = resolve_profile(context, custom)
    return {"days": days, "context": context, "custom_context": custom, "profile": profile, "notes": notes}


# ----------------------------------------------------------------------------- scoring
def band_for(score: float) -> dict:
    if score >= 75:
        return {"key": "critical", "label": "Critical Burnout Alert"}
    if score >= 50:
        return {"key": "elevated", "label": "Elevated Fatigue / Sleep Debt"}
    if score >= 25:
        return {"key": "moderate", "label": "Moderate Strain"}
    return {"key": "optimal", "label": "Optimal Circadian Recovery"}


def _is_weekend(i: int, label: str) -> bool:
    lab = label[:3].lower()
    if lab in ("sat", "sun"):
        return True
    if lab in WEEKDAYS:
        return False
    return i % 7 >= 5


def analyze(inp: dict) -> dict:
    prof = inp["profile"]
    base = prof["baseline_sleep"]
    limit = prof["caffeine_limit"]
    days = inp["days"]
    n = len(days)

    # ---- per-day calculations
    per = []
    debt = 0.0
    for i, d in enumerate(days):
        gap = base - d["sleep"]
        before = debt
        debt = debt + gap if gap > 0 else max(0.0, debt + gap * REPAY_RATE)
        mid = (d["bed"] + d["window"] / 2) % 24
        if d["caffeine"] > 0 and d["last"] is not None:
            hrs = (d["bed"] - d["last"]) % 24
            resid = d["caffeine"] * 0.5 ** (hrs / HALF_LIFE_H)
            late = hrs < 8 if prof["shift"] else d["last"] > 16.0
        else:
            hrs, resid, late = None, 0.0, False
        per.append({
            "day": d["day"], "index": i + 1, "weekend": _is_weekend(i, d["day"]),
            "sleep": r2(d["sleep"]), "screen": r2(d["screen"]), "caffeine": r2(d["caffeine"]),
            "bedtime": fmt_clock(d["bed"]), "wake": fmt_clock(d["wake"]), "window_h": r2(d["window"]),
            "last_caffeine": fmt_clock(d["last"]) if d["last"] is not None and d["caffeine"] > 0 else None,
            "gap_vs_baseline": r2(gap), "debt_before": r2(before), "running_debt": r2(debt),
            "midpoint": fmt_clock(mid), "midpoint_h": mid,
            "hours_caffeine_to_bed": r2(hrs) if hrs is not None else None,
            "residual_mg": r2(resid), "late_caffeine": late,
        })

    sleeps = [p["sleep"] for p in per]
    screens = [p["screen"] for p in per]
    cafs = [p["caffeine"] for p in per]
    resids = [p["residual_mg"] for p in per]
    mids = [p["midpoint_h"] for p in per]
    mean_sleep, mean_screen, mean_caf, mean_resid = mean(sleeps), mean(screens), mean(cafs), mean(resids)
    sd_sleep = sd(sleeps)
    mid_mean = circ_mean(mids)
    devs = [circ_dev(m, mid_mean) for m in mids]
    sd_mid = math.sqrt(mean([x * x for x in devs]))
    swing = max(devs) - min(devs)

    wk = [p for p in per if not p["weekend"]]
    we = [p for p in per if p["weekend"]]
    wk_mean = mean([p["sleep"] for p in wk]) if wk else mean_sleep
    we_mean = mean([p["sleep"] for p in we]) if we else mean_sleep
    wk_deficit = sum(max(0.0, base - p["sleep"]) for p in wk)
    rebound = we_mean - wk_mean if wk and we else 0.0
    sjl = 0.0
    if wk and we:
        sjl = abs(circ_dev(circ_mean([p["midpoint_h"] for p in we]),
                           circ_mean([p["midpoint_h"] for p in wk])))
    cum_debt = per[-1]["running_debt"]

    # ---- architecture efficiency
    caff_pen = min(30.0, mean_resid * 0.2)
    screen_pen = min(15.0, max(0.0, mean_screen - 4.0) * 1.5)
    frag_pen = min(15.0, sd_mid * 5.0)
    short_pen = min(20.0, max(0.0, base - mean_sleep) * 3.0)
    eff = max(20.0, 100.0 - caff_pen - screen_pen - frag_pen - short_pen)

    # ---- guardrails
    alerts: list[dict] = []

    def alert(code, title, severity, detail, floor):
        alerts.append({"code": code, "title": title, "severity": severity, "detail": detail, "floor": floor})

    if prof["teen"]:
        if mean_sleep < 8.0 and mean_caf > limit:
            alert("TEEN_MAJOR", "Major Pediatric/Adolescent Sleep & Caffeine Alert", "critical",
                  f"Average sleep {mean_sleep:.1f} h is well under the 9.0 h adolescent baseline and average caffeine "
                  f"{mean_caf:.0f} mg exceeds the {limit:.0f} mg/day pediatric ceiling. Growth, mood and learning are "
                  "especially sensitive to this combination.", 70)
        elif mean_sleep < base - 0.5 or mean_caf > limit:
            alert("TEEN_WATCH", "Adolescent Sleep or Caffeine Watch", "elevated",
                  f"Adolescents need about {base:.0f}–10 h of sleep and no more than {limit:.0f} mg of caffeine a day. "
                  f"Logged average: {mean_sleep:.1f} h sleep, {mean_caf:.0f} mg caffeine.", 50)
    if prof["pregnant"] and max(cafs) > 200:
        alert("MATERNAL_CAFFEINE", "Maternal Caffeine Ceiling Alert", "elevated",
              f"Caffeine reached {max(cafs):.0f} mg on at least one day, above the 200 mg/day ceiling used for pregnancy "
              "and postpartum. Fragmented recovery sleep makes caffeine linger longer, so talk with your care provider.", 55)
    elif prof["sensitive"] and max(cafs) > limit:
        alert("CAFFEINE_SENSITIVE", "Caffeine Sensitivity Context Alert", "elevated",
              f"You mentioned palpitations, anxiety or a similar concern. Caffeine reached {max(cafs):.0f} mg, "
              f"above the {limit:.0f} mg/day ceiling used here.", 50)
    elif not prof["teen"] and mean_caf > limit:
        alert("CAFFEINE_OVER", "Caffeine Above Safe Daily Limit", "moderate",
              f"Average caffeine {mean_caf:.0f} mg/day is above the {limit:.0f} mg/day ceiling for this context.", 30)

    long_days = [p for p in per if p["sleep"] >= 10.5]
    if len(long_days) >= 4 and mean([p["screen"] for p in long_days]) >= 9.0:
        alert("HYPERSOMNIA", "Excessive Sleep / Hypersomnia & Sedentary Screen Fatigue", "elevated",
              f"{len(long_days)} days with 10.5 h or more of sleep plus about "
              f"{mean([p['screen'] for p in long_days]):.0f} h of screen time. Chronic long sleep with heavy screen load can "
              "signal circadian dysregulation or non-restorative sleep, so it is not counted as optimal recovery.", 45)

    if sd_sleep >= 2.0 and wk_deficit >= 10.0 and rebound >= 2.0:
        alert("SOCIAL_JETLAG", "Severe Social Jetlag & Circadian Whiplash", "critical",
              f"Weekday sleep averages {wk_mean:.1f} h (a {wk_deficit:.1f} h weekday deficit) and weekends rebound to "
              f"{we_mean:.1f} h. Sleep varies by {sd_sleep:.1f} h (SD), so a 7-day average of {mean_sleep:.1f} h hides the strain.", 60)
    elif sjl >= 2.0:
        alert("SOCIAL_JETLAG_MILD", "Social Jetlag (Weekend Phase Shift)", "moderate",
              f"Your sleep midpoint moves about {sjl:.1f} h between weekdays and weekends.", 35)

    late_days = [p for p in per if p["late_caffeine"]]
    hidden = (7.0 <= mean_sleep <= 7.5 and mean_screen >= 9.0 and
              (mean_caf >= 350 or len(late_days) >= 3))
    if hidden or (caff_pen + screen_pen) >= 20.0:
        alert("ARCH_SUPPRESSED", "Suppressed Deep/REM Sleep Architecture", "elevated",
              f"Caffeine has a ~5 h half-life: about {mean_resid:.0f} mg is still active at bedtime on average, and "
              f"{mean_screen:.0f} h of daily screen time delays melatonin. Deep (slow-wave) and REM sleep are reduced "
              f"even when the clock total looks near {mean_sleep:.1f} h.", 35)

    if prof["shift"] and swing > 3.0:
        alert("SHIFT_FLIPFLOP", "Erratic Day/Night Schedule Flip-Flop", "elevated",
              f"Your sleep midpoint swings {swing:.1f} h across the week (limit 3 h). Shift workers recover best "
              "with a stable anchor, even if that anchor is during the day.", 45)
    if not prof["shift"] and not prof["teen"] and 10.0 <= mid_mean <= 20.0:
        alert("DAYTIME_ANCHOR", "Daytime Sleep Anchor Without a Shift Context", "moderate",
              f"Your average sleep midpoint is {fmt_clock(mid_mean)}, which is daytime. If you work nights, choose the "
              "Shift / Night Worker context so the schedule is built around it.", 40)

    if cum_debt >= 18:
        alert("DEBT_SEVERE", "Severe Cumulative Sleep Debt", "critical",
              f"{cum_debt:.1f} h of unrepaid sleep debt against a {base:.1f} h baseline.", 75)
    elif cum_debt >= 10:
        alert("DEBT_HIGH", "High Cumulative Sleep Debt", "elevated",
              f"{cum_debt:.1f} h of unrepaid sleep debt against a {base:.1f} h baseline.", 50)

    if any(a["code"] == "HYPERSOMNIA" for a in alerts):
        eff = min(eff, 70.0)

    # ---- weighted composite
    debt_score = min(100.0, cum_debt / DEBT_FULL_SCALE_H * 100)
    caf_score = min(100.0, max(0.0, mean_caf / limit - 0.5) * 100)
    resid_ref = 150.0 * min(1.0, limit / 400.0)
    resid_score = min(100.0, mean_resid / resid_ref * 100)
    caffeine_comp = 0.5 * caf_score + 0.5 * resid_score
    screen_score = min(100.0, max(0.0, mean_screen - 4.0) / 8.0 * 100)
    cons_pen = min(100.0, 0.6 * (sd_mid / 2.5 * 100) + 0.4 * (sd_sleep / 3.0 * 100))
    consistency_score = 100.0 - cons_pen
    arch_score = min(100.0, (100.0 - eff) / 50.0 * 100)

    comps = {
        "sleep_debt": debt_score, "caffeine": caffeine_comp, "screen": screen_score,
        "consistency": cons_pen, "architecture": arch_score,
    }
    raw = sum(WEIGHTS[k] * v for k, v in comps.items())
    floor = max([a["floor"] for a in alerts], default=0)
    floor_driver = next((a["title"] for a in sorted(alerts, key=lambda a: -a["floor"]) if a["floor"] == floor), None) if floor else None
    score = int(min(100, max(round(raw), floor)))
    band = band_for(score)
    recovery = 100 - score
    if any(a["code"] == "HYPERSOMNIA" for a in alerts):
        recovery = min(recovery, 55)

    # ---- trajectory
    mid_idx = n // 2
    debt_mid = per[mid_idx - 1]["running_debt"] if mid_idx >= 1 else 0.0
    delta = cum_debt - debt_mid
    if delta >= 2.0:
        traj_key, traj_label = "escalating", "Escalating"
    elif delta <= -2.0:
        traj_key, traj_label = "recovering", "Recovering"
    else:
        traj_key, traj_label = "stable", "Holding Steady"
    projected = int(min(100, max(0, round(score + max(-15.0, min(20.0, delta * 2.5))))))
    if traj_key == "recovering" and score >= 50:
        traj_note = "Debt is shrinking, but it is still high."
    elif traj_key == "escalating":
        traj_note = "Debt grew over the second half of the log. Unchanged habits point to a higher score next week."
    elif traj_key == "recovering":
        traj_note = "Debt is shrinking. Keep the same pattern."
    else:
        traj_note = "Debt is roughly flat. Next week looks like this week unless something changes."

    # ---- anchors for the daily schedule
    wake_anchor = circ_mean([d["wake"] for d in days])
    target_bed = (wake_anchor - base) % 24
    anchors = {
        "wake": fmt_clock(wake_anchor),
        "sunlight": fmt_clock(wake_anchor + 0.25),
        "first_caffeine_after": fmt_clock(wake_anchor + 1.5),
        "deep_work_start": fmt_clock(wake_anchor + 2.0),
        "deep_work_end": fmt_clock(wake_anchor + 5.0),
        "caffeine_cutoff": fmt_clock(target_bed - 10.0),
        "digital_sunset": fmt_clock(target_bed - 1.5),
        "wind_down": fmt_clock(target_bed - 1.0),
        "sleep_anchor": fmt_clock(target_bed),
        "target_sleep_hours": r2(base),
        "caffeine_limit_mg": r2(limit),
    }

    metrics = {
        "cumulative_sleep_debt_h": r2(cum_debt),
        "architecture_efficiency_pct": r2(eff),
        "caffeine_residual_at_bedtime_mg": r2(mean_resid),
        "caffeine_residual_peak_mg": r2(max(resids)),
        "circadian_consistency_score": r2(consistency_score),
        "midpoint_sd_h": r2(sd_mid), "midpoint_swing_h": r2(swing), "midpoint_mean": fmt_clock(mid_mean),
        "mean_sleep_h": r2(mean_sleep), "sleep_sd_h": r2(sd_sleep),
        "mean_screen_h": r2(mean_screen), "mean_caffeine_mg": r2(mean_caf),
        "weekday_mean_sleep_h": r2(wk_mean), "weekend_mean_sleep_h": r2(we_mean),
        "weekday_deficit_h": r2(wk_deficit), "weekend_rebound_h": r2(rebound), "social_jetlag_h": r2(sjl),
    }
    components = []
    labels = {"sleep_debt": "Cumulative sleep debt", "caffeine": "Caffeine load & bedtime residual",
              "screen": "Screen exposure", "consistency": "Circadian inconsistency", "architecture": "Architecture fragmentation"}
    for k in WEIGHTS:
        components.append({"key": k, "label": labels[k], "score": r2(comps[k]), "weight": WEIGHTS[k],
                           "contribution": r2(WEIGHTS[k] * comps[k])})

    audit = {
        "formulas": [
            {"name": "7-Day Sleep Debt",
             "formula": "gap = baseline − sleep. If gap > 0: debt += gap. Otherwise: debt = max(0, debt + 0.5 × gap). "
                        "Surplus sleep repays only half as fast as a deficit builds. Start at debt = 0."},
            {"name": "Caffeine Half-Life Residual",
             "formula": "residual = caffeine_mg × 0.5^(hours from last caffeine to bedtime ÷ 5). "
                        "Upper-bound estimate: the whole day's caffeine is treated as taken at the last-caffeine time."},
            {"name": "Circadian Midpoint Variance",
             "formula": "midpoint = bedtime + ((wake − bedtime) mod 24) ÷ 2. Midpoints are averaged on the 24 h circle; "
                        "variance = RMS of each midpoint's circular deviation from that mean."},
            {"name": "Architecture Efficiency",
             "formula": "100 − min(30, 0.2 × mean residual) − min(15, 1.5 × max(0, mean screen − 4)) "
                        "− min(15, 5 × midpoint SD) − min(20, 3 × max(0, baseline − mean sleep)), floor 20."},
            {"name": "Weighted Burnout Composite Score",
             "formula": "0.35·DebtScore + 0.15·CaffeineScore + 0.15·ScreenScore + 0.20·InconsistencyScore + "
                        "0.15·ArchitectureScore, then raised to the highest guardrail floor if one applies. "
                        f"DebtScore = min(100, debt ÷ {DEBT_FULL_SCALE_H:.0f} × 100); "
                        "CaffeineScore = ½·min(100, max(0, mean caffeine ÷ limit − 0.5) × 100) + "
                        "½·min(100, mean residual ÷ reference × 100); "
                        "ScreenScore = min(100, max(0, mean screen − 4) ÷ 8 × 100); "
                        "InconsistencyScore = min(100, 0.6·(midpoint SD ÷ 2.5) × 100 + 0.4·(sleep SD ÷ 3) × 100); "
                        "ArchitectureScore = min(100, (100 − efficiency) ÷ 50 × 100)."},
        ],
        "inputs": {"baseline_sleep_h": r2(base), "caffeine_limit_mg": r2(limit), "half_life_h": HALF_LIFE_H,
                   "repay_rate": REPAY_RATE},
        "penalties": {"caffeine": r2(caff_pen), "screen": r2(screen_pen), "fragmentation": r2(frag_pen),
                      "short_sleep": r2(short_pen)},
        "raw_score": r2(raw), "floor": floor, "floor_driver": floor_driver,
    }

    for p in per:
        p.pop("midpoint_h", None)
    return {
        "profile": {k: prof[k] for k in ("key", "label", "custom_text", "age", "baseline_sleep", "caffeine_limit", "reasons")},
        "days": per, "metrics": metrics, "alerts": alerts, "notes": inp.get("notes", []),
        "burnout": {"score": score, "band": band["key"], "label": band["label"], "raw_score": r2(raw),
                    "floor_applied": bool(floor and score == floor and round(raw) < floor), "floor": floor,
                    "components": components, "recovery_score": recovery},
        "trajectory": {"key": traj_key, "label": traj_label, "debt_mid_week": r2(debt_mid), "debt_end": r2(cum_debt),
                       "projected_risk_next_week": projected, "note": traj_note},
        "anchors": anchors, "audit": audit,
    }


# ----------------------------------------------------------------------------- what-if
def apply_adjustments(inp: dict, adj: dict) -> tuple[dict, list[str]]:
    """Return a modified copy of a validated input, plus plain-English descriptions of the changes."""
    if not isinstance(adj, dict):
        raise BadInput(["'adjustments' must be an object."])
    problems = []

    def num(name, lo, hi):
        v = adj.get(name)
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        x, st = _num(v)
        if st != "ok" or not (lo <= x <= hi):
            problems.append(f"'{name}' must be a number from {lo:g} to {hi:g}.")
            return None
        return x

    extra = num("extra_sleep_hours", 0, 3)
    cutoff = num("caffeine_cutoff_hours_before_bed", 0, 16)
    cap = num("caffeine_cap_mg", 0, 1200)
    screen_cut = num("screen_reduction_hours", 0, 12)
    lock = bool(adj.get("lock_schedule"))
    if problems:
        raise BadInput(problems)

    days = [dict(d) for d in inp["days"]]
    changes = []
    wake_mean = circ_mean([d["wake"] for d in days])
    bed_mean = circ_mean([d["bed"] for d in days])
    if extra:
        bed_mean = (bed_mean - extra) % 24
    for d in days:
        if extra:
            d["sleep"] = max(d["sleep"], min(d["sleep"] + extra, 24 - d["screen"], 12.0))
            d["bed"] = (d["bed"] - extra) % 24
            d["window"] = (d["wake"] - d["bed"]) % 24 or d["sleep"]
        if screen_cut:
            d["screen"] = max(0.0, d["screen"] - screen_cut)
        if cap is not None:
            d["caffeine"] = min(d["caffeine"], cap)
        if cutoff and d["caffeine"] > 0 and d["last"] is not None:
            if (d["bed"] - d["last"]) % 24 < cutoff:
                d["last"] = (d["bed"] - cutoff) % 24
        if lock:
            d["bed"], d["wake"] = bed_mean, wake_mean
            d["window"] = (d["wake"] - d["bed"]) % 24 or d["sleep"]
    if extra:
        changes.append(f"{extra:g} more hour(s) of sleep each night")
    if cutoff:
        changes.append(f"last caffeine at least {cutoff:g} h before bed")
    if cap is not None:
        changes.append(f"caffeine capped at {cap:g} mg/day")
    if screen_cut:
        changes.append(f"{screen_cut:g} fewer hour(s) of screen time per day")
    if lock:
        changes.append("the same bedtime and wake time every day")
    if not changes:
        raise BadInput(["Choose at least one change to simulate (more sleep, a caffeine cutoff, a caffeine cap, "
                        "less screen time, or a fixed schedule)."])
    out = dict(inp)
    out["days"] = days
    return out, changes

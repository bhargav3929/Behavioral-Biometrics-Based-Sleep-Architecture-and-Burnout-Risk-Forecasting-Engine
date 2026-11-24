"""Glue: validated log -> deterministic engine -> Groq coach -> one response."""
import json

from . import ai_groq, chronobiology as chrono, config

SYSTEM_PROMPT = """You are a Circadian & Recovery Coach for a wellness education app.
You receive a 7-14 day self-logged behaviour summary that was ALREADY analysed by a deterministic engine.
Rules:
- Never change, recompute or contradict the numbers or the burnout score you are given. Explain them.
- You are not a doctor. Never diagnose a sleep disorder or medical condition. Do not name medicines or doses.
- Write plain English for a non-expert, short sentences, no jargon without a quick explanation.
- If a guardrail alert is present (adolescent, pregnancy, caffeine ceiling, hypersomnia, social jetlag), address it directly and kindly.
- The daily schedule MUST use the anchor times provided (wake, sunlight, deep-work window, caffeine cutoff, digital sunset, wind-down, sleep anchor). Do not invent different anchors.
- Reply with ONE JSON object only, no markdown, no commentary."""

SCHEMA_TEXT = """JSON schema (all fields required unless noted):
{
  "headline": "one sentence verdict that matches the score band",
  "outlook": "2-3 sentences: what the next 7 days look like if habits stay the same",
  "bottlenecks": [{"title": "short name", "detail": "1-2 sentences naming the behaviour and its real numbers"}],   // 2 to 5 items, biggest first
  "schedule": [{"time": "HH:MM", "title": "short action", "detail": "one sentence", "category": "sunlight|focus|caffeine|movement|meals|screens|winddown|sleep"}],  // 8 to 12 blocks covering wake to sleep anchor, in time order starting at the wake anchor
  "priorities": ["3 short, specific changes for this week"],
  "comparison": "optional string; only for what-if runs"
}"""


def _digest(analysis: dict) -> dict:
    m = analysis["metrics"]
    return {
        "context": analysis["profile"],
        "burnout": {k: analysis["burnout"][k] for k in ("score", "label")},
        "trajectory": analysis["trajectory"],
        "metrics": m,
        "alerts": [{"title": a["title"], "severity": a["severity"], "detail": a["detail"]} for a in analysis["alerts"]],
        "score_components": [{"label": c["label"], "score": c["score"], "contribution": c["contribution"]}
                             for c in analysis["burnout"]["components"]],
        "anchors": analysis["anchors"],
        "days": [{"day": d["day"], "sleep_h": d["sleep"], "bed": d["bedtime"], "wake": d["wake"], "screen_h": d["screen"],
                  "caffeine_mg": d["caffeine"], "last_caffeine": d["last_caffeine"], "residual_mg": d["residual_mg"],
                  "running_debt_h": d["running_debt"]} for d in analysis["days"]],
    }


def _prompt_forecast(analysis: dict) -> str:
    return ("Analysis (authoritative, do not alter):\n" + json.dumps(_digest(analysis), ensure_ascii=False) +
            "\n\nWrite the burnout forecast explanation, the root behavioural bottlenecks and the hour-by-hour "
            "recovery schedule for one day.\n" + SCHEMA_TEXT)


def _prompt_simulation(base: dict, sim: dict, changes: list[str]) -> str:
    return ("CURRENT habits (authoritative):\n" + json.dumps(_digest(base), ensure_ascii=False) +
            "\n\nWHAT-IF habits after these changes: " + "; ".join(changes) + "\n" +
            json.dumps(_digest(sim), ensure_ascii=False) +
            "\n\nThe schedule you write is for the WHAT-IF habits. Fill \"comparison\" with 2-3 sentences on what "
            "improves and what still needs work, quoting the before/after score and sleep debt. Bottlenecks should "
            "list what is STILL holding recovery back after the changes.\n" + SCHEMA_TEXT)


def _order_schedule(coach: ai_groq.CoachOut, wake_clock: str) -> list[dict]:
    wake = chrono.parse_clock(wake_clock) or 0.0
    blocks = []
    for b in coach.schedule:
        t = chrono.parse_clock(b.time)
        blocks.append({"time": b.time, "title": b.title, "detail": b.detail, "category": b.category,
                       "offset": (t - wake) % 24})
    blocks.sort(key=lambda x: x["offset"])
    for b in blocks:
        b.pop("offset")
    return blocks


def _coach_dict(coach: ai_groq.CoachOut, anchors: dict) -> dict:
    return {
        "headline": coach.headline, "outlook": coach.outlook,
        "bottlenecks": [b.model_dump() for b in coach.bottlenecks],
        "schedule": _order_schedule(coach, anchors["wake"]),
        "priorities": coach.priorities, "comparison": coach.comparison,
    }


def _common(inp: dict) -> dict:
    return {"disclaimer": config.DISCLAIMER, "context": inp["context"]}


def score_summary(a: dict) -> dict:
    return {
        "score": a["burnout"]["score"], "label": a["burnout"]["label"], "band": a["burnout"]["band"],
        "sleep_debt_h": a["metrics"]["cumulative_sleep_debt_h"],
        "architecture_efficiency_pct": a["metrics"]["architecture_efficiency_pct"],
        "caffeine_residual_mg": a["metrics"]["caffeine_residual_at_bedtime_mg"],
        "consistency": a["metrics"]["circadian_consistency_score"],
    }


async def run_forecast(inp: dict) -> dict:
    analysis = chrono.analyze(inp)
    coach, model = await ai_groq.coach_complete(SYSTEM_PROMPT, _prompt_forecast(analysis))
    out = {"kind": "forecast", "model": model, **_common(inp), **analysis}
    out["coach"] = _coach_dict(coach, analysis["anchors"])
    return out


async def run_simulation(inp: dict, adjustments: dict) -> dict:
    sim_inp, changes = chrono.apply_adjustments(inp, adjustments)
    base = chrono.analyze(inp)
    sim = chrono.analyze(sim_inp)
    coach, model = await ai_groq.coach_complete(SYSTEM_PROMPT, _prompt_simulation(base, sim, changes))
    b, s = score_summary(base), score_summary(sim)
    deltas = {
        "score": s["score"] - b["score"],
        "sleep_debt_h": round(s["sleep_debt_h"] - b["sleep_debt_h"], 2),
        "architecture_efficiency_pct": round(s["architecture_efficiency_pct"] - b["architecture_efficiency_pct"], 2),
        "caffeine_residual_mg": round(s["caffeine_residual_mg"] - b["caffeine_residual_mg"], 2),
        "consistency": round(s["consistency"] - b["consistency"], 2),
    }
    out = {"kind": "simulation", "model": model, **_common(inp), "changes": changes,
           "baseline": base, "simulated": sim, "baseline_summary": b, "simulated_summary": s, "deltas": deltas}
    out["coach"] = _coach_dict(coach, sim["anchors"])
    return out

"use strict";
/* HTML renderers for the live stage (right pane). Depends on helpers in charts.js. */

const CHART_LEGEND = `<div class="legend"><span><i style="background:#A78BFA"></i>Sleep (hrs)</span><span><i style="background:#34D399"></i>Age-adjusted baseline</span><span><i style="background:rgba(148,163,184,.5)"></i>Screen time (hrs)</span><span><i style="background:#FF6B4A"></i>Caffeine still active at bedtime (mg, right axis)</span></div>`;

function loadingHtml(msg) {
  return `<div class="card loading"><div class="spin"></div><div><b>${esc(msg)}</b><div class="hint">The numbers are computed first, then the AI coach writes the plan. This usually takes 10 to 30 seconds.</div></div></div>`;
}

function emptyHtml(title, text, goView) {
  return `<div class="card empty"><h2>${esc(title)}</h2><p>${esc(text)}</p>${goView ? `<button class="btn" type="button" data-go="${goView}">Go to the forecast</button>` : ""}</div>`;
}

function rejectHtml(r) {
  const items = (r.details && r.details.length ? r.details : [r.error]).map((d) => `<li>${esc(d)}</li>`).join("");
  return `<div class="card reject"><h2>Log rejected: no forecast was made</h2>
    <p>These numbers are physiologically impossible or incomplete. Nothing was sent to the AI and no run was used from your hourly allowance.</p><ul>${items}</ul></div>`;
}

function kpisHtml(m) {
  const tile = (cls, k, v, u, n) => `<div class="kpi ${cls}"><div class="k">${k}</div><div class="v">${v}<small> ${u}</small></div><div class="n">${n}</div></div>`;
  return `<div class="kpis">
    ${tile("coral", "7-Day Sleep Debt", n1(m.cumulative_sleep_debt_h), "h", "Unrepaid; weekend sleep repays at 50% credit")}
    ${tile("lav", "Deep/REM Efficiency", Math.round(m.architecture_efficiency_pct), "%", "After caffeine, screen and timing penalties")}
    ${tile("amber", "Bedtime Caffeine Residual", Math.round(m.caffeine_residual_at_bedtime_mg), "mg", "Average still active at lights-out (5 h half-life)")}
    ${tile("mint", "Circadian Consistency", Math.round(m.circadian_consistency_score), "/100", `Midpoint ±${n1(m.midpoint_sd_h)} h, sleep ±${n1(m.sleep_sd_h)} h`)}
  </div>`;
}

function alertsHtml(alerts) {
  if (!alerts.length) return `<div class="alerts"><div class="alert ok"><strong>No guardrail alerts</strong><p>Nothing in this log tripped a chronobiology safety rule.</p></div></div>`;
  return `<div class="alerts">${alerts.map((a) => `<div class="alert sev-${esc(a.severity)}"><strong>${esc(a.title)}</strong><p>${esc(a.detail)}</p></div>`).join("")}</div>`;
}

function heroHtml(r, c) {
  const b = r.burnout, t = r.trajectory;
  const floor = b.floor_applied ? `<p class="hint" style="margin-top:8px">Safety guardrail applied: the raw weighted score was ${Math.round(b.raw_score)}, raised to ${b.floor} by a guardrail alert.</p>` : "";
  return `<div class="card b-${esc(b.band)}"><div class="hero">
    <div class="gauge">${gaugeSvg(b.score, b.band)}<span class="pill">${esc(b.label)}</span></div>
    <div>
      <div class="lbl" style="margin-top:0">7-day trajectory verdict</div>
      <h2>${esc(c.headline)}</h2>
      <p>${esc(c.outlook)}</p>
      <div class="traj"><span>Trajectory <b>${esc(t.label)}</b></span><span>Next week <b>${t.projected_risk_next_week}</b></span><span>Sleep target <b>${n1(r.anchors.target_sleep_hours)} h</b></span><span>Caffeine ceiling <b>${Math.round(r.anchors.caffeine_limit_mg)} mg</b></span></div>
      <p class="hint" style="margin-top:8px">${esc(t.note)}</p>${floor}
    </div></div></div>`;
}

function alertsCard(r) {
  const notes = [...(r.notes || []), ...(r.profile.reasons || [])];
  return `<div class="card"><div class="pane-head"><h2>Chronobiology guardrail alerts</h2></div>${alertsHtml(r.alerts)}${notes.length ? `<div class="small-notes">${notes.map(esc).join("<br>")}</div>` : ""}</div>`;
}

function chartCard(title) {
  return `<div class="card chart"><div class="pane-head"><h2>${esc(title)}</h2></div>${CHART_LEGEND}<div class="chart-host"></div></div>`;
}

function coachCards(c, bottleneckTitle, prioTitle) {
  return `<div class="two">
    <div class="card"><h3>${esc(bottleneckTitle)}</h3><ul class="bl">${c.bottlenecks.map((x) => `<li><strong>${esc(x.title)}</strong>${esc(x.detail)}</li>`).join("")}</ul></div>
    <div class="card"><h3>${esc(prioTitle)}</h3><ol class="prio">${c.priorities.map((x) => `<li>${esc(x)}</li>`).join("")}</ol></div>
  </div><div style="height:16px"></div>`;
}

function timelineHtml(blocks) {
  return `<ol class="timeline">${blocks.map((b) => `<li class="tl cat-${esc(b.category)}"><div class="time">${esc(b.time)}</div><div class="node"></div><div class="body"><div class="cat">${esc(b.category)}</div><h4>${esc(b.title)}</h4><p>${esc(b.detail)}</p></div></li>`).join("")}</ol>`;
}

function anchorsHtml(a) {
  const box = (k, v) => `<div class="anchor">${k}<b>${esc(v)}</b></div>`;
  return `<div class="anchors">${box("Sunlight", a.sunlight)}${box("Deep work", a.deep_work_start + "–" + a.deep_work_end)}${box("Caffeine cutoff", a.caffeine_cutoff)}${box("Digital sunset", a.digital_sunset)}${box("Wind-down", a.wind_down)}${box("Sleep anchor", a.sleep_anchor)}</div>`;
}

function scheduleCard(r, c, title) {
  return `<div class="card"><div class="pane-head"><h2>${esc(title)}</h2><span class="tag mono">wake ${esc(r.anchors.wake)} → sleep ${esc(r.anchors.sleep_anchor)}</span></div>
    ${ribbon24Html(r.anchors, c.schedule)}${timelineHtml(c.schedule)}</div>`;
}

function auditHtml(r) {
  const a = r.audit, days = r.days;
  const rows = days.map((d) => `<tr><td>${esc(d.day)}</td><td>${d.sleep.toFixed(2)}</td><td>${sgn(d.gap_vs_baseline, 2)}</td><td>${d.running_debt.toFixed(2)}</td><td>${esc(d.bedtime)}→${esc(d.wake)}</td><td>${esc(d.midpoint)}</td><td>${d.caffeine.toFixed(0)}</td><td>${esc(d.last_caffeine || "–")}</td><td>${d.hours_caffeine_to_bed == null ? "–" : d.hours_caffeine_to_bed.toFixed(2)}</td><td>${d.residual_mg.toFixed(2)}</td></tr>`).join("");
  const comps = r.burnout.components.map((c) => `<tr><td>${esc(c.label)}</td><td>${c.score.toFixed(2)}</td><td>${c.weight.toFixed(2)}</td><td>${c.contribution.toFixed(2)}</td></tr>`).join("");
  return `<details class="audit"><summary>Chronobiology Formula &amp; Biometric Verification Audit</summary><div class="in">
    <p class="hint">Every number on this page comes from these formulas, computed before the AI is called. Baseline sleep ${a.inputs.baseline_sleep_h} h, caffeine ceiling ${a.inputs.caffeine_limit_mg} mg, half-life ${a.inputs.half_life_h} h.</p>
    ${a.formulas.map((f) => `<div class="formula"><b>${esc(f.name)}</b><span>${esc(f.formula)}</span></div>`).join("")}
    <h3 style="margin:16px 0 6px">Day-by-day intermediate values</h3>
    <div class="tbl-wrap"><table class="plain"><thead><tr><th>Day</th><th>Sleep</th><th>Gap</th><th>Debt</th><th>Bed→Wake</th><th>Midpoint</th><th>Caff mg</th><th>Last</th><th>Hrs to bed</th><th>Residual mg</th></tr></thead><tbody>${rows}</tbody></table></div>
    <h3 style="margin:16px 0 6px">Weighted burnout composite</h3>
    <div class="tbl-wrap"><table class="plain" style="min-width:420px"><thead><tr><th>Component</th><th>Score</th><th>Weight</th><th>Adds</th></tr></thead><tbody>${comps}
      <tr><td><b>Raw weighted total</b></td><td></td><td></td><td>${a.raw_score.toFixed(2)}</td></tr>
      <tr><td><b>Guardrail floor${a.floor_driver ? " (" + esc(a.floor_driver) + ")" : ""}</b></td><td></td><td></td><td>${a.floor || "none"}</td></tr>
      <tr><td><b>Final burnout risk</b></td><td></td><td></td><td><b>${r.burnout.score}</b></td></tr></tbody></table></div>
    <p class="hint" style="margin-top:10px">Architecture penalties: caffeine ${a.penalties.caffeine}, screen ${a.penalties.screen}, fragmentation ${a.penalties.fragmentation}, short sleep ${a.penalties.short_sleep}.</p>
  </div></details>`;
}

function forecastHtml(r) {
  return heroHtml(r, r.coach) + kpisHtml(r.metrics) + alertsCard(r) + chartCard("Sleep architecture & caffeine wave") +
    coachCards(r.coach, "Root behavioural bottlenecks", "This week’s priorities") +
    scheduleCard(r, r.coach, "24-hour circadian recovery timeline") + auditHtml(r) +
    `<p class="hint">${esc(r.disclaimer)}</p>`;
}

function simHtml(r) {
  const b = r.baseline_summary, s = r.simulated_summary, d = r.deltas, c = r.coach, sim = r.simulated;
  const delta = (label, v, unit, lowerBetter, dec = 1) => {
    const better = lowerBetter ? v < 0 : v > 0;
    return `<div class="delta">${label}<b class="${v === 0 ? "" : better ? "good" : "bad"}">${sgn(v, dec)} ${unit}</b></div>`;
  };
  return `<div class="card"><div class="pane-head"><h2>Before and after</h2></div>
    <p class="hint">If you made these changes: ${r.changes.map(esc).join("; ")}.</p>
    <div class="compare">
      <div class="cmp b-${esc(b.band)}"><div class="t">Current habits</div><div class="s">${b.score}</div><span class="pill">${esc(b.label)}</span></div>
      <div class="arrow ${d.score < 0 ? "good" : d.score > 0 ? "bad" : ""}">→<br><small>${sgn(d.score, 0)}</small></div>
      <div class="cmp b-${esc(s.band)}"><div class="t">With your plan</div><div class="s">${s.score}</div><span class="pill">${esc(s.label)}</span></div>
    </div>
    <div class="deltas">${delta("Burnout risk", d.score, "pts", true, 0)}${delta("Sleep debt", d.sleep_debt_h, "h", true)}${delta("Deep/REM efficiency", d.architecture_efficiency_pct, "%", false)}${delta("Caffeine at bedtime", d.caffeine_residual_mg, "mg", true, 0)}${delta("Consistency", d.consistency, "pts", false, 0)}</div>
    <p style="margin-top:12px;color:#CBD5E1">${esc(c.comparison || c.headline)}</p></div>` +
    kpisHtml(sim.metrics) + alertsCard(sim) + chartCard("Simulated week") +
    coachCards(c, "What still holds recovery back", "Priorities for this plan") +
    scheduleCard(sim, c, "Daily timeline for the what-if plan") + auditHtml(sim) +
    `<p class="hint">${esc(r.disclaimer)}</p>`;
}

function scheduleHtml(src, hasBoth, which) {
  const toggle = hasBoth ? `<div class="toggle"><button type="button" data-src="forecast" class="${which === "forecast" ? "on" : ""}">Current habits</button><button type="button" data-src="sim" class="${which === "sim" ? "on" : ""}">What-if plan</button></div>` : "";
  const r = src.r, c = src.c;
  return `${toggle}<div class="card"><div class="pane-head"><h2>Daily Recovery Schedule</h2><span class="pill b-${esc(r.burnout.band)}">${esc(src.label)} · ${r.burnout.score}</span></div>
    <p class="hint">Built around your average wake time (${esc(r.anchors.wake)}) and a ${n1(r.anchors.target_sleep_hours)} h sleep target. The lavender band is your sleep window.</p>
    ${anchorsHtml(r.anchors)}${ribbon24Html(r.anchors, c.schedule)}${timelineHtml(c.schedule)}</div>
    <p class="hint">${esc(r.disclaimer || "")}</p>`;
}

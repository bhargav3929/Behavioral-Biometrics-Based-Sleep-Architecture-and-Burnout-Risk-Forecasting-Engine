"use strict";
/* Pure-SVG telemetry visuals: segmented burnout arc, sleep/caffeine wave chart, 24 h ribbon. */

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const n1 = (x) => (Math.round(x * 10) / 10).toFixed(1);
const sgn = (x, d = 1) => (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(d);
const clockH = (t) => { const [h, m] = String(t).split(":").map(Number); return h + m / 60; };

const BAND_COLOR = { critical: "#F87171", elevated: "#FB923C", moderate: "#FBBF24", optimal: "#34D399" };
const colorForScore = (v) => (v >= 75 ? BAND_COLOR.critical : v >= 50 ? BAND_COLOR.elevated : v >= 25 ? BAND_COLOR.moderate : BAND_COLOR.optimal);

/* 270 degree arc of 30 segments; lit up to the score, each segment tinted by the band it sits in. */
function gaugeSvg(score, band) {
  const cx = 110, cy = 110, r = 88, N = 30, gap = 2.2, start = 135, sweep = 270;
  const pt = (a) => [cx + r * Math.cos((a * Math.PI) / 180), cy + r * Math.sin((a * Math.PI) / 180)];
  let segs = "";
  for (let i = 0; i < N; i++) {
    const a0 = start + (sweep / N) * i + gap / 2, a1 = start + (sweep / N) * (i + 1) - gap / 2;
    const mid = ((i + 0.5) / N) * 100, lit = mid <= score + 1.2;
    const [x0, y0] = pt(a0), [x1, y1] = pt(a1);
    const col = colorForScore(mid);
    segs += `<path class="seg" d="M${x0.toFixed(2)} ${y0.toFixed(2)} A${r} ${r} 0 0 1 ${x1.toFixed(2)} ${y1.toFixed(2)}" fill="none" stroke="${col}" stroke-width="13" opacity="${lit ? 1 : 0.14}"${lit ? ` style="filter:drop-shadow(0 0 5px ${col})"` : ""}/>`;
  }
  const c = BAND_COLOR[band] || "#A78BFA";
  return `<svg viewBox="0 0 220 200" role="img" aria-label="Burnout risk ${score} out of 100">
    ${segs}
    <text x="${cx}" y="${cy + 6}" text-anchor="middle" font-family="JetBrains Mono, monospace" font-weight="700" font-size="52" fill="${c}" style="filter:drop-shadow(0 0 12px ${c}66)">${score}</text>
    <text x="${cx}" y="${cy + 28}" text-anchor="middle" font-family="JetBrains Mono, monospace" font-size="10" letter-spacing="1.6" fill="#94A3B8">BURNOUT RISK / 100</text>
    <text x="32" y="186" text-anchor="middle" font-family="JetBrains Mono, monospace" font-size="10" fill="#94A3B8">0</text>
    <text x="188" y="186" text-anchor="middle" font-family="JetBrains Mono, monospace" font-size="10" fill="#94A3B8">100</text></svg>`;
}

function smoothPath(pts) {
  if (pts.length < 2) return "";
  let d = `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
    const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
    const c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
    d += ` C${c1[0].toFixed(1)},${c1[1].toFixed(1)} ${c2[0].toFixed(1)},${c2[1].toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
  }
  return d;
}

/* Sleep hours (lavender wave) vs caffeine still active at bedtime (coral wave, right axis), screen bars, baseline. */
function drawWaveChart(host, r) {
  if (!host || !r) return;
  const W = Math.max(280, Math.floor(host.clientWidth || 600));
  const H = W < 480 ? 280 : 320;
  const m = { l: 32, r: W < 480 ? 34 : 42, t: 18, b: 26 };
  const n = r.days.length, base = r.profile.baseline_sleep;
  const maxH = Math.max(14, Math.ceil(Math.max(...r.days.map((d) => Math.max(d.sleep, d.screen)), base) + 1));
  const maxMg = Math.max(100, Math.ceil(Math.max(...r.days.map((d) => d.residual_mg)) / 50) * 50);
  const plotH = H - m.t - m.b, cw = (W - m.l - m.r) / n;
  const x = (i) => m.l + cw * (i + 0.5);
  const yH = (h) => m.t + plotH * (1 - h / maxH);
  const yM = (mg) => m.t + plotH * (1 - mg / maxMg);
  const bw = Math.min(cw * 0.5, 30);
  let s = `<defs>
    <linearGradient id="gSleep" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#A78BFA" stop-opacity=".38"/><stop offset="1" stop-color="#A78BFA" stop-opacity="0"/></linearGradient>
    <filter id="blurGlow" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="3.5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>`;
  for (let h = 0; h <= maxH; h += 2) s += `<line x1="${m.l}" x2="${W - m.r}" y1="${yH(h)}" y2="${yH(h)}" stroke="rgba(255,255,255,.06)"/><text x="${m.l - 6}" y="${yH(h) + 4}" text-anchor="end" font-size="10">${h}</text>`;
  for (let k = 0; k <= 4; k++) { const mg = (maxMg / 4) * k; s += `<text x="${W - m.r + 6}" y="${yM(mg) + 4}" font-size="10" style="fill:#FF8A6E">${Math.round(mg)}</text>`; }
  s += `<text x="${W - m.r + 6}" y="${m.t - 6}" font-size="9" style="fill:#FF8A6E">mg</text><text x="${m.l - 6}" y="${m.t - 6}" text-anchor="end" font-size="9">h</text>`;
  r.days.forEach((d, i) => {
    s += `<rect x="${x(i) - bw / 2}" y="${yH(d.screen)}" width="${bw}" height="${Math.max(0, yH(0) - yH(d.screen))}" rx="4" fill="rgba(148,163,184,.2)" stroke="rgba(148,163,184,.25)"><title>${esc(d.day)}: ${d.screen} h screen time</title></rect>`;
  });
  s += `<line x1="${m.l}" x2="${W - m.r}" y1="${yH(base)}" y2="${yH(base)}" stroke="#34D399" stroke-width="1.6" stroke-dasharray="6 5"/><text x="${m.l + 4}" y="${yH(base) - 6}" font-size="10" style="fill:#34D399">baseline ${base} h</text>`;
  const sp = r.days.map((d, i) => [x(i), yH(d.sleep)]);
  const sleepD = smoothPath(sp);
  s += `<path d="${sleepD} L${x(n - 1)},${yH(0)} L${x(0)},${yH(0)} Z" fill="url(#gSleep)"/>`;
  s += `<path d="${sleepD}" fill="none" stroke="#A78BFA" stroke-width="3" stroke-linecap="round" filter="url(#blurGlow)"/>`;
  const cp = r.days.map((d, i) => [x(i), yM(d.residual_mg)]);
  s += `<path d="${smoothPath(cp)}" fill="none" stroke="#FF6B4A" stroke-width="2.6" stroke-linecap="round" stroke-dasharray="1 0" filter="url(#blurGlow)"/>`;
  r.days.forEach((d, i) => {
    s += `<circle cx="${cp[i][0]}" cy="${cp[i][1]}" r="4" fill="#0D1019" stroke="#FF6B4A" stroke-width="2"><title>${esc(d.day)}: ${d.caffeine} mg caffeine, last at ${esc(d.last_caffeine || "n/a")}, ${d.residual_mg} mg still active at bedtime</title></circle>`;
    s += `<circle cx="${sp[i][0]}" cy="${sp[i][1]}" r="5" fill="#0D1019" stroke="#C4B5FD" stroke-width="2.5"><title>${esc(d.day)}: ${d.sleep} h sleep (${sgn(d.gap_vs_baseline, 1)} h vs baseline)</title></circle>`;
    if (cw >= 30) s += `<text x="${sp[i][0]}" y="${sp[i][1] - 11}" text-anchor="middle" font-size="10.5" font-weight="700" style="fill:#DDD6FE">${d.sleep}</text>`;
    s += `<text x="${x(i)}" y="${H - 6}" text-anchor="middle" font-size="11" style="fill:#F8FAFC;font-weight:600">${esc(d.day)}</text>`;
  });
  host.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Seven-day sleep, screen time and bedtime caffeine chart">${s}</svg>`;
}

/* 24 hour ribbon: sleep window plus a tick per schedule block. */
function ribbon24Html(anchors, blocks) {
  const sleepStart = clockH(anchors.sleep_anchor), wake = clockH(anchors.wake);
  const seg = (a, b) => `<div class="sleepseg" style="left:${(a / 24) * 100}%;width:${((b - a) / 24) * 100}%"></div>`;
  const segs = sleepStart > wake ? seg(sleepStart, 24) + seg(0, wake) : seg(sleepStart, wake);
  const ticks = blocks.map((b) => `<div class="tick ${esc(b.category)}" style="left:${(clockH(b.time) / 24) * 100}%" title="${esc(b.time)} ${esc(b.title)}"></div>`).join("");
  const hrs = [0, 6, 12, 18, 24].map((h) => `<span class="hr" style="left:${(h / 24) * 100}%">${String(h % 24).padStart(2, "0")}:00</span>`).join("");
  return `<div class="ribbon24" aria-hidden="true">${segs}${ticks}${hrs}</div>`;
}

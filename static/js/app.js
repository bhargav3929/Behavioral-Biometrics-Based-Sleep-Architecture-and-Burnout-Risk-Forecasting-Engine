"use strict";
/* App wiring: state, API calls, events. All URLs are relative so the app works under a sub-path. */

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const PRESETS = [
  "Standard Knowledge Worker", "Shift / Night Worker", "Student / Exam Week", "Teenager / Adolescent (13–17)",
  "Parent / Caregiver", "Pregnant / Postpartum", "Athlete / Heavy Training", "Custom Context...",
];
const CUSTOM = PRESETS[PRESETS.length - 1];
const COLS = [
  ["sleep", "Sleep (hrs)", "decimal", "7.5"], ["bed", "Bedtime", "text", "23:00"], ["wake", "Wake time", "text", "07:00"],
  ["screen", "Screen time (hrs)", "decimal", "5"], ["caffeine", "Caffeine (mg)", "numeric", "150"],
  ["last", "Last caffeine (24h clock)", "text", "10:00"],
];

const state = {
  info: null, samples: [], rows: [], context: PRESETS[0], custom: "", sampleId: null,
  forecast: null, sim: null, scheduleSource: "forecast", busy: false, view: "forecast",
};
const charts = {}; // container id -> analysis object drawn there

/* ---------------- ticket + fetch ---------------- */
function initTicket() {
  try {
    const p = new URLSearchParams(location.search);
    const t = p.get("ticket");
    if (t) {
      sessionStorage.setItem("lastsem_ticket", t);
      p.delete("ticket");
      const q = p.toString();
      history.replaceState(null, "", location.pathname + (q ? "?" + q : "") + location.hash);
    }
  } catch (e) { /* storage blocked: fine */ }
}
function ticket() { try { return sessionStorage.getItem("lastsem_ticket") || ""; } catch (e) { return ""; } }

async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  const t = ticket();
  if (t) headers["X-LastSem-Ticket"] = t;
  if (opts.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  let r;
  try { r = await fetch(path, { ...opts, headers }); }
  catch (e) { throw Object.assign(new Error("Cannot reach the app. Check that it is still running, then try again."), { code: "NETWORK" }); }
  let data = null;
  try { data = await r.json(); } catch (e) { /* not json */ }
  if (!r.ok) throw Object.assign(new Error((data && data.error) || "Something went wrong. Please try again."), { code: data && data.code, details: data && data.details, status: r.status });
  return data;
}

/* ---------------- notices ---------------- */
function notice(msg, action) {
  const el = $("#notice");
  if (!msg) { el.hidden = true; return; }
  el.innerHTML = `<span>${esc(msg)}</span>`;
  if (action) {
    const b = document.createElement("button");
    b.className = "btn"; b.type = "button"; b.textContent = action.label; b.onclick = action.run; el.appendChild(b);
  }
  el.hidden = false;
  el.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

/* ---------------- info / runs ---------------- */
async function loadInfo() {
  try { state.info = await api("api/info"); } catch (e) { notice(e.message); return; }
  const i = state.info;
  setRuns(i.limits.runs_left);
  $("#keysBtn").hidden = i.mode === "demo";
  $(".rail-btns").style.gridTemplateColumns = i.mode === "demo" ? "1fr" : "";
  $("#footInfo").textContent = `v${i.version} · ${i.mode} mode · ${i.ai.model}`;
  updateRunAvailability();
}
function setRuns(n) {
  $("#runsLeft").textContent = n; $("#runsLeftMini").textContent = n;
  $("#runsPill").classList.toggle("low", n <= 3);
}
function updateRunAvailability() {
  const i = state.info; if (!i) return;
  let off = false, hint = "";
  if (i.mode === "demo" && !(i.demo && i.demo.ticket_valid)) { off = true; hint = "Sign in on lastsem.com to try your own input. The sample logs work without it."; }
  else if (i.mode === "demo" && i.demo && i.demo.daily_cap_reached) { off = true; hint = "The demo is at its daily limit. The sample logs still work."; }
  else if (i.mode === "demo" && i.demo && i.demo.runs_left <= 0) { off = true; hint = "You have used all live runs on this ticket. The sample logs still work."; }
  else if (!i.ai.ready && i.mode === "local") { hint = "Add your free Groq key under API Keys to run the AI coach."; }
  $$("#runBtn, #simBtn").forEach((b) => (b.disabled = off || state.busy));
  $("#runHint").textContent = hint; $("#simHint").textContent = hint;
}

/* ---------------- navigation ---------------- */
function openRail(open) {
  $("#rail").classList.toggle("open", open); $("#railScrim").hidden = !open; $("#menuBtn").setAttribute("aria-expanded", String(open));
}
$("#menuBtn").onclick = () => openRail(!$("#rail").classList.contains("open"));
$("#railScrim").onclick = () => openRail(false);

function show(view, scroll = true) {
  state.view = view;
  $$(".view").forEach((v) => (v.hidden = v.id !== "view-" + view));
  $$("#nav button").forEach((b) => b.classList.toggle("on", b.dataset.view === view));
  if (view === "whatif") updateWhatifSummary();
  if (view === "schedule") renderSchedulePage();
  redrawCharts();
  openRail(false);
  if (!scroll) return;
  if (window.innerWidth <= 1060) $(".live").scrollIntoView({ behavior: "smooth", block: "start" }); else window.scrollTo({ top: 0 });
}
$("#nav").addEventListener("click", (e) => { const b = e.target.closest("button[data-view]"); if (b) show(b.dataset.view); });

/* ---------------- matrix ---------------- */
const blankRows = () => DAYS.map((d) => ({ day: d, sleep: "", bed: "", wake: "", screen: "", caffeine: "", last: "" }));
function drawMatrix() {
  $("#matrix tbody").innerHTML = state.rows.map((r, i) => {
    const cells = COLS.map(([k, label, mode, ph]) =>
      `<td><input data-i="${i}" data-k="${k}" inputmode="${mode}" autocomplete="off" placeholder="${ph}" value="${esc(r[k])}" aria-label="${esc(label)}, day ${i + 1}"></td>`).join("");
    return `<tr><td>${esc(r.day)}<small>D${i + 1}</small></td>${cells}</tr>`;
  }).join("");
}
$("#matrix").addEventListener("input", (e) => {
  const el = e.target; if (!el.dataset.k) return;
  state.rows[+el.dataset.i][el.dataset.k] = el.value; el.classList.remove("bad");
});
const rowsFromParsed = (days) => days.map((d, i) => ({
  day: d.day || DAYS[i % 7], sleep: d.sleep_hours ?? "", bed: d.bedtime ?? "", wake: d.wake_time ?? "",
  screen: d.screen_hours ?? "", caffeine: d.caffeine_mg ?? "", last: d.last_caffeine ?? "",
}));
function payload() {
  return {
    days: state.rows.map((r) => ({ day: r.day, sleep_hours: r.sleep, bedtime: r.bed, wake_time: r.wake, screen_hours: r.screen, caffeine_mg: r.caffeine, last_caffeine: r.last })),
    context: state.context,
    custom_context: state.context === CUSTOM || state.custom ? state.custom : "",
  };
}

/* ---------------- context pills ---------------- */
function drawPills() {
  $("#pills").innerHTML = PRESETS.map((p) => `<button type="button" class="chip${p === state.context ? " on" : ""}" role="radio" aria-checked="${p === state.context}" data-p="${esc(p)}">${esc(p)}</button>`).join("");
  const c = $("#customCtx"); c.hidden = state.context !== CUSTOM; c.value = state.custom;
}
$("#pills").addEventListener("click", (e) => {
  const b = e.target.closest("[data-p]"); if (!b) return;
  state.context = b.dataset.p; drawPills();
  if (state.context === CUSTOM) $("#customCtx").focus();
});
$("#customCtx").addEventListener("input", (e) => { state.custom = e.target.value; });
function setContext(ctx) {
  if (!ctx) return;
  if (PRESETS.includes(ctx)) { state.context = ctx; state.custom = ""; } else { state.context = CUSTOM; state.custom = ctx; }
  drawPills();
}

/* ---------------- samples ---------------- */
const SHORT = { "tech-crunch-burnout-week": "Tech crunch week", "balanced-circadian-baseline": "Balanced baseline", "social-jetlag-late-caffeine": "Social jetlag + late caffeine", "invalid-biometric-log-control": "Invalid log control" };
function drawSampleChips() {
  $("#sampleBtns").innerHTML = state.samples.map((s) =>
    `<button type="button" class="chip sample${s.id === state.sampleId ? " on" : ""}" data-s="${esc(s.id)}" title="${esc(s.title)}${s.has_saved_result ? "" : " (no saved result)"}"><span class="${s.has_saved_result ? "ok" : "no"}">${s.has_saved_result ? "●" : "○"}</span>${esc(SHORT[s.id] || s.title)}</button>`).join("");
}
async function loadSamples() {
  try { state.samples = (await api("api/samples")).samples; } catch (e) { return; }
  drawSampleChips();
}
$("#sampleBtns").addEventListener("click", (e) => { const b = e.target.closest("[data-s]"); if (b) openSample(b.dataset.s); });

function renderInto(id, html, data) {
  const el = $("#" + id); el.innerHTML = html;
  $$("[data-go]", el).forEach((b) => (b.onclick = () => show(b.dataset.go)));
  if (data) { charts[id] = data; drawChartsIn(el, id); } else delete charts[id];
}
function drawChartsIn(el, id) { const h = $(".chart-host", el); if (h && charts[id]) drawWaveChart(h, charts[id]); }
function redrawCharts() { Object.keys(charts).forEach((id) => { const el = $("#" + id); if (el && el.offsetParent !== null) drawChartsIn(el, id); }); }
let rz; window.addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(redrawCharts, 120); });

async function openSample(id, quiet) {
  let s;
  try { s = await api("api/samples/" + encodeURIComponent(id)); } catch (e) { notice(e.message); return; }
  state.sampleId = id;
  if (s.input) { state.rows = rowsFromParsed(s.input.days); setContext(s.input.context || PRESETS[0]); drawMatrix(); }
  drawSampleChips(); notice("");
  show("forecast", !quiet);
  if (!s.result) { renderInto("forecastOut", `<div class="banner">This sample has no saved result yet. Press the forecast button to analyse it live.</div>`); return; }
  const banner = `<div class="banner">Saved result from a real recorded run of this sample. It used none of your runs. Press <b>Forecast Burnout &amp; Build Recovery Plan</b> to analyse the table live.</div>`;
  if (s.result.code) { state.forecast = null; renderInto("forecastOut", banner + rejectHtml(s.result)); markBadRows(s.result.details); }
  else { state.forecast = s.result; state.scheduleSource = "forecast"; renderInto("forecastOut", banner + forecastHtml(s.result), s.result); }
}

/* ---------------- paste / reset ---------------- */
$("#pasteBtn").addEventListener("click", async () => {
  try {
    const r = await api("api/parse-log", { method: "POST", body: JSON.stringify({ log_text: $("#pasteBox").value }) });
    state.rows = rowsFromParsed(r.days); if (r.context) setContext(r.context); drawMatrix(); state.sampleId = null; drawSampleChips();
    notice(`Filled ${r.days.length} day(s) from your text. Check the numbers, then run the forecast.`);
  } catch (e) { notice(e.message); }
});
$("#clearBtn").addEventListener("click", () => { state.rows = blankRows(); state.sampleId = null; drawSampleChips(); drawMatrix(); notice(""); });

/* ---------------- live runs ---------------- */
function markBadRows(details) {
  $$("#matrix input").forEach((i) => i.classList.remove("bad"));
  (details || []).forEach((d) => {
    const m = /^Day (\d+)/.exec(d); if (!m) return;
    $$(`#matrix input[data-i="${+m[1] - 1}"]`).forEach((i) => i.classList.add("bad"));
  });
}
function failUi(e, outId) {
  if (e.code === "BAD_INPUT" && e.details) { renderInto(outId, rejectHtml({ error: e.message, details: e.details })); markBadRows(e.details); return; }
  renderInto(outId, "");
  const act = (e.code === "AI_NOT_CONFIGURED" || e.code === "AI_KEY_INVALID") && state.info && state.info.mode === "local" ? { label: "Open API Keys", run: openKeys } : null;
  notice(e.message, act);
}
async function runForecast() {
  if (state.busy) return;
  state.busy = true; updateRunAvailability(); notice("");
  show("forecast"); renderInto("forecastOut", loadingHtml("Analysing your 7 days…"));
  $$("#matrix input").forEach((i) => i.classList.remove("bad"));
  try {
    const r = await api("api/forecast", { method: "POST", body: JSON.stringify(payload()) });
    state.forecast = r; state.scheduleSource = "forecast";
    renderInto("forecastOut", forecastHtml(r), r); setRuns(r.limits.runs_left);
  } catch (e) { failUi(e, "forecastOut"); }
  finally { state.busy = false; await loadInfo(); }
}
$("#runBtn").addEventListener("click", runForecast);

function updateWhatifSummary() {
  const filled = state.rows.filter((r) => r.sleep !== "").length;
  $("#whatifSummary").textContent = filled ? `${filled} days, ${state.context === CUSTOM ? state.custom || "custom context" : state.context}` : "the table is empty, fill it in first";
}
$("#adjSleep").addEventListener("input", (e) => { $("#vSleep").textContent = "+" + n1(+e.target.value) + " h"; });
$("#adjScreen").addEventListener("input", (e) => { $("#vScreen").textContent = "−" + n1(+e.target.value) + " h"; });
$("#simBtn").addEventListener("click", async () => {
  if (state.busy) return;
  state.busy = true; updateRunAvailability(); notice("");
  renderInto("whatifOut", loadingHtml("Simulating your plan…"));
  const adj = {
    extra_sleep_hours: +$("#adjSleep").value, screen_reduction_hours: +$("#adjScreen").value,
    caffeine_cutoff_hours_before_bed: $("#adjCutoff").value, caffeine_cap_mg: $("#adjCap").value, lock_schedule: $("#adjLock").checked,
  };
  try {
    const r = await api("api/simulate-recovery", { method: "POST", body: JSON.stringify({ ...payload(), adjustments: adj }) });
    state.sim = r; state.scheduleSource = "sim";
    renderInto("whatifOut", simHtml(r), r.simulated); setRuns(r.limits.runs_left);
  } catch (e) { failUi(e, "whatifOut"); }
  finally { state.busy = false; await loadInfo(); }
});

function renderSchedulePage() {
  const useSim = state.scheduleSource === "sim" && state.sim;
  const src = useSim ? { r: state.sim.simulated, c: state.sim.coach, label: "What-if plan" }
    : state.forecast ? { r: state.forecast, c: state.forecast.coach, label: "Current habits" } : null;
  if (!src) { renderInto("scheduleOut", emptyHtml("Daily Recovery Schedule", "Run a 7-day forecast and your hour-by-hour plan appears here.", "forecast")); return; }
  renderInto("scheduleOut", scheduleHtml(src, !!(state.forecast && state.sim), useSim ? "sim" : "forecast"));
  $$("[data-src]", $("#scheduleOut")).forEach((b) => (b.onclick = () => { state.scheduleSource = b.dataset.src; renderSchedulePage(); }));
}

/* ---------------- history drawer ---------------- */
function openDrawer(open) {
  $("#drawer").classList.toggle("open", open); $("#drawer").setAttribute("aria-hidden", String(!open)); $("#scrim").hidden = !open;
  if (open) { openRail(false); loadHistory(); }
}
async function loadHistory() {
  const box = $("#historyList");
  try {
    const { items } = await api("api/history");
    box.innerHTML = items.length ? items.map((h) => `<button class="hitem" type="button" data-h="${h.id}"><b>${h.score ?? "?"}</b> ${esc(h.band || "")}<small>${h.kind === "simulation" ? "What-if: " : ""}${esc(h.title)} · ${new Date(h.created * 1000).toLocaleString()}</small></button>`).join("") : `<p class="hint">No saved forecasts yet. Run a forecast and it will appear here.</p>`;
  } catch (e) { box.innerHTML = `<p class="hint">${esc(e.message)}</p>`; }
}
$("#historyBtn").onclick = () => openDrawer(true);
$("#drawerClose").onclick = $("#scrim").onclick = () => openDrawer(false);
$("#historyList").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-h]"); if (!b) return;
  try {
    const row = await api("api/history/" + b.dataset.h); const r = row.result;
    openDrawer(false);
    if (r.kind === "simulation") { state.sim = r; state.scheduleSource = "sim"; show("whatif"); renderInto("whatifOut", `<div class="banner">Saved what-if from your history.</div>` + simHtml(r), r.simulated); }
    else { state.forecast = r; state.scheduleSource = "forecast"; show("forecast"); renderInto("forecastOut", `<div class="banner">Saved forecast from your history.</div>` + forecastHtml(r), r); }
  } catch (err) { notice(err.message); }
});
$("#historyClear").onclick = async () => { try { await api("api/history", { method: "DELETE" }); loadHistory(); } catch (e) { notice(e.message); } };

/* ---------------- API keys ---------------- */
async function openKeys() {
  openRail(false); $("#keyMsg").textContent = ""; $("#keyInput").value = "";
  await refreshKeyStatus();
  const d = $("#keysModal"); if (d.showModal) d.showModal(); else d.setAttribute("open", "");
}
async function refreshKeyStatus() {
  try {
    const { groq } = await api("api/keys");
    $("#keyStatus").textContent = groq.configured ? `Key in use: ${groq.masked} (from ${groq.source === "ui" ? "this screen" : ".env"})` : "No usable key yet.";
  } catch (e) { $("#keyStatus").textContent = e.message; }
}
$("#keysBtn").onclick = openKeys;
$("#keyClose").onclick = (e) => { e.preventDefault(); $("#keysModal").close(); };
$("#keySave").onclick = async () => {
  try { await api("api/keys", { method: "POST", body: JSON.stringify({ groq_api_key: $("#keyInput").value.trim() }) }); $("#keyInput").value = ""; $("#keyMsg").textContent = "Saved."; await refreshKeyStatus(); await loadInfo(); }
  catch (e) { $("#keyMsg").textContent = e.message; }
};
$("#keyRemove").onclick = async () => {
  try { await api("api/keys/groq", { method: "DELETE" }); $("#keyMsg").textContent = "Removed."; await refreshKeyStatus(); await loadInfo(); }
  catch (e) { $("#keyMsg").textContent = e.message; }
};

/* ---------------- boot ---------------- */
async function boot() {
  initTicket();
  state.rows = blankRows(); drawPills(); drawMatrix();
  renderInto("forecastOut", emptyHtml("Your forecast appears here", "Pick a sample log or enter your own seven days, then press Forecast Burnout & Build Recovery Plan."));
  await Promise.all([loadInfo(), loadSamples()]);
  if (state.samples.length) { const first = state.samples[0].id; const s = await api("api/samples/" + first).catch(() => null); if (s && s.result) await openSample(first, true); else if (s && s.input) { state.rows = rowsFromParsed(s.input.days); setContext(s.input.context); drawMatrix(); } }
}
boot();

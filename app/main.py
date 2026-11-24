"""FastAPI app: standard LastSem routes plus /api/forecast and /api/simulate-recovery."""
import json
import logging
import re

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import access, ai_groq, chronobiology as chrono, config, db, forecast
from .errors import ApiError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("sleep-burnout")

app = FastAPI(title=config.PROJECT_NAME, version=config.VERSION, docs_url=None, redoc_url=None, openapi_url=None)


@app.on_event("startup")
def _startup() -> None:
    db.conn()
    if config.DEMO_MODE:
        if not config.DEMO_TICKET_SECRET:
            log.warning("DEMO_MODE is on but DEMO_TICKET_SECRET is empty: every ticket will be rejected. Samples still work.")
        db.purge_demo_data()


# ---- errors -------------------------------------------------------------------------
def _json(status: int, code: str, message: str, details=None) -> JSONResponse:
    body = {"error": message, "code": code}
    if details:
        body["details"] = details
    return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store"})


@app.exception_handler(ApiError)
async def _api_error(_: Request, e: ApiError):
    return _json(e.status, e.code, e.message, e.details)


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, e: RequestValidationError):
    return _json(400, "BAD_INPUT", "Some of the information sent was missing or in the wrong format.")


@app.exception_handler(StarletteHTTPException)
async def _http_error(_: Request, e: StarletteHTTPException):
    if e.status_code == 404:
        return _json(404, "NOT_FOUND", "That page or item was not found.")
    if e.status_code == 405:
        return _json(405, "BAD_INPUT", "That request method is not allowed here.")
    return _json(e.status_code, "BAD_INPUT", "The request could not be handled.")


@app.exception_handler(Exception)
async def _unexpected(_: Request, e: Exception):
    log.exception("unexpected error: %s", ai_groq._redact(str(e), ai_groq.resolve_key()[0]))
    return _json(500, "AI_FAILED", "Something went wrong on the server. Please try again.")


def max_body_bytes() -> int:
    mb = config.DEMO_MAX_UPLOAD_MB if config.DEMO_MODE else config.MAX_UPLOAD_MB
    return max(1, mb) * 1024 * 1024


async def read_json(request: Request) -> dict:
    raw = await request.body()
    if len(raw) > max_body_bytes():
        raise ApiError(413, "TOO_LARGE", f"That request is too large. Keep it under {max_body_bytes() // (1024 * 1024)} MB.")
    try:
        data = json.loads(raw or b"{}")
    except (ValueError, UnicodeDecodeError):
        raise ApiError(400, "BAD_INPUT", "The request was not valid JSON.")
    if not isinstance(data, dict):
        raise ApiError(400, "BAD_INPUT", "The request body must be a JSON object.")
    return data


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    return resp


# ---- standard routes ---------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok"}


def _caller(request: Request) -> tuple[dict | None, str, str]:
    """(ticket payload or None, history owner, quota bucket). Never raises."""
    payload = None
    if config.DEMO_MODE:
        payload, _ = access.ticket_from_request(request)
    owner, bucket = access.owner_and_bucket(payload)
    return payload, owner, bucket


def _runs_left(request: Request, bucket: str) -> int:
    left = db.slots_left(bucket)
    ip = _ip_bucket(request)
    return min(left, db.slots_left(ip)) if ip else left


def _ip_bucket(request: Request) -> str | None:
    """Demo only: a second hourly bucket per client IP, so one visitor cannot dodge the limit with many tickets.
    The IP is the socket address, or the first X-Forwarded-For entry only when TRUST_PROXY=true."""
    return f"ip:{access.client_ip(request)}" if config.DEMO_MODE else None


@app.get("/api/info")
async def info(request: Request):
    payload, _, bucket = _caller(request)
    demo = None
    if config.DEMO_MODE:
        db.purge_demo_data()
        used = db.ticket_used(payload["tid"]) if payload else 0
        demo = {
            "ticket_valid": payload is not None,
            "runs_left": max(0, int(payload.get("runs", 0)) - used) if payload else 0,
            "daily_cap_reached": db.daily_used() >= config.DEMO_DAILY_CAP,
        }
    return {
        "name": config.PROJECT_NAME, "slug": config.PROJECT_SLUG, "number": config.PROJECT_NUMBER,
        "version": config.VERSION, "mode": "demo" if config.DEMO_MODE else "local",
        "ai": {"provider": "groq", "ready": ai_groq.ai_ready(), "model": config.GROQ_MODEL},
        "limits": {"max_upload_mb": config.DEMO_MAX_UPLOAD_MB if config.DEMO_MODE else config.MAX_UPLOAD_MB,
                   "hourly_runs": config.HOURLY_RUNS,
                   "runs_left": _runs_left(request, bucket) if (payload or not config.DEMO_MODE) else config.HOURLY_RUNS},
        "demo": demo,
        "disclaimer": config.DISCLAIMER,
        "presets": chrono.PRESETS,
    }


SAMPLE_ID = re.compile(r"^[a-z0-9][a-z0-9\-]{0,60}$")


def _load_sample_meta(path) -> dict:
    text = path.read_text(encoding="utf-8")
    meta = {"title": path.stem.replace("-", " ").title(), "order": 99}
    for line in text.splitlines():
        m = re.match(r"^#\s*(title|order)\s*:\s*(.+)$", line.strip(), re.I)
        if m:
            meta[m.group(1).lower()] = int(m.group(2)) if m.group(1).lower() == "order" else m.group(2).strip()
    meta["input_text"] = text
    meta["id"] = path.stem
    return meta


def _samples() -> list[dict]:
    items = [_load_sample_meta(p) for p in sorted(config.SAMPLES_DIR.glob("*.csv"))]
    items.sort(key=lambda m: (m["order"], m["id"]))
    return items


@app.get("/api/samples")
async def samples():
    return {"samples": [
        {"id": m["id"], "title": m["title"], "input_text": m["input_text"],
         "has_saved_result": (config.RESULTS_DIR / f"{m['id']}.json").is_file()}
        for m in _samples()]}


@app.get("/api/samples/{sample_id}")
async def sample(sample_id: str):
    path = config.SAMPLES_DIR / f"{sample_id}.csv"
    if not SAMPLE_ID.match(sample_id) or not path.is_file():
        raise ApiError(404, "NOT_FOUND", "That sample does not exist.")
    meta = _load_sample_meta(path)
    result_path = config.RESULTS_DIR / f"{sample_id}.json"
    result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else None
    try:
        parsed = chrono.parse_log_text(meta["input_text"])
        structured = {"context": parsed["context"], "days": parsed["days"]}
    except chrono.BadInput:
        structured = None
    return {"id": sample_id, "title": meta["title"], "input_text": meta["input_text"], "input": structured, "result": result}



@app.post("/api/parse-log")
async def parse_log(request: Request):
    body = await read_json(request)
    text = body.get("log_text")
    if not isinstance(text, str) or not text.strip():
        raise ApiError(400, "BAD_INPUT", "Paste your log first: one line per day.")
    try:
        parsed = chrono.parse_log_text(text)
    except chrono.BadInput as e:
        raise ApiError(400, "BAD_INPUT", e.problems[0])
    if len(parsed["days"]) > 14:
        raise ApiError(400, "BAD_INPUT", "That log has more than 14 days. Paste the most recent 14 at most.")
    return parsed


# ---- API keys (download version only) ---------------------------------------------------------
def _keys_guard(request: Request) -> None:
    if config.DEMO_MODE:
        raise ApiError(404, "NOT_FOUND", "That page or item was not found.")
    access.require_local_key_request(request)


class KeyBody(BaseModel):
    groq_api_key: str


def _key_status() -> dict:
    key, source = ai_groq.resolve_key()
    return {"groq": {"configured": key is not None, "source": source, "masked": ai_groq.mask(key) if key else ""}}


@app.get("/api/keys")
async def keys_get(request: Request):
    _keys_guard(request)
    return _key_status()


@app.post("/api/keys")
async def keys_post(request: Request):
    _keys_guard(request)
    body = await read_json(request)
    key = body.get("groq_api_key")
    if not isinstance(key, str) or not ai_groq.key_usable(key.strip()):
        raise ApiError(400, "BAD_INPUT", "That does not look like a Groq key. It starts with gsk_ and has no spaces. "
                                         "Get a free one at console.groq.com/keys.")
    db.set_setting("groq_api_key", key.strip())
    return {"saved": ["groq"]}


@app.delete("/api/keys/groq")
async def keys_delete(request: Request):
    _keys_guard(request)
    db.del_setting("groq_api_key")
    return {"removed": "groq"}


# ---- live runs ----------------------------------------------------------------------------------
async def _live_run(request: Request, kind: str) -> dict:
    """Shared flow: ticket -> validate -> key -> hourly slot -> engine + Groq -> record. Failures refund the slot."""
    payload = access.demo_gate(request) if config.DEMO_MODE else None
    owner, bucket = access.owner_and_bucket(payload)
    body = await read_json(request)

    try:
        inp = chrono.validate(body)
        adjustments = None
        if kind == "simulation":
            adjustments = body.get("adjustments")
            if adjustments is None:
                raise chrono.BadInput(["Send an 'adjustments' object describing what to change."])
            chrono.apply_adjustments(inp, adjustments)  # validate before taking a slot
    except chrono.BadInput as e:
        first = e.problems[0]
        extra = f" (and {len(e.problems) - 1} more problem{'s' if len(e.problems) > 2 else ''})" if len(e.problems) > 1 else ""
        raise ApiError(400, "BAD_INPUT", first + extra, e.problems)

    if not ai_groq.ai_ready():
        raise ApiError(503, "AI_NOT_CONFIGURED",
                       "No Groq key is set up yet. Open API Keys and paste your free key from console.groq.com/keys.")

    slot, wait = db.reserve_slot(bucket)
    ip_slot = None
    if slot is not None and _ip_bucket(request):
        ip_slot, wait = db.reserve_slot(_ip_bucket(request))
        if ip_slot is None:
            db.refund_slot(slot)
            slot = None
    if slot is None:
        raise ApiError(429, "RATE_LIMITED",
                       f"You have used all {config.HOURLY_RUNS} runs for this hour. A run frees up in about {max(1, wait // 60)} minute(s).")
    try:
        result = await (forecast.run_forecast(inp) if kind == "forecast" else forecast.run_simulation(inp, adjustments))
    except BaseException:
        db.refund_slot(slot)  # failed runs never use up quota
        db.refund_slot(ip_slot)
        raise

    if config.DEMO_MODE:
        db.record_demo_run(payload["tid"])
    title = f"{inp['context']}: {result['burnout']['score'] if kind == 'forecast' else result['simulated']['burnout']['score']} risk"
    result["history_id"] = db.add_history(owner, kind, title, result)
    result["limits"] = {"hourly_runs": config.HOURLY_RUNS, "runs_left": _runs_left(request, bucket)}
    return result


@app.post("/api/forecast")
async def api_forecast(request: Request):
    return JSONResponse(await _live_run(request, "forecast"), headers={"Cache-Control": "no-store"})


@app.post("/api/simulate-recovery")
async def api_simulate(request: Request):
    return JSONResponse(await _live_run(request, "simulation"), headers={"Cache-Control": "no-store"})


# ---- history ---------------------------------------------------------------------------------------
@app.get("/api/history")
async def history_list(request: Request):
    payload, owner, _ = _caller(request)
    if config.DEMO_MODE and not payload:
        return {"items": []}
    return {"items": db.list_history(owner)}


@app.get("/api/history/{hid}")
async def history_get(hid: int, request: Request):
    payload, owner, _ = _caller(request)
    row = None if (config.DEMO_MODE and not payload) else db.get_history(owner, hid)
    if not row:
        raise ApiError(404, "NOT_FOUND", "That saved forecast was not found.")
    return row


@app.delete("/api/history")
async def history_clear(request: Request):
    payload, owner, _ = _caller(request)
    if config.DEMO_MODE and not payload:
        return {"removed": 0}
    return {"removed": db.clear_history(owner)}


# ---- frontend ------------------------------------------------------------------------------------------
@app.get("/")
async def index():
    return FileResponse(config.STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")

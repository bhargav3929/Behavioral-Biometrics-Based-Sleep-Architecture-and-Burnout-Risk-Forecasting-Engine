"""The only place that talks to Groq: key rules, retries, model fallback, JSON validation."""
import asyncio
import json
import logging
import random
import re

import httpx
from pydantic import BaseModel, ValidationError, field_validator

from . import config, db
from .errors import ApiError

log = logging.getLogger("sleep-burnout.ai")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
TIMEOUT_SECONDS = 45
RETRY_STATUSES = {429, 500, 502, 503, 504}
CATEGORIES = {"sunlight", "focus", "caffeine", "movement", "meals", "screens", "winddown", "sleep", "habit"}
CLOCK_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


# ---- key handling ---------------------------------------------------------------
def key_usable(key: str | None) -> bool:
    if not key:
        return False
    k = key.strip()
    if not k or k != key or k == config.PLACEHOLDER_KEY or any(ch.isspace() for ch in key):
        return False
    return k.startswith("gsk_") and len(k) > 8


def resolve_key() -> tuple[str | None, str]:
    """Return (key, source). Download: saved key first, then .env. Demo: server env only."""
    if not config.DEMO_MODE:
        saved = db.get_setting("groq_api_key")
        if key_usable(saved):
            return saved, "ui"
    if key_usable(config.GROQ_API_KEY):
        return config.GROQ_API_KEY, "env"
    return None, "none"


def mask(key: str) -> str:
    return f"gsk_...{key[-4:]}" if key else ""


def ai_ready() -> bool:
    return resolve_key()[0] is not None


def _redact(text: str, key: str | None) -> str:
    text = re.sub(r"gsk_[A-Za-z0-9]{8,}", "gsk_***", text or "")
    if key:
        text = text.replace(key, "***")
    return text[:400]


# ---- output schema ---------------------------------------------------------------
class Bottleneck(BaseModel):
    title: str
    detail: str


class Block(BaseModel):
    time: str
    title: str
    detail: str
    category: str = "habit"

    @field_validator("time")
    @classmethod
    def _time(cls, v: str) -> str:
        v = str(v).strip()
        m = CLOCK_RE.match(v)
        if not m:
            raise ValueError("time must be HH:MM")
        return f"{int(m.group(1)):02d}:{m.group(2)}"

    @field_validator("category", mode="before")
    @classmethod
    def _cat(cls, v) -> str:
        v = str(v or "habit").strip().lower()
        return v if v in CATEGORIES else "habit"


class CoachOut(BaseModel):
    headline: str
    outlook: str
    bottlenecks: list[Bottleneck]
    schedule: list[Block]
    priorities: list[str]
    comparison: str = ""

    @field_validator("bottlenecks", mode="after")
    @classmethod
    def _b(cls, v):
        if not v:
            raise ValueError("need at least one bottleneck")
        return v[:6]

    @field_validator("schedule", mode="after")
    @classmethod
    def _s(cls, v):
        if len(v) < 6:
            raise ValueError("need at least 6 schedule blocks")
        return v[:14]

    @field_validator("priorities", mode="after")
    @classmethod
    def _p(cls, v):
        if not v:
            raise ValueError("need at least one priority")
        return [str(x) for x in v[:5]]


def clean_json_text(text: str) -> str:
    """Strip <think> blocks and markdown fences, then cut to the outermost JSON object."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S | re.I)
    text = re.sub(r"<think>.*$", "", text, flags=re.S | re.I)
    text = re.sub(r"```(?:json|JSON)?", "", text)
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start != -1 and end > start else text.strip()


def parse_coach(text: str) -> CoachOut:
    return CoachOut.model_validate(json.loads(clean_json_text(text)))


# ---- HTTP with retries ---------------------------------------------------------------
class _Retryable(Exception):
    pass


class _ModelFailed(Exception):
    pass


def _wait_from_429(body: str) -> float | None:
    m = re.search(r"try again in\s+(\d+(?:\.\d+)?)\s*s", body or "", re.I)
    if m:
        x = float(m.group(1))
        if x <= 20:
            return x + random.uniform(0.1, 0.6)
    return None


async def _call_model(client: httpx.AsyncClient, key: str, model: str, messages: list[dict]) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.3,
        "max_completion_tokens": 4000,
        "response_format": {"type": "json_object"},
    }
    if model.startswith("openai/gpt-oss"):
        payload["reasoning_effort"] = "low"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    last: Exception | None = None
    for attempt in range(3):
        delay = (2 ** attempt) + random.uniform(0, 0.5)
        try:
            r = await client.post(GROQ_URL, headers=headers, json=payload)
        except (httpx.TimeoutException, httpx.TransportError) as e:
            last = _Retryable(type(e).__name__)
            log.warning("groq %s attempt %d network error: %s", model, attempt + 1, type(e).__name__)
        else:
            if r.status_code == 200:
                try:
                    return r.json()["choices"][0]["message"]["content"] or ""
                except Exception:
                    raise _ModelFailed("unreadable response")
            if r.status_code in (401, 403):
                log.warning("groq rejected the key (%s)", r.status_code)
                raise ApiError(502, "AI_KEY_INVALID",
                               "Your Groq key was rejected. Open API Keys and paste a fresh key from console.groq.com/keys.")
            if r.status_code in RETRY_STATUSES:
                last = _Retryable(str(r.status_code))
                log.warning("groq %s attempt %d status %s: %s", model, attempt + 1, r.status_code, _redact(r.text, key))
                if r.status_code == 429:
                    delay = _wait_from_429(r.text) or delay
            else:
                log.warning("groq %s status %s: %s", model, r.status_code, _redact(r.text, key))
                raise _ModelFailed(str(r.status_code))
        if attempt < 2:
            await asyncio.sleep(delay)
    raise last or _Retryable("unknown")


async def coach_complete(system: str, user: str) -> tuple[CoachOut, str]:
    """Call the primary model (then the fallback). Returns (validated output, model that answered)."""
    key, _ = resolve_key()
    if not key:
        raise ApiError(503, "AI_NOT_CONFIGURED",
                       "No Groq key is set up yet. Open API Keys and paste your free key from console.groq.com/keys.")
    models = [config.GROQ_MODEL]
    if config.GROQ_FALLBACK_MODEL and config.GROQ_FALLBACK_MODEL != config.GROQ_MODEL:
        models.append(config.GROQ_FALLBACK_MODEL)

    busy = False
    async with httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT_SECONDS)) as client:
        for model in models:
            messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
            try:
                for parse_try in range(2):
                    text = await _call_model(client, key, model, messages)
                    try:
                        return parse_coach(text), model
                    except (json.JSONDecodeError, ValidationError, ValueError) as e:
                        log.warning("groq %s invalid output (try %d): %s", model, parse_try + 1, _redact(str(e), key))
                        messages = messages + [
                            {"role": "assistant", "content": text[:1500]},
                            {"role": "user", "content": "That was not valid JSON for the required schema. "
                                                        "Reply again with ONLY the JSON object, no other text."},
                        ]
                raise _ModelFailed("invalid output")
            except _Retryable:
                busy = True
            except _ModelFailed:
                busy = False
    if busy:
        raise ApiError(503, "AI_BUSY", "The AI service is busy right now. Wait a minute and try again.")
    raise ApiError(502, "AI_FAILED", "The AI couldn't process this input.")

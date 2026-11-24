"""Who may do what: key-screen locality checks and the demo ticket (HMAC-SHA256)."""
import base64
import hashlib
import hmac
import json
import time

from fastapi import Request

from . import config, db
from .errors import ApiError

LOCAL_PEERS = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def verify_ticket(ticket: str | None, secret: str, slug: str) -> tuple[dict | None, str | None]:
    """Return (payload, None) if valid, else (None, error_code)."""
    if not ticket:
        return None, "TICKET_REQUIRED"
    if not secret:
        return None, "TICKET_INVALID"
    try:
        body, sig = ticket.split(".")
        payload = json.loads(_b64d(body))
        expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
        if payload.get("v") != 1 or not hmac.compare_digest(expected, _b64d(sig)):
            return None, "TICKET_INVALID"
    except Exception:
        return None, "TICKET_INVALID"
    if payload.get("slug") not in (slug, "*"):
        return None, "TICKET_INVALID"
    try:
        if int(payload.get("exp", 0)) < time.time():
            return None, "TICKET_EXPIRED"
    except (TypeError, ValueError):
        return None, "TICKET_INVALID"
    if not isinstance(payload.get("tid"), str) or not payload["tid"]:
        return None, "TICKET_INVALID"
    return payload, None


TICKET_MESSAGES = {
    "TICKET_REQUIRED": ("Sign in on lastsem.com to try your own input.", 401),
    "TICKET_INVALID": ("This demo ticket is not valid. Go back to lastsem.com and start a new try.", 401),
    "TICKET_EXPIRED": ("This demo ticket has expired. Go back to lastsem.com and start a new try.", 401),
    "TICKET_USED_UP": ("You have used all the live runs on this demo ticket.", 429),
    "DAILY_CAP_REACHED": ("The demo has reached its limit for today. Please try again tomorrow; the sample logs still work.", 429),
}


def _raise(code: str):
    msg, status = TICKET_MESSAGES[code]
    raise ApiError(status, code, msg)


def client_ip(request: Request) -> str:
    """Socket address; the first X-Forwarded-For entry only when TRUST_PROXY=true."""
    peer = request.client.host if request.client else ""
    if config.TRUST_PROXY:
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            return xff.split(",")[0].strip()
    return peer


def require_local_key_request(request: Request) -> None:
    """Key screen only from this machine, never through a proxy."""
    peer = request.client.host if request.client else ""
    if peer not in LOCAL_PEERS or "x-forwarded-for" in request.headers or "forwarded" in request.headers:
        raise ApiError(403, "KEYS_LOCAL_ONLY",
                       "API keys can only be viewed or changed from the computer the app is running on.")


def ticket_from_request(request: Request) -> tuple[dict | None, str | None]:
    return verify_ticket(request.headers.get("x-lastsem-ticket"), config.DEMO_TICKET_SECRET, config.PROJECT_SLUG)


def demo_gate(request: Request) -> dict:
    """Run before a live AI route in demo mode (steps 1-7 of the ticket contract)."""
    payload, code = ticket_from_request(request)
    if code:
        _raise(code)
    db.purge_demo_data()
    if db.ticket_used(payload["tid"]) >= int(payload.get("runs", 0)):
        _raise("TICKET_USED_UP")
    if db.daily_used() >= config.DEMO_DAILY_CAP:
        _raise("DAILY_CAP_REACHED")
    return payload


def owner_and_bucket(payload: dict | None) -> tuple[str, str]:
    """History owner and hourly-quota bucket for this caller."""
    if config.DEMO_MODE:
        tid = payload["tid"] if payload else "anonymous"
        return f"t:{tid}", f"t:{tid}"
    return "local", "local"

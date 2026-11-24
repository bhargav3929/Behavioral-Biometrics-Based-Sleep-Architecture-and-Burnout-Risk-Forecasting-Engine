"""Embedded SQLite (WAL): saved key, hourly run slots, ticket run counts, forecast history."""
import json
import sqlite3
import threading
import time
from datetime import datetime, timezone

from . import config

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (name TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY AUTOINCREMENT, bucket TEXT NOT NULL, ts REAL NOT NULL);
CREATE INDEX IF NOT EXISTS runs_bucket_ts ON runs(bucket, ts);
CREATE TABLE IF NOT EXISTS ticket_runs (tid TEXT PRIMARY KEY, used INTEGER NOT NULL, first_seen REAL NOT NULL);
CREATE TABLE IF NOT EXISTS daily_runs (day TEXT PRIMARY KEY, used INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS history (
  id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL, created REAL NOT NULL,
  kind TEXT NOT NULL, title TEXT NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS history_owner ON history(owner, created);
"""


def conn() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            config.DATA_DIR.mkdir(parents=True, exist_ok=True)
            c = sqlite3.connect(str(config.DB_PATH), check_same_thread=False, isolation_level=None)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.executescript(SCHEMA)
            _conn = c
        return _conn


# ---- saved settings (API key) -------------------------------------------------
def get_setting(name: str) -> str | None:
    with _lock:
        row = conn().execute("SELECT value FROM settings WHERE name=?", (name,)).fetchone()
        return row["value"] if row else None


def set_setting(name: str, value: str) -> None:
    with _lock:
        conn().execute(
            "INSERT INTO settings(name,value) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",
            (name, value),
        )


def del_setting(name: str) -> None:
    with _lock:
        conn().execute("DELETE FROM settings WHERE name=?", (name,))


# ---- hourly sliding-window run slots -----------------------------------------
def _prune_slots(now: float) -> None:
    conn().execute("DELETE FROM runs WHERE ts < ?", (now - config.HOURLY_WINDOW_SECONDS,))


def slots_left(bucket: str, limit: int = config.HOURLY_RUNS) -> int:
    with _lock:
        now = time.time()
        _prune_slots(now)
        used = conn().execute("SELECT COUNT(*) c FROM runs WHERE bucket=?", (bucket,)).fetchone()["c"]
        return max(0, limit - used)


def reserve_slot(bucket: str, limit: int = config.HOURLY_RUNS) -> tuple[int | None, int]:
    """Take one slot. Returns (slot_id or None, seconds until a slot frees up)."""
    with _lock:
        now = time.time()
        _prune_slots(now)
        rows = conn().execute("SELECT ts FROM runs WHERE bucket=? ORDER BY ts", (bucket,)).fetchall()
        if len(rows) >= limit:
            wait = int(max(1, rows[0]["ts"] + config.HOURLY_WINDOW_SECONDS - now))
            return None, wait
        cur = conn().execute("INSERT INTO runs(bucket, ts) VALUES(?,?)", (bucket, now))
        return cur.lastrowid, 0


def refund_slot(slot_id: int | None) -> None:
    if slot_id is None:
        return
    with _lock:
        conn().execute("DELETE FROM runs WHERE id=?", (slot_id,))


# ---- demo ticket counters -----------------------------------------------------
def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def ticket_used(tid: str) -> int:
    with _lock:
        row = conn().execute("SELECT used FROM ticket_runs WHERE tid=?", (tid,)).fetchone()
        return int(row["used"]) if row else 0


def daily_used() -> int:
    with _lock:
        row = conn().execute("SELECT used FROM daily_runs WHERE day=?", (_today(),)).fetchone()
        return int(row["used"]) if row else 0


def record_demo_run(tid: str) -> None:
    """Count one successful live run for this ticket and for today."""
    with _lock:
        c = conn()
        c.execute(
            "INSERT INTO ticket_runs(tid, used, first_seen) VALUES(?,1,?) "
            "ON CONFLICT(tid) DO UPDATE SET used = used + 1",
            (tid, time.time()),
        )
        c.execute(
            "INSERT INTO daily_runs(day, used) VALUES(?,1) ON CONFLICT(day) DO UPDATE SET used = used + 1",
            (_today(),),
        )


def purge_demo_data() -> None:
    """Demo mode: drop ticket rows, and that ticket's history, once older than 24 h."""
    with _lock:
        cutoff = time.time() - 24 * 3600
        c = conn()
        c.execute("DELETE FROM history WHERE owner != 'local' AND created < ?", (cutoff,))
        c.execute("DELETE FROM ticket_runs WHERE first_seen < ?", (cutoff,))
        old_day = datetime.fromtimestamp(time.time() - 3 * 86400, timezone.utc).strftime("%Y-%m-%d")
        c.execute("DELETE FROM daily_runs WHERE day < ?", (old_day,))


# ---- history ------------------------------------------------------------------
def add_history(owner: str, kind: str, title: str, payload: dict) -> int:
    with _lock:
        cur = conn().execute(
            "INSERT INTO history(owner, created, kind, title, payload) VALUES(?,?,?,?,?)",
            (owner, time.time(), kind, title, json.dumps(payload)),
        )
        # keep the table small: newest 60 per owner
        conn().execute(
            "DELETE FROM history WHERE owner=? AND id NOT IN "
            "(SELECT id FROM history WHERE owner=? ORDER BY id DESC LIMIT 60)",
            (owner, owner),
        )
        return cur.lastrowid


def list_history(owner: str, limit: int = 30) -> list[dict]:
    with _lock:
        rows = conn().execute(
            "SELECT id, created, kind, title, payload FROM history WHERE owner=? ORDER BY id DESC LIMIT ?",
            (owner, limit),
        ).fetchall()
    out = []
    for r in rows:
        p = json.loads(r["payload"])
        burnout = p.get("burnout") or p.get("simulated", {}).get("burnout") or {}
        out.append({
            "id": r["id"], "created": r["created"], "kind": r["kind"], "title": r["title"],
            "score": burnout.get("score"), "band": burnout.get("label"),
        })
    return out


def get_history(owner: str, hid: int) -> dict | None:
    with _lock:
        r = conn().execute(
            "SELECT id, created, kind, title, payload FROM history WHERE owner=? AND id=?", (owner, hid)
        ).fetchone()
    if not r:
        return None
    return {"id": r["id"], "created": r["created"], "kind": r["kind"], "title": r["title"],
            "result": json.loads(r["payload"])}


def clear_history(owner: str) -> int:
    with _lock:
        cur = conn().execute("DELETE FROM history WHERE owner=?", (owner,))
        return cur.rowcount

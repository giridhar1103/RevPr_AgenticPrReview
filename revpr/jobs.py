"""SQLite-backed job queue with progress events (ADR 0012)."""

from __future__ import annotations

import json
import secrets
import time

from . import db

KINDS = ("pr_review", "repo_review", "ask")


def create(kind: str, payload: dict, cache_key: str | None, client_ip: str | None) -> str:
    job_id = secrets.token_urlsafe(9)
    db.get().execute(
        "INSERT INTO jobs (id, kind, cache_key, input, status, client_ip, created_at) "
        "VALUES (?, ?, ?, ?, 'queued', ?, ?)",
        (job_id, kind, cache_key, json.dumps(payload), client_ip, time.time()))
    event(job_id, "queued", {})
    return job_id


def find_cached(cache_key: str, max_age_s: float = 14 * 86400) -> str | None:
    row = db.get().execute(
        "SELECT id FROM jobs WHERE cache_key = ? AND status IN ('done', 'running', 'queued') "
        "AND created_at > ? ORDER BY created_at DESC LIMIT 1",
        (cache_key, time.time() - max_age_s)).fetchone()
    return row["id"] if row else None


def claim() -> dict | None:
    conn = db.get()
    with db.transaction(conn):
        row = conn.execute("SELECT * FROM jobs WHERE status = 'queued' ORDER BY created_at "
                           "LIMIT 1").fetchone()
        if row is None:
            return None
        conn.execute("UPDATE jobs SET status = 'running', started_at = ? WHERE id = ?",
                     (time.time(), row["id"]))
    return dict(row)


def finish(job_id: str, result: dict) -> None:
    db.get().execute("UPDATE jobs SET status = 'done', result = ?, finished_at = ? WHERE id = ?",
                     (json.dumps(result, default=str), time.time(), job_id))
    event(job_id, "done", {})


def fail(job_id: str, message: str) -> None:
    db.get().execute("UPDATE jobs SET status = 'failed', error = ?, finished_at = ? WHERE id = ?",
                     (message[:500], time.time(), job_id))
    event(job_id, "failed", {"error": message[:500]})


def event(job_id: str, type_: str, data: dict) -> None:
    db.get().execute("INSERT INTO events (job_id, at, type, data) VALUES (?, ?, ?, ?)",
                     (job_id, time.time(), type_, json.dumps(data, default=str)[:4000]))


def events_after(job_id: str, after: int) -> list[dict]:
    rows = db.get().execute("SELECT id, at, type, data FROM events WHERE job_id = ? AND id > ? "
                            "ORDER BY id", (job_id, after)).fetchall()
    return [{"id": r["id"], "at": r["at"], "type": r["type"], "data": json.loads(r["data"])}
            for r in rows]


def get(job_id: str) -> dict | None:
    row = db.get().execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        return None
    out = dict(row)
    out["input"] = json.loads(out["input"])
    out["result"] = json.loads(out["result"]) if out["result"] else None
    return out


def queue_position(job_id: str) -> int:
    row = db.get().execute(
        "SELECT COUNT(*) AS n FROM jobs WHERE status = 'queued' AND created_at < "
        "(SELECT created_at FROM jobs WHERE id = ?)", (job_id,)).fetchone()
    return int(row["n"])


def recent_count(client_ip: str, kinds: tuple[str, ...], window_s: float) -> int:
    q = ",".join("?" * len(kinds))
    row = db.get().execute(
        f"SELECT COUNT(*) AS n FROM jobs WHERE client_ip = ? AND kind IN ({q}) AND created_at > ?",
        (client_ip, *kinds, time.time() - window_s)).fetchone()
    return int(row["n"])


def global_count(window_s: float) -> int:
    row = db.get().execute("SELECT COUNT(*) AS n FROM jobs WHERE created_at > ? AND "
                           "cache_key IS NOT NULL", (time.time() - window_s,)).fetchone()
    return int(row["n"])


def requeue_stale(max_running_s: float = 1800) -> None:
    """Jobs left 'running' by a crashed worker are failed so clients stop waiting."""
    conn = db.get()
    for r in conn.execute("SELECT id FROM jobs WHERE status = 'running' AND started_at < ?",
                          (time.time() - max_running_s,)).fetchall():
        fail(r["id"], "worker restarted while this job was running; please retry")

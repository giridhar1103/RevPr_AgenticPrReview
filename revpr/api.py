"""Public HTTP API. Heavy work happens in the worker; this process only validates, rate limits,
deduplicates through the cache and streams progress."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from . import db, jobs
from .config import settings
from .github import GitHub, GitHubError, parse_pr_url, parse_repo_url
from .review.pr_review import PIPELINE_VERSION as PR_VERSION
from .review.repo_review import PIPELINE_VERSION as REPO_VERSION

REVIEWS_PER_IP_HOUR = 6
ASKS_PER_IP_HOUR = 20
NEW_JOBS_PER_DAY = 150

app = FastAPI(title="RevPr", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://giriworks.com", "https://www.giriworks.com", "http://localhost:5173"],
    allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

_gh: GitHub | None = None


def gh() -> GitHub:
    global _gh
    if _gh is None:
        _gh = GitHub()
    return _gh


@app.on_event("startup")
def _startup() -> None:
    db.init()


def _ip(request: Request) -> str:
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "?")


def _limit(ip: str, kinds: tuple[str, ...], per_hour: int) -> None:
    if jobs.recent_count(ip, kinds, 3600) >= per_hour:
        raise HTTPException(429, "Hourly limit reached for your address. Try again later, or "
                                 "browse the example reviews.")
    if jobs.global_count(86400) >= NEW_JOBS_PER_DAY:
        raise HTTPException(429, "The daily budget for new reviews is used up. Cached and "
                                 "example reviews still work.")


class UrlIn(BaseModel):
    url: str = Field(max_length=300)


class AskIn(BaseModel):
    snapshot_id: int
    question: str = Field(min_length=4, max_length=500)


def _job_view(job_id: str) -> dict:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "unknown job")
    view = {"id": job["id"], "kind": job["kind"], "status": job["status"],
            "input": job["input"], "error": job["error"], "created_at": job["created_at"],
            "finished_at": job["finished_at"]}
    if job["status"] == "queued":
        view["position"] = jobs.queue_position(job_id)
    if job["status"] == "done":
        view["result"] = job["result"]
    return view


@app.get("/health")
def health() -> dict:
    row = db.get().execute("SELECT COUNT(*) AS n FROM jobs WHERE status = 'queued'").fetchone()
    return {"ok": True, "queued": row["n"]}


@app.post("/review/pr")
def review_pr(body: UrlIn, request: Request) -> dict:
    try:
        repo, number = parse_pr_url(body.url)
        pr = gh().client.get(f"/repos/{repo}/pulls/{number}")
    except GitHubError as e:
        raise HTTPException(e.status, str(e)) from e
    if pr.status_code == 404:
        raise HTTPException(404, "PR not found, or the repository is private.")
    if pr.status_code >= 400:
        raise HTTPException(502, "GitHub did not answer; try again shortly.")
    head = pr.json()["head"]["sha"]
    key = f"pr:{repo}#{number}@{head}:{PR_VERSION}"
    cached = jobs.find_cached(key)
    if cached:
        return {"job_id": cached, "cached": True}
    ip = _ip(request)
    _limit(ip, ("pr_review", "repo_review"), REVIEWS_PER_IP_HOUR)
    url = f"https://github.com/{repo}/pull/{number}"
    return {"job_id": jobs.create("pr_review", {"url": url}, key, ip), "cached": False}


@app.post("/review/repo")
def review_repo(body: UrlIn, request: Request) -> dict:
    try:
        repo = parse_repo_url(body.url)
        info = gh().repo(repo)
    except GitHubError as e:
        raise HTTPException(e.status, str(e)) from e
    key = f"repo:{repo}@{info.head_sha}:{REPO_VERSION}"
    cached = jobs.find_cached(key)
    if cached:
        return {"job_id": cached, "cached": True}
    ip = _ip(request)
    _limit(ip, ("pr_review", "repo_review"), REVIEWS_PER_IP_HOUR)
    return {"job_id": jobs.create("repo_review", {"url": f"https://github.com/{repo}"}, key, ip),
            "cached": False}


@app.post("/ask")
def ask(body: AskIn, request: Request) -> dict:
    row = db.get().execute("SELECT status FROM snapshots WHERE id = ?",
                           (body.snapshot_id,)).fetchone()
    if row is None or row["status"] != "ready":
        raise HTTPException(409, "That repository index is not available; run a repo review "
                                 "first.")
    q = " ".join(body.question.split())
    key = f"ask:{body.snapshot_id}:{hashlib.sha1(q.lower().encode()).hexdigest()[:16]}"
    cached = jobs.find_cached(key)
    if cached:
        return {"job_id": cached, "cached": True}
    ip = _ip(request)
    _limit(ip, ("ask",), ASKS_PER_IP_HOUR)
    return {"job_id": jobs.create("ask", {"snapshot_id": body.snapshot_id, "question": q}, key,
                                  ip), "cached": False}


@app.get("/jobs/{job_id}")
def job(job_id: str) -> dict:
    return _job_view(job_id)


@app.get("/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request):
    if jobs.get(job_id) is None:
        raise HTTPException(404, "unknown job")

    async def gen():
        after = 0
        started = time.monotonic()
        while time.monotonic() - started < 1200:
            if await request.is_disconnected():
                return
            for ev in jobs.events_after(job_id, after):
                after = ev["id"]
                yield {"event": "progress", "data": json.dumps(ev)}
            status = jobs.get(job_id)["status"]
            if status in ("done", "failed"):
                yield {"event": "end", "data": json.dumps({"status": status})}
                return
            await asyncio.sleep(0.7)

    return EventSourceResponse(gen(), ping=15)


@app.get("/examples")
def examples() -> dict:
    path = settings.data_dir / "examples.json"
    ids = json.loads(path.read_text()) if path.exists() else []
    out = []
    for jid in ids:
        j = jobs.get(jid)
        if j and j["status"] == "done":
            r = j["result"]
            title = (r.get("pr") or {}).get("title") or (r.get("repo") or {}).get("full_name")
            out.append({"id": jid, "kind": j["kind"], "title": title,
                        "url": j["input"].get("url"),
                        "findings": len(r.get("findings", []))})
    return {"examples": out}


@app.get("/evals")
def evals() -> dict:
    path = settings.data_dir / "evals" / "latest.json"
    if not path.exists():
        return {"available": False}
    return {"available": True, **json.loads(path.read_text())}


@app.get("/stats")
def stats() -> dict:
    conn = db.get()
    since = time.time() - 7 * 86400
    rows = conn.execute(
        "SELECT kind, status, COUNT(*) AS n, AVG(finished_at - started_at) AS avg_s FROM jobs "
        "WHERE created_at > ? GROUP BY kind, status", (since,)).fetchall()
    snaps = conn.execute("SELECT COUNT(*) AS n, SUM(dense_done) AS emb FROM snapshots "
                         "WHERE status = 'ready'").fetchone()
    return {"last_7_days": [dict(r) for r in rows], "indexed_snapshots": snaps["n"],
            "embedded_chunks": snaps["emb"] or 0}

"""Public HTTP API. Heavy work happens in the worker; this process only validates, rate limits,
deduplicates through the cache and streams progress."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
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
    # Cloudflare Pages branch previews. The API is public and cookie-free, so this is safe.
    allow_origin_regex=r"https://[a-z0-9-]+(\.[a-z0-9-]+)?\.pages\.dev",
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


# The site proxies API calls through a Cloudflare Pages Function, so those requests reach
# nginx from Cloudflare's network. The function passes the visitor's address in
# X-RevPr-Client-IP, which is trusted only when the connection really comes from Cloudflare.
# Source: https://www.cloudflare.com/ips-v4 and /ips-v6
CLOUDFLARE_NETS = [ipaddress.ip_network(n) for n in (
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22",
    "141.101.64.0/18", "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20",
    "197.234.240.0/22", "198.41.128.0/17", "162.158.0.0/15", "104.16.0.0/13",
    "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22", "2400:cb00::/32", "2606:4700::/32",
    "2803:f800::/32", "2405:b500::/32", "2405:8100::/32", "2a06:98c0::/29", "2c0f:f248::/32",
)]


def _from_cloudflare(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return any(ip in net for net in CLOUDFLARE_NETS)


def _ip(request: Request) -> str:
    peer = request.headers.get("x-real-ip") or (request.client.host if request.client else "?")
    forwarded = request.headers.get("x-revpr-client-ip", "").strip()
    if forwarded and _from_cloudflare(peer):
        try:
            return str(ipaddress.ip_address(forwarded))
        except ValueError:
            pass
    return peer


def _check_size(size_kb: int) -> None:
    if size_kb > settings.max_repo_kb:
        raise HTTPException(413, f"This repository is {size_kb // 1024} MB; the limit is "
                                 f"{settings.max_repo_kb // 1024} MB.")


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


@app.get("/")
def root() -> dict:
    return {"service": "RevPr", "status": "ok",
            "docs": "https://github.com/giridhar1103/RevPr_AgenticPrReview"}


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
    data = pr.json()
    head = data["head"]["sha"]
    _check_size(int((data.get("base") or {}).get("repo", {}).get("size") or 0))
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
    _check_size(info.size_kb)
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

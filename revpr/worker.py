"""Job worker: runs reviews one at a time and embeds in the background when idle."""

from __future__ import annotations

import logging
import signal
import time
import traceback

from . import db, embed, jobs, tracing
from .config import settings
from .github import GitHubError
from .indexer import IndexError_, delete_snapshot
from .llm.client import LLMError
from .review.ask import ask
from .review.pr_review import ReviewError, review_pr
from .review.repo_review import review_repo
from .vectorstore import get_store

log = logging.getLogger("revpr.worker")

IDLE_EMBED_BATCH = 64
MAX_SNAPSHOTS = 40

_stop = False


def _handle(sig, frame):  # noqa: ARG001
    global _stop
    _stop = True


USER_ERRORS = (GitHubError, IndexError_, ReviewError, ValueError)


def run_job(job: dict) -> None:
    job_id = job["id"]
    payload = jobs.get(job_id)["input"]

    def progress(stage: str, data: dict) -> None:
        jobs.event(job_id, stage, data)

    with tracing.job_trace() as steps:
        try:
            if job["kind"] == "pr_review":
                result = review_pr(payload["url"], progress)
            elif job["kind"] == "repo_review":
                result = review_repo(payload["url"], progress)
            elif job["kind"] == "ask":
                result = ask(int(payload["snapshot_id"]), payload["question"], progress)
            else:
                raise ValueError(f"unknown job kind {job['kind']}")
            result["trace"] = _compact(steps)
            jobs.finish(job_id, result)
        except USER_ERRORS as e:
            jobs.fail(job_id, str(e))
        except LLMError as e:
            log.warning("model error on %s: %s", job_id, e)
            jobs.fail(job_id, "The model provider failed on this request. Please try again.")
        except Exception as e:  # noqa: BLE001
            log.error("job %s crashed: %s\n%s", job_id, e, traceback.format_exc())
            jobs.fail(job_id, "Internal error while processing this request.")


def _compact(steps: list[dict]) -> list[dict]:
    out = []
    for s in steps:
        rec = {k: s[k] for k in ("name", "kind", "ms") if k in s}
        if "attrs" in s:
            rec["attrs"] = {k: v for k, v in s["attrs"].items()
                            if k not in ("llm.system",)}
        if "input" in s and s["kind"] in ("RETRIEVER", "TOOL", "RERANKER"):
            rec["input"] = s["input"] if isinstance(s["input"], str) else str(s["input"])
        if "documents" in s:
            rec["documents"] = s["documents"][:12]
        if "error" in s:
            rec["error"] = s["error"]
        out.append(rec)
    return out


def idle_embed() -> bool:
    """Embed pending chunks of the most recently used snapshots. Returns True if work done."""
    conn = db.get()
    row = conn.execute(
        "SELECT id FROM snapshots WHERE status = 'ready' AND dense_done < dense_total "
        "ORDER BY last_used_at DESC LIMIT 1").fetchone()
    if row is None:
        return False
    n = embed.embed_pending(row["id"], IDLE_EMBED_BATCH, get_store(), time_budget_s=20)
    return n > 0


def evict() -> None:
    """Keep the newest MAX_SNAPSHOTS snapshots; drop older ones and their vectors."""
    conn = db.get()
    old = conn.execute("SELECT id FROM snapshots ORDER BY last_used_at DESC LIMIT -1 OFFSET ?",
                       (MAX_SNAPSHOTS,)).fetchall()
    store = get_store()
    for r in old:
        sid = r["id"]
        store.delete_snapshot(sid)
        delete_snapshot(sid)
        log.info("evicted snapshot %s", sid)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)
    db.init()
    tracing.init()
    jobs.requeue_stale(0)
    log.info("worker started, data at %s", settings.data_dir)
    last_evict = 0.0
    while not _stop:
        job = jobs.claim()
        if job is not None:
            log.info("job %s %s", job["id"], job["kind"])
            run_job(job)
            continue
        if time.time() - last_evict > 3600:
            evict()
            last_evict = time.time()
        try:
            if idle_embed():
                continue
        except Exception as e:  # noqa: BLE001
            log.warning("idle embedding failed: %s", e)
        time.sleep(1.0)


if __name__ == "__main__":
    main()

"""Ask the repository: retrieval-augmented question answering with citations."""

from __future__ import annotations

import time
from typing import Callable

from .. import db, gitops, retrieval
from ..llm.client import complete_json, role_label
from ..tracing import span
from ..vectorstore import get_store
from .diffparse import numbered
from .evidence import EvidenceStore
from .prompts import ANSWER_SCHEMA, ANSWER_SYSTEM

Progress = Callable[[str, dict], None]


def _validate_answer(obj: dict) -> dict:
    # A one-word reply has happened once in production; treat it as invalid so it is retried.
    if len((obj.get("answer") or "").split()) < 8:
        raise ValueError("answer is too short to be a real answer")
    return obj


def ask(snapshot_id: int, question: str, progress: Progress | None = None) -> dict:
    emit = progress or (lambda stage, data: None)
    t0 = time.monotonic()
    conn = db.get()
    row = conn.execute("SELECT s.sha, r.full_name FROM snapshots s JOIN repos r ON "
                       "r.id = s.repo_id WHERE s.id = ?", (snapshot_id,)).fetchone()
    if row is None:
        raise ValueError("unknown snapshot")
    rdir = gitops.repo_dir(row["full_name"])
    store = get_store()
    with span("ask", "AGENT", input=question, repo=row["full_name"]) as root:
        with gitops.repo_lock(row["full_name"]):
            gitops.checkout(rdir, row["sha"])
            ev = EvidenceStore(snapshot_id, rdir, row["sha"], store=store)
            emit("retrieve", {})
            hits = retrieval.search(snapshot_id, question, k=8, store=store, use_rerank=True)
            for h in hits:
                ev.seen_chunks.add(h.chunk_id)
                ev.add("search", h.path, h.start_line, h.end_line,
                       numbered(ev.base_text(h.path) or h.text, h.start_line, h.end_line),
                       "; ".join(h.reasons[:2]))
            emit("answer", {"model": role_label("answer"), "evidence": len(ev.items)})
            obj = None
            for rnd in range(2):
                prompt = (f"<pr>\nRepository: {row['full_name']}\nQuestion: {question}\n</pr>\n\n"
                          + "\n".join(e.render() for e in ev.items))
                if rnd == 1:
                    prompt += "\n\nMore evidence was added for your requests. Answer now."
                obj, _ = complete_json("answer", ANSWER_SYSTEM, prompt, ANSWER_SCHEMA,
                                       _validate_answer)
                reqs = obj.get("requests") or []
                if rnd == 1 or not reqs:
                    break
                new = []
                for req in reqs[:3]:
                    new += ev.tool(req.get("tool", ""), req.get("args") or {})
                emit("investigate", {"requests": reqs[:3], "new_evidence": len(new)})
                if not new:
                    break
        cited = [c for c in obj.get("cited", []) if ev.get(c)]
        result = {
            "kind": "ask",
            "repo": row["full_name"],
            "sha": row["sha"],
            "question": question,
            "answer": obj.get("answer", ""),
            "confidence": obj.get("confidence", "low"),
            "cited": cited,
            "evidence": [e.brief() for e in ev.items],
            "evidence_text": {e.id: e.text for e in ev.items},
            "retrieval": [h.brief() for h in hits],
            "model": role_label("answer"),
            "stats": {"total_s": round(time.monotonic() - t0, 1)},
        }
        root.output(result["answer"][:2000])
        return result

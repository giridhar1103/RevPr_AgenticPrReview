"""CPU embedding and reranking with a content-hash cache (ADR 0004).

Models load lazily and only in the worker process. Vectors are L2-normalized float32 in memory
and stored as float16 in SQLite.
"""

from __future__ import annotations

import logging
import threading
import time

import numpy as np

from . import db
from .config import settings

log = logging.getLogger(__name__)

_lock = threading.Lock()
_embedder = None
_reranker = None


def model_slug(name: str | None = None) -> str:
    return (name or settings.embed_model).split("/")[-1].replace(".", "-").lower()


def embedder():
    global _embedder
    with _lock:
        if _embedder is None:
            from fastembed import TextEmbedding
            _embedder = TextEmbedding(settings.embed_model, threads=settings.model_threads)
        return _embedder


def reranker():
    global _reranker
    with _lock:
        if _reranker is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
            _reranker = TextCrossEncoder(settings.rerank_model, threads=settings.model_threads)
        return _reranker


def encode(texts: list[str], batch_size: int = 16) -> np.ndarray:
    if not texts:
        return np.zeros((0, 0), dtype=np.float32)
    vecs = np.asarray(list(embedder().embed(texts, batch_size=batch_size)), dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    return vecs / np.maximum(norms, 1e-9)


def encode_query(text: str) -> np.ndarray:
    return encode([text[: settings.card_chars * 2]])[0]


def rerank(query: str, docs: list[str]) -> list[float]:
    if not docs:
        return []
    return [float(s) for s in reranker().rerank(query, docs)]


def cached_vectors(hashes: list[str]) -> dict[str, np.ndarray]:
    conn = db.get()
    out: dict[str, np.ndarray] = {}
    model = settings.embed_model
    for i in range(0, len(hashes), 500):
        part = hashes[i:i + 500]
        q = ",".join("?" * len(part))
        for row in conn.execute(
                f"SELECT card_hash, vector FROM embeddings WHERE model = ? AND card_hash IN ({q})",
                [model, *part]):
            out[row["card_hash"]] = np.frombuffer(row["vector"], dtype=np.float16).astype(
                np.float32)
    return out


def embed_pending(snapshot_id: int, limit: int, store, time_budget_s: float | None = None,
                  min_priority: float | None = None) -> int:
    """Embed up to `limit` pending chunks of a snapshot in priority order. Returns count done."""
    conn = db.get()
    sql = ("SELECT id, card, card_hash FROM chunks WHERE snapshot_id = ? AND embedded = 0")
    params: list = [snapshot_id]
    if min_priority is not None:
        sql += " AND priority >= ?"
        params.append(min_priority)
    sql += " ORDER BY priority DESC, id LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    if not rows:
        return 0
    t0 = time.monotonic()
    done = 0
    batch = 32
    for i in range(0, len(rows), batch):
        part = rows[i:i + batch]
        cache = cached_vectors([r["card_hash"] for r in part])
        missing = [r for r in part if r["card_hash"] not in cache]
        if missing:
            vecs = encode([r["card"] for r in missing])
            with db.transaction(conn):
                for r, v in zip(missing, vecs, strict=True):
                    conn.execute(
                        "INSERT OR IGNORE INTO embeddings (card_hash, model, vector) "
                        "VALUES (?, ?, ?)",
                        (r["card_hash"], settings.embed_model, v.astype(np.float16).tobytes()))
                    cache[r["card_hash"]] = v
        items = [(r["id"], cache[r["card_hash"]]) for r in part]
        store.upsert(snapshot_id, items)
        with db.transaction(conn):
            conn.executemany("UPDATE chunks SET embedded = 1 WHERE id = ?",
                             [(r["id"],) for r in part])
            conn.execute("UPDATE snapshots SET dense_done = dense_done + ? WHERE id = ?",
                         (len(part), snapshot_id))
        done += len(part)
        if time_budget_s is not None and time.monotonic() - t0 > time_budget_s:
            break
    return done

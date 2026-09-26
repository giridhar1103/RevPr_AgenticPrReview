"""Dense vector storage: Qdrant Cloud first, local exact search as fallback (ADR 0002)."""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from typing import Protocol

import numpy as np

from . import db
from .config import settings
from .embed import model_slug

log = logging.getLogger(__name__)


class VectorStore(Protocol):
    name: str

    def upsert(self, snapshot_id: int, items: list[tuple[int, np.ndarray]]) -> None: ...
    def search(self, snapshot_id: int, vector: np.ndarray, k: int) -> list[tuple[int, float]]: ...
    def delete_snapshot(self, snapshot_id: int) -> None: ...


class LocalStore:
    """Exact cosine search over the float16 vectors cached in SQLite."""

    name = "local"

    def __init__(self, max_cached: int = 4):
        self._cache: OrderedDict[int, tuple[int, np.ndarray, np.ndarray]] = OrderedDict()
        self._max = max_cached
        self._lock = threading.Lock()

    def upsert(self, snapshot_id: int, items: list[tuple[int, np.ndarray]]) -> None:
        with self._lock:
            self._cache.pop(snapshot_id, None)  # vectors already persisted by embed_pending

    def _matrix(self, snapshot_id: int) -> tuple[np.ndarray, np.ndarray]:
        conn = db.get()
        done = conn.execute("SELECT dense_done FROM snapshots WHERE id = ?",
                            (snapshot_id,)).fetchone()
        version = done["dense_done"] if done else 0
        with self._lock:
            hit = self._cache.get(snapshot_id)
            if hit and hit[0] == version:
                self._cache.move_to_end(snapshot_id)
                return hit[1], hit[2]
        rows = conn.execute(
            "SELECT c.id, e.vector FROM chunks c JOIN embeddings e "
            "ON e.card_hash = c.card_hash AND e.model = ? "
            "WHERE c.snapshot_id = ? AND c.embedded = 1", (settings.embed_model, snapshot_id)
        ).fetchall()
        ids = np.array([r["id"] for r in rows], dtype=np.int64)
        mat = (np.stack([np.frombuffer(r["vector"], dtype=np.float16) for r in rows])
               .astype(np.float32) if rows else np.zeros((0, 1), dtype=np.float32))
        with self._lock:
            self._cache[snapshot_id] = (version, ids, mat)
            while len(self._cache) > self._max:
                self._cache.popitem(last=False)
        return ids, mat

    def search(self, snapshot_id: int, vector: np.ndarray, k: int) -> list[tuple[int, float]]:
        ids, mat = self._matrix(snapshot_id)
        if len(ids) == 0:
            return []
        scores = mat @ vector
        k = min(k, len(ids))
        top = np.argpartition(-scores, k - 1)[:k]
        top = top[np.argsort(-scores[top])]
        return [(int(ids[i]), float(scores[i])) for i in top]

    def delete_snapshot(self, snapshot_id: int) -> None:
        with self._lock:
            self._cache.pop(snapshot_id, None)


class QdrantStore:
    """One multitenant collection; tenant key is the snapshot (s<id>)."""

    name = "qdrant"

    def __init__(self, dim: int):
        from qdrant_client import QdrantClient, models
        self.models = models
        self.client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key,
                                   timeout=10)
        self.collection = f"{settings.qdrant_collection}_{model_slug()}"
        self.dim = dim
        self._ensure()

    def _ensure(self) -> None:
        m = self.models
        if self.client.collection_exists(self.collection):
            return
        self.client.create_collection(
            self.collection,
            vectors_config=m.VectorParams(size=self.dim, distance=m.Distance.COSINE,
                                          on_disk=True),
            # Per-tenant HNSW graphs only; no global graph (m=0) since every query filters.
            hnsw_config=m.HnswConfigDiff(m=0, payload_m=16),
            quantization_config=m.ScalarQuantization(
                scalar=m.ScalarQuantizationConfig(type=m.ScalarType.INT8, quantile=0.99,
                                                  always_ram=True)),
            on_disk_payload=True,
        )
        self.client.create_payload_index(
            self.collection, "snap",
            field_schema=m.KeywordIndexParams(type=m.KeywordIndexType.KEYWORD, is_tenant=True))

    def upsert(self, snapshot_id: int, items: list[tuple[int, np.ndarray]]) -> None:
        m = self.models
        points = [m.PointStruct(id=cid, vector=v.tolist(), payload={"snap": f"s{snapshot_id}"})
                  for cid, v in items]
        self.client.upsert(self.collection, points=points, wait=False)

    def search(self, snapshot_id: int, vector: np.ndarray, k: int) -> list[tuple[int, float]]:
        m = self.models
        res = self.client.query_points(
            self.collection, query=vector.tolist(), limit=k,
            query_filter=m.Filter(must=[m.FieldCondition(
                key="snap", match=m.MatchValue(value=f"s{snapshot_id}"))]),
            search_params=m.SearchParams(quantization=m.QuantizationSearchParams(
                rescore=True, oversampling=2.0)),
        )
        return [(int(p.id), float(p.score)) for p in res.points]

    def delete_snapshot(self, snapshot_id: int) -> None:
        m = self.models
        self.client.delete(self.collection, points_selector=m.FilterSelector(
            filter=m.Filter(must=[m.FieldCondition(
                key="snap", match=m.MatchValue(value=f"s{snapshot_id}"))])))

    def count(self) -> int:
        return self.client.count(self.collection, exact=False).count


class FailoverStore:
    """Writes to both stores; reads from Qdrant, falling back to local on errors."""

    name = "failover"

    def __init__(self, primary: QdrantStore | None, local: LocalStore):
        self.primary = primary
        self.local = local
        self._down_until = 0.0
        self.last_used = "local"

    def _primary_ok(self) -> bool:
        return self.primary is not None and time.monotonic() >= self._down_until

    def _trip(self, err: Exception) -> None:
        log.warning("qdrant unavailable, using local vectors for 5 min: %s", err)
        self._down_until = time.monotonic() + 300

    def upsert(self, snapshot_id: int, items: list[tuple[int, np.ndarray]]) -> None:
        self.local.upsert(snapshot_id, items)
        if self._primary_ok():
            try:
                self.primary.upsert(snapshot_id, items)
            except Exception as e:  # noqa: BLE001
                self._trip(e)

    def search(self, snapshot_id: int, vector: np.ndarray, k: int) -> list[tuple[int, float]]:
        if self._primary_ok():
            try:
                hits = self.primary.search(snapshot_id, vector, k)
                self.last_used = "qdrant"
                return hits
            except Exception as e:  # noqa: BLE001
                self._trip(e)
        self.last_used = "local"
        return self.local.search(snapshot_id, vector, k)

    def delete_snapshot(self, snapshot_id: int) -> None:
        self.local.delete_snapshot(snapshot_id)
        if self.primary is not None:
            try:
                self.primary.delete_snapshot(snapshot_id)
            except Exception as e:  # noqa: BLE001
                self._trip(e)


_store: FailoverStore | None = None


def get_store(dim: int | None = None) -> FailoverStore:
    global _store
    if _store is None:
        primary = None
        if settings.qdrant_url and settings.qdrant_api_key:
            try:
                if dim is None:
                    from .embed import encode
                    dim = int(encode(["probe"]).shape[1])
                primary = QdrantStore(dim)
            except Exception as e:  # noqa: BLE001
                log.warning("qdrant disabled: %s", e)
        _store = FailoverStore(primary, LocalStore())
    return _store

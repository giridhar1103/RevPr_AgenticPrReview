"""Hybrid retrieval: lexical (FTS5), dense (vectors), structural (symbols and graph).

Channels are fused with Reciprocal Rank Fusion (Cormack et al., SIGIR 2009) and optionally
reranked with a CPU cross-encoder. Every call emits RETRIEVER / RERANKER spans.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

from . import db
from .identifiers import STOP_NAMES, fts_query
from .tracing import span

RRF_K = 60
CHANNEL_DEPTH = 40
RERANK_DEPTH = 20

# How much each graph relation is worth when expanding from seed symbols.
EDGE_WEIGHT = {
    ("calls", "in"): 1.0,     # callers of the seed
    ("calls", "out"): 0.8,    # callees of the seed
    ("tests", "in"): 1.0,     # tests exercising the seed
    ("inherits", "in"): 0.7,  # subclasses
    ("inherits", "out"): 0.7,  # base classes
    ("cochange", "out"): 0.6,  # files that change with the seed's file
    ("imports", "in"): 0.4,   # files importing the seed's file
    ("tests_file", "in"): 0.6,
}


@dataclass
class Hit:
    chunk_id: int
    path: str
    start_line: int
    end_line: int
    header: str
    text: str
    symbol_id: int | None
    score: float = 0.0
    ranks: dict[str, int] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    rerank: float | None = None

    def brief(self) -> dict:
        return {"id": self.chunk_id, "path": self.path, "lines": [self.start_line, self.end_line],
                "score": round(self.score, 4), "ranks": self.ranks,
                "reasons": self.reasons[:4],
                "rerank": None if self.rerank is None else round(self.rerank, 3)}


def _chunks(conn: sqlite3.Connection, ids: list[int]) -> dict[int, Hit]:
    if not ids:
        return {}
    q = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT c.id, f.path, c.start_line, c.end_line, c.header, c.text, c.symbol_id "
        f"FROM chunks c JOIN files f ON f.id = c.file_id WHERE c.id IN ({q})", ids).fetchall()
    return {r["id"]: Hit(r["id"], r["path"], r["start_line"], r["end_line"], r["header"],
                         r["text"], r["symbol_id"]) for r in rows}


# -- channels -----------------------------------------------------------------------------

def lexical(snapshot_id: int, query: str, limit: int = CHANNEL_DEPTH) -> list[int]:
    terms = fts_query(query)
    if not terms:
        return []
    conn = db.get()
    rows = conn.execute(
        "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? "
        "ORDER BY bm25(chunks_fts, 0.0, 2.0, 1.0) LIMIT ?",
        (f'snap : "s{snapshot_id}" AND ({terms})', limit)).fetchall()
    return [r[0] for r in rows]


def dense(snapshot_id: int, query: str, store, limit: int = CHANNEL_DEPTH) -> list[int]:
    from .embed import encode_query
    vec = encode_query(query)
    return [cid for cid, _ in store.search(snapshot_id, vec, limit)]


def symbol_matches(snapshot_id: int, query: str, limit: int = 20) -> list[int]:
    """Symbols whose name appears verbatim as an identifier in the query."""
    conn = db.get()
    dotted = {m.group(0) for m in re.finditer(r"[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)+", query)}
    out: list[int] = []
    if dotted:
        q = ",".join("?" * len(dotted))
        out = [r["id"] for r in conn.execute(
            f"SELECT id FROM symbols WHERE snapshot_id = ? AND qualname IN ({q}) LIMIT ?",
            [snapshot_id, *dotted, limit])]
    idents = {m.group(0) for m in re.finditer(r"[A-Za-z_][A-Za-z0-9_]{2,}", query)}
    idents = {i for i in idents if i.lower() not in STOP_NAMES}
    if not idents:
        return out
    q = ",".join("?" * len(idents))
    rows = conn.execute(
        f"SELECT id FROM symbols WHERE snapshot_id = ? AND name IN ({q}) AND kind != 'module' "
        f"ORDER BY (end_line - start_line) DESC LIMIT ?", [snapshot_id, *idents, limit]
    ).fetchall()
    return out + [r["id"] for r in rows if r["id"] not in out]


def symbol_chunks(snapshot_id: int, symbol_ids: list[int]) -> list[int]:
    """Map symbols to the chunk that starts their definition (or covers it)."""
    if not symbol_ids:
        return []
    conn = db.get()
    out: list[int] = []
    for sid in symbol_ids:
        row = conn.execute(
            "SELECT c.id FROM symbols s JOIN chunks c ON c.file_id = s.file_id "
            "AND c.start_line <= s.start_line AND c.end_line >= s.start_line "
            "WHERE s.id = ? ORDER BY c.start_line DESC LIMIT 1", (sid,)).fetchone()
        if row and row["id"] not in out:
            out.append(row["id"])
    return out


def expand(snapshot_id: int, seeds: list[int], limit: int = CHANNEL_DEPTH,
           min_conf: float = 0.5) -> list[tuple[int, str]]:
    """Graph neighbours of seed symbols, ranked by relation weight x edge confidence.

    Returns (symbol_id, reason) pairs. File-level relations are applied through each seed's
    module symbol.
    """
    if not seeds:
        return []
    conn = db.get()
    scores: dict[int, float] = {}
    reasons: dict[int, str] = {}
    q = ",".join("?" * len(seeds))
    modules = [r["mid"] for r in conn.execute(
        f"SELECT DISTINCT m.id AS mid FROM symbols s JOIN symbols m ON m.file_id = s.file_id "
        f"AND m.kind = 'module' WHERE s.id IN ({q})", seeds)]
    names = {r["id"]: r["qualname"] for r in conn.execute(
        f"SELECT id, qualname FROM symbols WHERE id IN ({q})", seeds)}

    def bump(sym: int, value: float, why: str) -> None:
        if sym in seeds:
            return
        if value > scores.get(sym, 0):
            scores[sym] = value
            reasons[sym] = why

    for (kind, direction), w in EDGE_WEIGHT.items():
        ids = modules if kind in ("cochange", "imports", "tests_file") else seeds
        if not ids:
            continue
        qq = ",".join("?" * len(ids))
        if direction == "in":
            sql = (f"SELECT src AS other, dst AS seed, weight FROM edges WHERE snapshot_id = ? "
                   f"AND kind = ? AND dst IN ({qq}) AND weight >= ? ORDER BY weight DESC LIMIT 60")
        else:
            sql = (f"SELECT dst AS other, src AS seed, weight FROM edges WHERE snapshot_id = ? "
                   f"AND kind = ? AND src IN ({qq}) AND weight >= ? ORDER BY weight DESC LIMIT 60")
        floor = 0.2 if kind == "cochange" else min_conf
        for r in conn.execute(sql, [snapshot_id, kind, *ids, floor]):
            label = {"calls": "caller of" if direction == "in" else "called by",
                     "tests": "tests", "inherits": "subclass of" if direction == "in"
                     else "base of", "cochange": "changes with", "imports": "imports",
                     "tests_file": "test file for"}[kind]
            seed_name = names.get(r["seed"]) or "the changed file"
            bump(r["other"], w * r["weight"], f"{label} {seed_name}")
    ranked = sorted(scores, key=lambda s: -scores[s])[:limit]
    return [(s, reasons[s]) for s in ranked]


# -- fusion -------------------------------------------------------------------------------

def rrf(lists: dict[str, list[int]], k: int = RRF_K) -> list[tuple[int, float, dict[str, int]]]:
    scores: dict[int, float] = {}
    ranks: dict[int, dict[str, int]] = {}
    for channel, ids in lists.items():
        for rank, cid in enumerate(ids, start=1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
            ranks.setdefault(cid, {})[channel] = rank
    order = sorted(scores, key=lambda c: -scores[c])
    return [(c, scores[c], ranks[c]) for c in order]


def search(snapshot_id: int, query: str, k: int = 10, seeds: list[int] | None = None,
           channels: tuple[str, ...] = ("lexical", "dense", "symbols", "graph"),
           use_rerank: bool = True, store=None, exclude: set[int] | None = None) -> list[Hit]:
    conn = db.get()
    exclude = exclude or set()
    lists: dict[str, list[int]] = {}
    reason_by_chunk: dict[int, list[str]] = {}

    with span("retrieve", "RETRIEVER", input=query, snapshot_id=snapshot_id,
              channels=",".join(channels)) as root:
        if "lexical" in channels:
            with span("retrieve.lexical", "RETRIEVER", input=query) as s:
                lists["lexical"] = lexical(snapshot_id, query)
                s.set("hits", len(lists["lexical"]))
        if "dense" in channels and store is not None:
            with span("retrieve.dense", "RETRIEVER", input=query) as s:
                try:
                    lists["dense"] = dense(snapshot_id, query, store)
                    s.set("backend", store.last_used)
                except Exception as e:  # noqa: BLE001
                    lists["dense"] = []
                    s.set("error", str(e)[:200])
                s.set("hits", len(lists["dense"]))
        seed_syms = list(seeds or [])
        if "symbols" in channels:
            with span("retrieve.symbols", "RETRIEVER", input=query) as s:
                matched = symbol_matches(snapshot_id, query)
                lists["symbols"] = symbol_chunks(snapshot_id, matched)
                for cid in lists["symbols"]:
                    reason_by_chunk.setdefault(cid, []).append("names a symbol in the query")
                seed_syms = seed_syms or matched[:5]
                s.set("hits", len(lists["symbols"]))
        if "graph" in channels and seed_syms:
            with span("retrieve.graph", "RETRIEVER", input=seed_syms) as s:
                related = expand(snapshot_id, seed_syms)
                chunk_ids = []
                for sym, why in related:
                    for cid in symbol_chunks(snapshot_id, [sym]):
                        if cid not in chunk_ids:
                            chunk_ids.append(cid)
                            reason_by_chunk.setdefault(cid, []).append(why)
                lists["graph"] = chunk_ids
                s.set("hits", len(chunk_ids))

        lists = {ch: [c for c in ids if c not in exclude] for ch, ids in lists.items()}
        fused = rrf(lists)[: max(k, RERANK_DEPTH)]
        hits_by_id = _chunks(conn, [c for c, _, _ in fused])
        hits: list[Hit] = []
        for cid, score, ranks in fused:
            h = hits_by_id.get(cid)
            if h is None:
                continue
            h.score, h.ranks = score, ranks
            h.reasons = reason_by_chunk.get(cid, []) + [
                f"{ch} #{r}" for ch, r in sorted(ranks.items(), key=lambda kv: kv[1])]
            hits.append(h)

        if use_rerank and len(hits) > 1:
            with span("rerank", "RERANKER", input=query, candidates=len(hits)) as s:
                from .embed import rerank
                scores = rerank(query, [(h.header + "\n" + h.text)[:1000] for h in hits])
                for h, sc in zip(hits, scores, strict=True):
                    h.rerank = sc
                # Blend: the reranker orders, RRF breaks near-ties and keeps structural hits.
                top_rr = max(scores) if scores else 1.0
                for h in hits:
                    h.score = 0.7 * ((h.rerank or 0) / (abs(top_rr) or 1.0)) + 0.3 * h.score * RRF_K
                hits.sort(key=lambda h: -h.score)
                s.set("reranked", len(hits))

        hits = hits[:k]
        root.documents([{"id": h.chunk_id, "score": h.score, "content": h.text,
                         "path": h.path, "lines": [h.start_line, h.end_line],
                         "ranks": h.ranks} for h in hits])
        root.set("channel_sizes", {ch: len(ids) for ch, ids in lists.items()})
    return hits

"""Snapshot indexing: clone, parse, chunk, lexical index, graph, history (docs/architecture.md).

Dense embeddings are not computed here; they fill in progressively (ADR 0004) through
`embed.embed_pending`, driven by the worker.
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import db, gitops, history
from .config import settings
from .graph import build_edges, pagerank
from .identifiers import identifier_terms
from .langs import detect, is_test_path
from .parsing import ParsedFile, parse_source

log = logging.getLogger(__name__)

Progress = Callable[[str, dict], None]


class IndexError_(Exception):
    pass


@dataclass
class SnapshotRef:
    id: int
    repo_id: int
    full_name: str
    sha: str
    status: str


def _parse_one(args: tuple[str, str]) -> ParsedFile | None:
    rel, full = args
    lang, parsed = detect(rel)
    if lang is None:
        return None
    data = gitops.read_text(Path(full))
    if data is None:
        return None
    return parse_source(rel, data, lang, parsed)


def get_or_create_snapshot(full_name: str, sha: str, meta: dict | None = None) -> SnapshotRef:
    conn = db.get()
    now = time.time()
    with db.transaction(conn):
        conn.execute(
            "INSERT INTO repos (full_name, default_branch, size_kb, stars, description, "
            "updated_at) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(full_name) DO UPDATE SET "
            "updated_at = excluded.updated_at",
            (full_name, (meta or {}).get("default_branch"), (meta or {}).get("size_kb"),
             (meta or {}).get("stars"), (meta or {}).get("description"), now))
        repo_id = conn.execute("SELECT id FROM repos WHERE full_name = ?",
                               (full_name,)).fetchone()["id"]
        conn.execute(
            "INSERT OR IGNORE INTO snapshots (repo_id, sha, created_at, last_used_at) "
            "VALUES (?, ?, ?, ?)", (repo_id, sha, now, now))
        row = conn.execute("SELECT id, status FROM snapshots WHERE repo_id = ? AND sha = ?",
                           (repo_id, sha)).fetchone()
        conn.execute("UPDATE snapshots SET last_used_at = ? WHERE id = ?", (now, row["id"]))
    return SnapshotRef(row["id"], repo_id, full_name, sha, row["status"])


def _set_stage(snapshot_id: int, status: str, stage: str, error: str | None = None) -> None:
    db.get().execute("UPDATE snapshots SET status = ?, stage = ?, error = ? WHERE id = ?",
                     (status, stage, error, snapshot_id))


def index_snapshot(full_name: str, sha: str, meta: dict | None = None,
                   progress: Progress | None = None) -> SnapshotRef:
    snap = get_or_create_snapshot(full_name, sha, meta)
    if snap.status == "ready":
        return snap
    emit = progress or (lambda stage, data: None)
    conn = db.get()
    t_start = time.monotonic()
    timings: dict[str, float] = {}

    def lap(name: str, t0: float) -> float:
        timings[name] = round(time.monotonic() - t0, 2)
        return time.monotonic()

    try:
        # Stale partial data from a crashed run.
        _clear_snapshot(snap.id)
        _set_stage(snap.id, "indexing", "clone")
        emit("clone", {"repo": full_name, "sha": sha[:10]})
        t = time.monotonic()
        with gitops.repo_lock(full_name):
            repo = gitops.ensure_clone(full_name)
            gitops.checkout(repo, sha)
            t = lap("clone", t)

            _set_stage(snap.id, "indexing", "parse")
            candidates: list[tuple[str, str]] = []
            for rel, full in gitops.iter_source_files(repo):
                lang, _ = detect(rel)
                if lang is not None:
                    candidates.append((rel, str(full)))
            parsed_langs = [c for c in candidates if detect(c[0])[1]]
            if len(parsed_langs) > settings.max_source_files:
                raise IndexError_(
                    f"Repository has {len(parsed_langs)} source files; the limit is "
                    f"{settings.max_source_files}.")
            emit("parse", {"files": len(candidates)})
            with ProcessPoolExecutor(max_workers=3) as pool:
                files = [f for f in pool.map(_parse_one, candidates, chunksize=16)
                         if f is not None]
            t = lap("parse", t)

            _set_stage(snap.id, "indexing", "history")
            hist = history.collect(repo, sha)
            t = lap("history", t)

        is_test = [is_test_path(f.path) for f in files]

        _set_stage(snap.id, "indexing", "graph")
        emit("graph", {"files": len(files), "symbols": sum(len(f.symbols) for f in files)})
        edges = build_edges(files, is_test)
        t = lap("graph", t)

        # File-level PageRank over imports and resolved references.
        file_edges: dict[tuple[int, int], float] = defaultdict(float)
        for kind, sf, _ss, df, _ds, w, _ln in edges.edges:
            if sf != df and kind in ("imports", "calls", "inherits"):
                file_edges[(sf, df)] += w
        ranks = pagerank(len(files), [(s, d, w) for (s, d), w in file_edges.items()])

        _set_stage(snap.id, "indexing", "store")
        emit("store", {"chunks": sum(len(f.chunks) for f in files)})
        _store(snap, files, is_test, edges, ranks, hist)
        t = lap("store", t)

        stats = {
            "files": len(files),
            "parsed_files": sum(1 for f in files if f.symbols),
            "symbols": sum(len(f.symbols) for f in files),
            "chunks": sum(len(f.chunks) for f in files),
            "edges": len(edges.edges),
            "commits": hist.commits,
            "languages": _lang_breakdown(files),
            "timings_s": timings,
            "total_s": round(time.monotonic() - t_start, 2),
        }
        dense_total = min(stats["chunks"], settings.dense_cap_per_snapshot)
        conn.execute(
            "UPDATE snapshots SET status = 'ready', stage = 'ready', stats = ?, "
            "dense_total = ?, error = NULL WHERE id = ?",
            (json.dumps(stats), dense_total, snap.id))
        emit("indexed", stats)
        snap.status = "ready"
        return snap
    except Exception as e:
        _set_stage(snap.id, "failed", "failed", str(e)[:500])
        raise


def _lang_breakdown(files: list[ParsedFile]) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for f in files:
        out[f.lang or "other"] += f.loc
    return dict(sorted(out.items(), key=lambda kv: -kv[1])[:8])


def _clear_snapshot(snapshot_id: int) -> None:
    conn = db.get()
    with db.transaction(conn):
        conn.execute(
            "DELETE FROM chunks_fts WHERE rowid IN (SELECT id FROM chunks WHERE snapshot_id = ?)",
            (snapshot_id,))
        conn.execute("DELETE FROM edges WHERE snapshot_id = ?", (snapshot_id,))
        conn.execute("DELETE FROM chunks WHERE snapshot_id = ?", (snapshot_id,))
        conn.execute("DELETE FROM symbols WHERE snapshot_id = ?", (snapshot_id,))
        conn.execute("DELETE FROM files WHERE snapshot_id = ?", (snapshot_id,))
        conn.execute("UPDATE snapshots SET dense_done = 0, dense_total = 0 WHERE id = ?",
                     (snapshot_id,))


def _store(snap: SnapshotRef, files: list[ParsedFile], is_test: list[bool], edges,
           ranks: list[float], hist: history.HistoryStats) -> None:
    conn = db.get()
    sid = snap.id
    snap_token = f"s{sid}"
    max_rank = max(ranks) if ranks else 1.0
    with db.transaction(conn):
        file_ids: list[int] = []
        module_ids: list[int] = []
        sym_ids: list[list[int]] = []
        for i, f in enumerate(files):
            cur = conn.execute(
                "INSERT INTO files (snapshot_id, path, lang, loc, complexity, is_test, churn, "
                "churn_recent, authors, last_commit_at, pagerank) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (sid, f.path, f.lang, f.loc, f.complexity, int(is_test[i]),
                 hist.churn.get(f.path, 0), hist.churn_recent.get(f.path, 0),
                 len(hist.authors.get(f.path, ())), hist.last_commit.get(f.path),
                 ranks[i] / max_rank if ranks else 0))
            fid = cur.lastrowid
            file_ids.append(fid)
            mcur = conn.execute(
                "INSERT INTO symbols (snapshot_id, file_id, name, qualname, kind, start_line, "
                "end_line, signature, parent_id) VALUES (?, ?, ?, ?, 'module', 1, ?, NULL, NULL)",
                (sid, fid, f.path.rsplit("/", 1)[-1], f.path, max(f.loc, 1)))
            module_ids.append(mcur.lastrowid)
            ids: list[int] = []
            for s in f.symbols:
                parent = ids[s.parent] if s.parent is not None else module_ids[-1]
                c = conn.execute(
                    "INSERT INTO symbols (snapshot_id, file_id, name, qualname, kind, "
                    "start_line, end_line, signature, parent_id) VALUES (?,?,?,?,?,?,?,?,?)",
                    (sid, fid, s.name, s.qualname, s.kind, s.start_line, s.end_line,
                     s.signature, parent))
                ids.append(c.lastrowid)
            sym_ids.append(ids)

            base_priority = ranks[i] / max_rank if ranks else 0.0
            if is_test[i]:
                base_priority *= 0.3
            if not f.symbols:
                base_priority *= 0.5
            for ch in f.chunks:
                sym = ids[ch.symbol] if ch.symbol is not None else None
                cc = conn.execute(
                    "INSERT INTO chunks (snapshot_id, file_id, start_line, end_line, symbol_id, "
                    "header, text, card, card_hash, priority) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (sid, fid, ch.start_line, ch.end_line, sym, ch.header, ch.text, ch.card,
                     ch.card_hash, base_priority))
                conn.execute(
                    "INSERT INTO chunks_fts (rowid, snap, idents, body) VALUES (?, ?, ?, ?)",
                    (cc.lastrowid, snap_token, identifier_terms(ch.header + "\n" + ch.text),
                     ch.header + "\n" + ch.text))

        def node(fi: int, si: int | None) -> int:
            return sym_ids[fi][si] if si is not None else module_ids[fi]

        rows: dict[tuple[str, int, int], tuple[float, int | None]] = {}
        for kind, sf, ss, df, ds, w, line in edges.edges:
            key = (kind, node(sf, ss), node(df, ds))
            if key[1] == key[2]:
                continue
            prev = rows.get(key)
            if prev is None or w > prev[0]:
                rows[key] = (w, line)

        path_idx = {f.path: i for i, f in enumerate(files)}
        for (a, b), n in hist.cochange.items():
            ia, ib = path_idx.get(a), path_idx.get(b)
            if ia is None or ib is None:
                continue
            denom = max(1, min(hist.churn.get(a, 1), hist.churn.get(b, 1)))
            w = round(n / denom, 3)
            rows[("cochange", module_ids[ia], module_ids[ib])] = (w, n)
            rows[("cochange", module_ids[ib], module_ids[ia])] = (w, n)

        conn.executemany(
            "INSERT OR REPLACE INTO edges (snapshot_id, kind, src, dst, weight, line) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(sid, k, s, d, w, ln) for (k, s, d), (w, ln) in rows.items()])

"""Retrieval eval on SWE-bench Lite (ADR 0011, suite 1). No LLM involved.

For each task the query is the real issue text and the gold set is what the reference patch
changed: files, and the functions/classes enclosing the changed lines at the base commit. We
measure how well each retrieval configuration ranks the gold locations.

Runs against a separate data directory and the local vector store so it never touches
production data or the hosted vector database.

    REVPR_DATA=/root/revpr/data/evaldb QDRANT_URL= \
        venv/bin/python -m evals.retrieval_eval prepare
    ... run --model jinaai/jina-embeddings-v2-base-code
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

os.environ.setdefault("REVPR_DATA", "/root/revpr/data/evaldb")
os.environ["QDRANT_URL"] = ""  # local exact search only

import pyarrow.parquet as pq  # noqa: E402

from revpr import db, embed, retrieval, tracing  # noqa: E402
from revpr.config import settings  # noqa: E402
from revpr.indexer import delete_snapshot, index_snapshot  # noqa: E402
from revpr.vectorstore import get_store  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "data" / "evals" / "swebench_lite.parquet"
OUT_DIR = ROOT / "data" / "evals"
REPOS = {"psf/requests": 6, "pallets/flask": 3, "mwaskom/seaborn": 4, "pylint-dev/pylint": 6,
         "pydata/xarray": 5, "pytest-dev/pytest": 6, "sphinx-doc/sphinx": 6}
CONFIGS = {
    "lexical": dict(channels=("lexical",), use_rerank=False),
    "dense": dict(channels=("dense",), use_rerank=False),
    "structural": dict(channels=("symbols", "graph"), use_rerank=False),
    "lexical+structural": dict(channels=("lexical", "symbols", "graph"), use_rerank=False),
    "hybrid": dict(channels=("lexical", "dense", "symbols", "graph"), use_rerank=False),
    "hybrid+rerank": dict(channels=("lexical", "dense", "symbols", "graph"), use_rerank=True),
}
K_CHUNKS = 40
# Channels that need no embeddings, evaluated on a larger stratified sample.
SPARSE_CONFIGS = {k: v for k, v in CONFIGS.items() if "dense" not in v["channels"]}
SPARSE_CONFIGS["lexical+structural+rerank"] = dict(channels=("lexical", "symbols", "graph"),
                                                   use_rerank=True)
PER_REPO_CAP = 15
_DIFF_FILE = re.compile(r"^diff --git a/(\S+) b/(\S+)$", re.M)
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@", re.M)


def select_tasks(seed: int = 7) -> list[dict]:
    rows = pq.read_table(DATASET).to_pylist()
    rng = random.Random(seed)
    tasks = []
    for repo, n in REPOS.items():
        pool = sorted((r for r in rows if r["repo"] == repo), key=lambda r: r["instance_id"])
        tasks += rng.sample(pool, min(n, len(pool)))
    return tasks


def gold_from_patch(patch: str) -> dict[str, list[tuple[int, int]]]:
    """{path: [(old_start, old_end), ...]} for non-test source files."""
    out: dict[str, list[tuple[int, int]]] = defaultdict(list)
    blocks = re.split(r"(?=^diff --git )", patch, flags=re.M)
    for block in blocks:
        m = _DIFF_FILE.search(block)
        if not m:
            continue
        path = m.group(1)
        for h in _HUNK.finditer(block):
            start = int(h.group(1))
            length = int(h.group(2) or 1)
            # The hunk includes 3 context lines on each side; the change is inside.
            out[path].append((start + 3, max(start + 3, start + length - 4)))
    return dict(out)


def gold_symbols(snapshot_id: int, gold: dict[str, list[tuple[int, int]]]) -> list[dict]:
    conn = db.get()
    syms = []
    for path, ranges in gold.items():
        rows = conn.execute(
            "SELECT s.id, s.qualname, s.start_line, s.end_line, s.kind FROM symbols s JOIN "
            "files f ON f.id = s.file_id WHERE f.snapshot_id = ? AND f.path = ? "
            "AND s.kind IN ('function', 'method', 'class')", (snapshot_id, path)).fetchall()
        for lo, hi in ranges:
            inner = [r for r in rows if r["start_line"] <= hi and r["end_line"] >= lo]
            if inner:
                best = min(inner, key=lambda r: r["end_line"] - r["start_line"])
                if not any(s["id"] == best["id"] for s in syms):
                    syms.append({"id": best["id"], "path": path, "qualname": best["qualname"],
                                 "start": best["start_line"], "end": best["end_line"]})
    return syms


def ensure_dense(snapshot_id: int) -> int:
    store = get_store()
    total = 0
    while True:
        n = embed.embed_pending(snapshot_id, 512, store)
        total += n
        if n == 0:
            return total


def prepare(args) -> None:
    db.init()
    tasks = select_tasks()
    manifest = []
    t0 = time.time()
    for i, t in enumerate(tasks, 1):
        snap = index_snapshot(t["repo"], t["base_commit"])
        db.get().execute("UPDATE snapshots SET dense_total = (SELECT COUNT(*) FROM chunks WHERE "
                         "snapshot_id = ?) WHERE id = ?", (snap.id, snap.id))
        gold = gold_from_patch(t["patch"])
        syms = gold_symbols(snap.id, gold)
        new = ensure_dense(snap.id) if not args.no_dense else 0
        manifest.append({"instance_id": t["instance_id"], "repo": t["repo"],
                         "snapshot_id": snap.id, "query": t["problem_statement"][:3000],
                         "gold_files": sorted(gold), "gold_symbols": syms})
        print(f"[{i}/{len(tasks)}] {t['instance_id']} snap={snap.id} gold_files={len(gold)} "
              f"gold_syms={len(syms)} embedded+={new} elapsed={time.time() - t0:.0f}s",
              flush=True)
    path = settings.data_dir / f"manifest_{embed.model_slug()}.json"
    path.write_text(json.dumps(manifest, indent=1))
    print("wrote", path)


def rank_files(hits: list[retrieval.Hit]) -> list[str]:
    seen: list[str] = []
    for h in hits:
        if h.path not in seen:
            seen.append(h.path)
    return seen


def score(task: dict, hits: list[retrieval.Hit]) -> dict:
    files = rank_files(hits)
    gold = set(task["gold_files"])
    m: dict[str, float] = {}
    for k in (1, 5, 10):
        top = set(files[:k])
        m[f"file_recall@{k}"] = len(gold & top) / len(gold) if gold else 0.0
        m[f"file_acc@{k}"] = float(gold <= top) if gold else 0.0
    first = next((i for i, f in enumerate(files, 1) if f in gold), None)
    m["file_mrr"] = 1.0 / first if first else 0.0
    gs = task["gold_symbols"]
    if gs:
        found = 0
        for g in gs:
            if any(h.path == g["path"] and h.start_line <= g["end"] and h.end_line >= g["start"]
                   for h in hits[:10]):
                found += 1
        m["function_recall@10chunks"] = found / len(gs)
    return m


def sparse(args) -> None:
    """Index, score and delete one task at a time over a stratified sample of all repos."""
    db.init()
    tracing.init("revpr-evals")
    rows = pq.read_table(DATASET).to_pylist()
    rng = random.Random(11)
    by_repo: dict[str, list[dict]] = defaultdict(list)
    for r in sorted(rows, key=lambda r: r["instance_id"]):
        by_repo[r["repo"]].append(r)
    tasks = []
    for _repo, pool in sorted(by_repo.items()):
        tasks += rng.sample(pool, min(args.per_repo, len(pool)))
    per_config: dict[str, list[dict]] = defaultdict(list)
    latency: dict[str, list[float]] = defaultdict(list)
    skipped = []
    t0 = time.time()
    for i, t in enumerate(tasks, 1):
        try:
            snap = index_snapshot(t["repo"], t["base_commit"])
        except Exception as e:  # noqa: BLE001
            skipped.append({"instance_id": t["instance_id"], "reason": str(e)[:200]})
            continue
        gold = gold_from_patch(t["patch"])
        task = {"instance_id": t["instance_id"], "repo": t["repo"], "snapshot_id": snap.id,
                "query": t["problem_statement"][:3000], "gold_files": sorted(gold),
                "gold_symbols": gold_symbols(snap.id, gold)}
        for name, cfg in SPARSE_CONFIGS.items():
            ts = time.perf_counter()
            hits = retrieval.search(snap.id, task["query"], k=K_CHUNKS, store=None, **cfg)
            latency[name].append((time.perf_counter() - ts) * 1000)
            per_config[name].append({"instance_id": t["instance_id"], "repo": t["repo"],
                                     **score(task, hits), "top_files": rank_files(hits)[:10],
                                     "gold_files": task["gold_files"]})
        delete_snapshot(snap.id)
        best = per_config["lexical+structural"][-1]
        print(f"[{i}/{len(tasks)}] {t['instance_id']} r@5={best['file_recall@5']:.2f} "
              f"mrr={best['file_mrr']:.2f} elapsed={time.time() - t0:.0f}s", flush=True)
    by_repo_summary = {}
    for repo in sorted({r["repo"] for r in per_config["lexical"]}):
        by_repo_summary[repo] = {n: _mean([r for r in rows_ if r["repo"] == repo])
                                 for n, rows_ in per_config.items()}
    summary = {
        "suite": "retrieval-sparse",
        "dataset": f"SWE-bench Lite, {len(per_config['lexical'])} tasks stratified across "
                   f"{len(by_repo_summary)} repositories (issue text as query)",
        "rerank_model": settings.rerank_model,
        "ran_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "tasks": len(per_config["lexical"]),
        "skipped": skipped,
        "configs": {n: {**_mean(r), "latency_ms_p50": _p50(latency[n])}
                    for n, r in per_config.items()},
        "by_repo": by_repo_summary,
    }
    (OUT_DIR / "retrieval_sparse.json").write_text(json.dumps(
        {"summary": summary, "rows": per_config}, indent=1))
    if args.phoenix:
        manifest = [{"instance_id": r["instance_id"], "query": "", "repo": r["repo"],
                     "gold_files": r["gold_files"], "gold_symbols": []}
                    for r in per_config["lexical"]]
        log_to_phoenix(manifest, dict(per_config), "sparse", dataset_name=
                       f"swebench-lite-localization-{len(manifest)}")
    print(json.dumps(summary["configs"], indent=1))


def run(args) -> None:
    tracing.init("revpr-evals")
    model = embed.model_slug()
    manifest = json.loads((settings.data_dir / f"manifest_{model}.json").read_text())
    store = get_store()
    per_config: dict[str, list[dict]] = {}
    latency: dict[str, list[float]] = defaultdict(list)
    for name, cfg in CONFIGS.items():
        rows = []
        for task in manifest:
            t = time.perf_counter()
            hits = retrieval.search(task["snapshot_id"], task["query"], k=K_CHUNKS, store=store,
                                    **cfg)
            latency[name].append((time.perf_counter() - t) * 1000)
            rows.append({"instance_id": task["instance_id"], **score(task, hits),
                         "top_files": rank_files(hits)[:10], "gold_files": task["gold_files"]})
        per_config[name] = rows
        print(name, _mean(rows), flush=True)

    summary = {
        "suite": "retrieval",
        "dataset": "SWE-bench Lite, 36 tasks from 7 repositories (issue text as query)",
        "embed_model": settings.embed_model,
        "rerank_model": settings.rerank_model,
        "ran_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "tasks": len(manifest),
        "configs": {n: {**_mean(r), "latency_ms_p50": _p50(latency[n])}
                    for n, r in per_config.items()},
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"retrieval_{model}.json").write_text(json.dumps(
        {"summary": summary, "rows": per_config}, indent=1))
    if args.phoenix:
        log_to_phoenix(manifest, per_config, model)
    print(json.dumps(summary, indent=1))


def _mean(rows: list[dict]) -> dict:
    keys = [k for k in rows[0] if isinstance(rows[0][k], float)] if rows else []
    out = {}
    for k in keys:
        vals = [r[k] for r in rows if k in r]
        out[k] = round(sum(vals) / len(vals), 3) if vals else None
    return out


def _p50(xs: list[float]) -> int:
    s = sorted(xs)
    return int(s[len(s) // 2]) if s else 0


def log_to_phoenix(manifest: list[dict], per_config: dict[str, list[dict]], model: str,
                   dataset_name: str = "swebench-lite-localization-36") -> None:
    """Record each configuration as a Phoenix experiment over a shared dataset."""
    from phoenix.client import Client
    client = Client(base_url="http://127.0.0.1:6006")
    name = dataset_name
    try:
        ds = client.datasets.get_dataset(dataset=name)
    except Exception:  # noqa: BLE001
        ds = client.datasets.create_dataset(
            name=name,
            inputs=[{"instance_id": t["instance_id"], "query": t["query"]} for t in manifest],
            outputs=[{"gold_files": t["gold_files"],
                      "gold_symbols": [g["qualname"] for g in t["gold_symbols"]]}
                     for t in manifest],
            metadata=[{"repo": t["repo"]} for t in manifest],
            dataset_description="Issue-to-code localization; gold from reference patches.")
    for cfg, rows in per_config.items():
        by_id = {r["instance_id"]: r for r in rows}

        def task(example, _by_id=by_id):
            return _by_id[example.input["instance_id"]]

        def metric(key):
            def ev(output):
                return float(output.get(key, 0.0))
            ev.__name__ = key.replace("@", "_at_")
            return ev

        client.experiments.run_experiment(
            dataset=ds, task=task,
            evaluators=[metric("file_recall@1"), metric("file_recall@5"),
                        metric("file_recall@10"), metric("file_mrr"),
                        metric("function_recall@10chunks")],
            experiment_name=f"{cfg} [{model}]",
            experiment_metadata={"config": cfg, "embed_model": model},
            print_summary=False)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--no-dense", action="store_true")
    r = sub.add_parser("run")
    r.add_argument("--phoenix", action="store_true")
    sp = sub.add_parser("sparse")
    sp.add_argument("--per-repo", type=int, default=PER_REPO_CAP)
    sp.add_argument("--phoenix", action="store_true")
    a = ap.parse_args()
    {"prepare": prepare, "run": run, "sparse": sparse}[a.cmd](a)
    sys.exit(0)

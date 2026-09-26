"""Combine eval outputs into data/evals/latest.json, which the API serves at /evals."""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "evals"


def _load(name: str) -> dict | None:
    p = OUT / name
    return json.loads(p.read_text())["summary"] if p.exists() else None


def main() -> None:
    latest: dict = {}
    sparse = _load("retrieval_sparse.json")
    models: dict = {}
    if sparse:
        models["no embeddings"] = {"configs": sparse["configs"]}
    for p in sorted(OUT.glob("retrieval_*.json")):
        if p.name == "retrieval_sparse.json":
            continue
        s = json.loads(p.read_text())["summary"]
        models[s["embed_model"].split("/")[-1]] = {"configs": s["configs"], "tasks": s["tasks"],
                                                   "dataset": s["dataset"]}
    if models:
        latest["retrieval"] = {
            "dataset": (sparse or {}).get("dataset", ""),
            "tasks": (sparse or {}).get("tasks"),
            "ran_at": (sparse or {}).get("ran_at", ""),
            "models": models,
            "by_repo": (sparse or {}).get("by_repo", {}),
        }
    bench = _load("review_bench.json")
    if bench:
        latest["review"] = bench
    (OUT / "latest.json").write_text(json.dumps(latest, indent=1))
    print(json.dumps({k: list(v) if isinstance(v, dict) else v for k, v in latest.items()},
                     indent=1))


if __name__ == "__main__":
    main()

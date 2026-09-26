"""Bug-reintroduction benchmark for PR review (ADR 0011, suite 2).

Each SWE-bench Lite task is a real bug fix. Reversing its reference patch gives a change that
re-introduces the bug, and the exact lines are known. We submit that change to the same review
pipeline used for GitHub PRs and check whether a finding lands on the re-introduced bug.

Reported per run:
- detection: a verified finding overlaps a gold hunk (the review a user would see)
- detection_pre_verify: any candidate finding overlaps a gold hunk (recall before the verifier)
- other_findings: verified findings elsewhere (not necessarily wrong; judged in suite 3)
- cost and latency

The base of each change is the fixed state: the reference patch is applied on top of the task's
base commit as a local commit, which is indexed; the change under review goes from that commit
back to the buggy code. (An earlier version indexed the buggy commit directly, so base-side
evidence contradicted the diff and the verifier rightly rejected true findings.)

Caveat: frontier models may have seen these public fixes during training; the pre/post
verification comparison and the other-findings rate are less exposed to that than raw detection.

    REVPR_DATA=data/benchdb QDRANT_URL= \
        venv/bin/python -m evals.review_bench --tasks 30 [--repeat 3 --only-first 10]
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import time
from collections import defaultdict
from pathlib import Path

os.environ.setdefault("REVPR_DATA", str(Path(__file__).resolve().parent.parent / "data" / "benchdb"))
os.environ["QDRANT_URL"] = ""

import pyarrow.parquet as pq  # noqa: E402

from revpr import db, gitops, tracing  # noqa: E402
from revpr.github import PRFile, PRInfo  # noqa: E402
from revpr.indexer import index_snapshot  # noqa: E402
from revpr.review.diffparse import parse_patch  # noqa: E402
from revpr.review.pr_review import review_change  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "data" / "evals" / "swebench_lite.parquet"
OUT = ROOT / "data" / "evals"
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")


def reverse_patch(file_patch: str) -> str:
    """Swap the sides of a unified diff for one file (fix -> bug)."""
    out = []
    for line in file_patch.splitlines():
        m = _HUNK.match(line)
        if m:
            o, ol, n, nl, rest = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
            old = f"{n},{nl}" if nl is not None else n
            new = f"{o},{ol}" if ol is not None else o
            out.append(f"@@ -{old} +{new} @@{rest}")
        elif line.startswith("+") and not line.startswith("+++"):
            out.append("-" + line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            out.append("+" + line[1:])
        elif line.startswith(("diff --git", "index ", "---", "+++")):
            continue
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def split_patch(patch: str) -> dict[str, str]:
    files = {}
    for block in re.split(r"(?=^diff --git )", patch, flags=re.M):
        m = re.search(r"^diff --git a/(\S+) b/(\S+)$", block, re.M)
        if m:
            files[m.group(2)] = block
    return files


def gold_regions(hunks) -> list[tuple[int, int]]:
    """New-side (buggy) line ranges of the re-introduced change, without context lines."""
    regions = []
    for h in hunks:
        lines = sorted(h.added)
        if lines:
            regions.append((lines[0], lines[-1]))
        else:  # the bug is a deletion of the fix: point at where it was
            anchor = h.new_start + 3
            regions.append((anchor - 1, anchor + 1))
    return regions


def overlaps(f: dict, regions: list[tuple[int, int]], slack: int = 3) -> bool:
    lo, hi = f["line_start"] - slack, f["line_end"] + slack
    return any(not (hi < a or lo > b) for a, b in regions)


def build_change(task: dict, snap, rdir: Path):
    per_file = split_patch(task["patch"])
    files, hunks, head, gold = [], {}, {}, {}
    for path, block in per_file.items():
        rev = reverse_patch(block)
        hs = parse_patch(rev)
        adds = sum(len(h.added) for h in hs)
        dels = sum(len(h.removed) for h in hs)
        files.append(PRFile(path, "modified", adds, dels, rev, None))
        hunks[path] = hs
        text = (rdir / path).read_text(errors="replace")
        head[path] = text
        gold[path] = gold_regions(hs)
    names = ", ".join(p.rsplit("/", 1)[-1] for p in per_file)
    title = f"Update {names}"
    pr = PRInfo(
        repo=task["repo"], number=0, title=title, body="", author="bench", state="open",
        merged=False, base_ref="main", base_sha=task["base_commit"], head_ref="bench",
        head_sha=task["base_commit"], additions=sum(f.additions for f in files),
        deletions=sum(f.deletions for f in files), changed_files=len(files),
        commits=[{"sha": "0" * 40, "message": title, "author": "bench"}], files=files,
        review_comments=[], issue_comments=[], url=f"https://github.com/{task['repo']}")
    return pr, files, hunks, head, gold


_FIXED: dict[str, str] = {}


def fixed_commit(task: dict) -> str:
    """Create (once) a local commit with the reference fix applied on the base commit."""
    if task["instance_id"] in _FIXED:
        return _FIXED[task["instance_id"]]
    rdir = gitops.ensure_clone(task["repo"])
    with gitops.repo_lock(task["repo"]):
        gitops.checkout(rdir, task["base_commit"])
        patch_file = rdir.parent / f".{task['instance_id']}.patch"
        patch_file.write_text(task["patch"])
        gitops.git(["apply", "--whitespace=nowarn", str(patch_file)], cwd=rdir)
        gitops.git(["-c", "user.name=bench", "-c", "user.email=bench@localhost", "commit",
                    "-q", "-a", "-m", f"reference fix for {task['instance_id']}"], cwd=rdir)
        sha = gitops.git(["rev-parse", "HEAD"], cwd=rdir).strip()
        patch_file.unlink()
        gitops.checkout(rdir, task["base_commit"])  # the buggy version is the PR head
    _FIXED[task["instance_id"]] = sha
    return sha


def run_task(task: dict) -> dict:
    fixed = fixed_commit(task)
    snap = index_snapshot(task["repo"], fixed)
    rdir = gitops.repo_dir(task["repo"])
    with gitops.repo_lock(task["repo"]):
        gitops.checkout(rdir, task["base_commit"])
    pr, files, hunks, head, gold = build_change(task, snap, rdir)
    pr.base_sha = fixed
    with gitops.repo_lock(task["repo"]):
        gitops.checkout(rdir, fixed)  # evidence reads base files from the working tree
    t = time.monotonic()
    result = review_change(pr, files, hunks, head, snap, rdir, [], lambda s, d: None)
    confirmed = result["findings"]
    candidates = confirmed + [f for f in result["hidden_findings"]
                              if f["verification"]["verdict"] != "dropped"]
    hit = [f for f in confirmed if f["path"] in gold and overlaps(f, gold[f["path"]])]
    hit_pre = [f for f in candidates if f["path"] in gold and overlaps(f, gold[f["path"]])]
    return {
        "instance_id": task["instance_id"], "repo": task["repo"],
        "detected": bool(hit), "detected_pre_verify": bool(hit_pre),
        "confirmed": len(confirmed), "candidates": len(candidates),
        "other_findings": len(confirmed) - len(hit),
        "hit_titles": [f["title"] for f in hit],
        "other_titles": [f"{f['severity']}: {f['title']}" for f in confirmed if f not in hit],
        "rejected_hits": [f["verification"]["reason"][:300] for f in hit_pre if f not in hit],
        "cost_usd": result["stats"]["cost_usd"],
        "seconds": round(time.monotonic() - t, 1),
        "findings": confirmed, "hidden": result["hidden_findings"],
        "gold": gold,
    }


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    if not n:
        return {}
    costs = [r["cost_usd"] for r in rows if r["cost_usd"] is not None]
    return {
        "tasks": n,
        "detection": round(sum(r["detected"] for r in rows) / n, 3),
        "detection_pre_verify": round(sum(r["detected_pre_verify"] for r in rows) / n, 3),
        "other_findings_per_pr": round(sum(r["other_findings"] for r in rows) / n, 2),
        "clean_reviews": round(sum(r["other_findings"] == 0 for r in rows) / n, 3),
        "avg_cost_usd": round(sum(costs) / len(costs), 4) if costs else None,
        "p50_seconds": sorted(r["seconds"] for r in rows)[n // 2],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", type=int, default=30)
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--only-first", type=int, default=0, help="repeat only the first N tasks")
    ap.add_argument("--seed", type=int, default=5)
    args = ap.parse_args()
    db.init()
    tracing.init("revpr-bench")

    rows_all = pq.read_table(DATASET).to_pylist()
    # Single-file fixes keep the change reviewable and the gold region unambiguous.
    single = [r for r in rows_all if r["patch"].count("diff --git") == 1]
    by_repo: dict[str, list[dict]] = defaultdict(list)
    for r in sorted(single, key=lambda r: r["instance_id"]):
        by_repo[r["repo"]].append(r)
    rng = random.Random(args.seed)
    per_repo = max(1, args.tasks // len(by_repo))
    tasks: list[dict] = []
    for _repo, pool in sorted(by_repo.items()):
        tasks += rng.sample(pool, min(per_repo, len(pool)))
    rng.shuffle(tasks)
    tasks = tasks[: args.tasks]

    runs: list[list[dict]] = []
    for rep in range(args.repeat):
        subset = tasks if rep == 0 or not args.only_first else tasks[: args.only_first]
        rows = []
        for i, task in enumerate(subset, 1):
            try:
                row = run_task(task)
            except Exception as e:  # noqa: BLE001
                print(f"[{rep}:{i}] {task['instance_id']} ERROR {e}", flush=True)
                continue
            rows.append(row)
            print(f"[{rep}:{i}/{len(subset)}] {task['instance_id']} detected={row['detected']} "
                  f"pre={row['detected_pre_verify']} other={row['other_findings']} "
                  f"${row['cost_usd']} {row['seconds']}s", flush=True)
        runs.append(rows)

    summary = {"suite": "review-bug-reintroduction", "dataset":
               "SWE-bench Lite single-file fixes, reversed into bug-introducing changes",
               "ran_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
               "run1": summarize(runs[0])}
    if len(runs) > 1:
        ids = [r["instance_id"] for r in runs[1]]
        by_run = [{r["instance_id"]: r for r in run} for run in runs]
        common = [i for i in ids if all(i in br for br in by_run)]
        k = len(runs)
        summary[f"pass^{k}"] = round(sum(all(br[i]["detected"] for br in by_run)
                                         for i in common) / max(1, len(common)), 3)
        summary[f"pass@{k}"] = round(sum(any(br[i]["detected"] for br in by_run)
                                         for i in common) / max(1, len(common)), 3)
        summary["repeated_tasks"] = len(common)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "review_bench.json").write_text(json.dumps(
        {"summary": summary, "runs": runs}, indent=1, default=str))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()

"""Precision judge (ADR 0011, suite 3).

The bug-reintroduction benchmark only knows about one bug per change. Verified findings
elsewhere may be real issues or false positives. Each one is judged by a model from a different
vendor than the reviewer (to avoid self-preference bias), with a binary valid/invalid label and
a reason, from the code around the cited lines. Labels are exported to CSV with an empty
`human_label` column; filling a sample of it gives the judge's agreement rate.

    REVPR_DATA=/root/revpr/data/benchdb venv/bin/python -m evals.judge_findings
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

os.environ.setdefault("REVPR_DATA", "/root/revpr/data/benchdb")

from revpr import gitops, tracing  # noqa: E402
from revpr.llm.client import complete_json, role_label  # noqa: E402
from revpr.review.diffparse import numbered  # noqa: E402
from revpr.review.prompts import UNTRUSTED  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "data" / "evals"

JUDGE_SYSTEM = f"""You are auditing an automated code reviewer. For one finding, decide from the
code shown whether it describes a real problem a maintainer would want fixed (valid) or not
(invalid: wrong, already handled, speculative, or a style preference). {UNTRUSTED}
Answer with JSON only."""

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {"label": {"type": "string", "enum": ["valid", "invalid"]},
                   "reason": {"type": "string"}},
    "required": ["label", "reason"], "additionalProperties": False,
}


def main() -> None:
    tracing.init("revpr-bench")
    bench = json.loads((OUT / "review_bench.json").read_text())
    import pyarrow.parquet as pq
    tasks = {r["instance_id"]: r for r in
             pq.read_table(OUT / "swebench_lite.parquet").to_pylist()}
    rows = []
    for run in bench["runs"][:1]:
        for row in run:
            task = tasks[row["instance_id"]]
            gold = row["gold"]
            for f in row["findings"]:
                on_gold = f["path"] in gold and any(
                    not (f["line_end"] + 3 < a or f["line_start"] - 3 > b)
                    for a, b in gold[f["path"]])
                if on_gold:
                    continue
                text = gitops.show_file(gitops.repo_dir(task["repo"]), task["base_commit"],
                                        f["path"]) or ""
                lo, hi = max(1, f["line_start"] - 30), f["line_end"] + 30
                prompt = (f"Finding ({f['severity']}, {f['category']}) at {f['path']}:"
                          f"{f['line_start']}-{f['line_end']}\nTitle: {f['title']}\n"
                          f"Explanation: {f['explanation']}\n\n<evidence>\n"
                          f"{numbered(text, lo, hi)}\n</evidence>")
                try:
                    obj, _ = complete_json("judge", JUDGE_SYSTEM, prompt, JUDGE_SCHEMA)
                except Exception as e:  # noqa: BLE001
                    obj = {"label": "error", "reason": str(e)[:200]}
                rows.append({"instance_id": row["instance_id"], "path": f["path"],
                             "line": f["line_start"], "severity": f["severity"],
                             "title": f["title"], "judge_label": obj["label"],
                             "judge_reason": obj["reason"][:400], "human_label": ""})
                print(row["instance_id"], obj["label"], f["title"][:80], flush=True)
    with open(OUT / "judge_labels.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["instance_id"])
        w.writeheader()
        w.writerows(rows)
    judged = [r for r in rows if r["judge_label"] in ("valid", "invalid")]
    summary = {
        "judge": role_label("judge"),
        "off_target_findings": len(rows),
        "judged_valid": sum(r["judge_label"] == "valid" for r in judged),
        "judged_invalid": sum(r["judge_label"] == "invalid" for r in judged),
    }
    if judged:
        summary["off_target_valid_rate"] = round(summary["judged_valid"] / len(judged), 3)
    bench["summary"]["precision_judge"] = summary
    (OUT / "review_bench.json").write_text(json.dumps(bench, indent=1, default=str))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()

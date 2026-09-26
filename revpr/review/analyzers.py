"""Static analyzers run on changed files. They read code and never execute it."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Rules that find real defects rather than style: pyflakes, syntax errors, bugbear.
RUFF_SELECT = "E9,F,B,PLE,S102,S307"


def ruff(files: dict[str, str], lines: dict[str, set[int]]) -> list[dict]:
    """Run ruff over the given Python sources; keep findings on changed lines only."""
    py = {p: t for p, t in files.items() if p.endswith(".py")}
    if not py:
        return []
    ruff_bin = Path(sys.executable).parent / "ruff"
    with tempfile.TemporaryDirectory() as td:
        for rel, text in py.items():
            dest = Path(td) / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text)
        proc = subprocess.run(
            [str(ruff_bin), "check", "--no-cache", "--isolated", "--select", RUFF_SELECT,
             "--output-format", "json", "--exit-zero", "."],
            cwd=td, capture_output=True, text=True, timeout=60)
    try:
        items = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return []
    out = []
    for it in items:
        rel = os.path.relpath(it["filename"], td) if os.path.isabs(it["filename"]) \
            else it["filename"]
        rel = rel.lstrip("./")
        row = it["location"]["row"]
        if row in lines.get(rel, set()):
            out.append({"tool": "ruff", "rule": it["code"], "path": rel, "line": row,
                        "message": it["message"]})
    return out[:40]

"""Unified diff parsing and mapping of hunks to changed symbols."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")


@dataclass
class Hunk:
    old_start: int
    old_len: int
    new_start: int
    new_len: int
    header: str
    lines: list[str] = field(default_factory=list)
    added: list[int] = field(default_factory=list)    # new-side line numbers
    removed: list[int] = field(default_factory=list)  # old-side line numbers

    @property
    def new_range(self) -> tuple[int, int]:
        return self.new_start, self.new_start + max(self.new_len, 1) - 1

    @property
    def old_range(self) -> tuple[int, int]:
        return self.old_start, self.old_start + max(self.old_len, 1) - 1


def parse_patch(patch: str | None) -> list[Hunk]:
    hunks: list[Hunk] = []
    if not patch:
        return hunks
    cur: Hunk | None = None
    old_no = new_no = 0
    for line in patch.splitlines():
        m = _HUNK.match(line)
        if m:
            cur = Hunk(int(m.group(1)), int(m.group(2) or 1), int(m.group(3)),
                       int(m.group(4) or 1), m.group(5).strip())
            hunks.append(cur)
            old_no, new_no = cur.old_start, cur.new_start
            continue
        if cur is None:
            continue
        cur.lines.append(line)
        if line.startswith("+"):
            cur.added.append(new_no)
            new_no += 1
        elif line.startswith("-"):
            cur.removed.append(old_no)
            old_no += 1
        elif line.startswith("\\"):
            continue
        else:
            old_no += 1
            new_no += 1
    return hunks


def changed_new_lines(hunks: list[Hunk]) -> set[int]:
    return {n for h in hunks for n in h.added}


def changed_old_lines(hunks: list[Hunk]) -> set[int]:
    return {n for h in hunks for n in h.removed}


def in_hunks(hunks: list[Hunk], line: int, side: str = "new", slack: int = 3) -> bool:
    for h in hunks:
        lo, hi = h.new_range if side == "new" else h.old_range
        if lo - slack <= line <= hi + slack:
            return True
    return False


def numbered(text: str, start: int = 1, end: int | None = None) -> str:
    lines = text.splitlines()
    end = min(end or len(lines), len(lines))
    width = len(str(end))
    return "\n".join(f"{i:>{width}} | {lines[i - 1]}" for i in range(max(start, 1), end + 1))


def annotate_patch(path: str, hunks: list[Hunk]) -> str:
    """Render a patch with explicit new-side line numbers so the model can cite them."""
    out = [f"--- {path}"]
    for h in hunks:
        out.append(f"@@ old {h.old_start},{h.old_len} new {h.new_start},{h.new_len} @@ {h.header}")
        old_no, new_no = h.old_start, h.new_start
        for line in h.lines:
            if line.startswith("+"):
                out.append(f"{new_no:>5} + {line[1:]}")
                new_no += 1
            elif line.startswith("-"):
                out.append(f"{'':>5} - {line[1:]}")
                old_no += 1
            elif line.startswith("\\"):
                continue
            else:
                out.append(f"{new_no:>5}   {line[1:]}")
                old_no += 1
                new_no += 1
    return "\n".join(out)

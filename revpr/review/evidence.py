"""Evidence collection: the context pack and the investigation tools.

Every piece of context shown to the model is an `Evidence` item with a stable id (E1, E2, ...).
Findings must cite these ids, which makes grounding checkable without another model call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .. import db, gitops, retrieval
from .diffparse import numbered

MAX_ITEM_CHARS = 2400


@dataclass
class Evidence:
    id: str
    kind: str        # head_symbol, definition, caller, callee, test, subclass, cochange,
    #                  history, search, analyzer, read
    path: str
    start: int | None
    end: int | None
    text: str
    reason: str
    source: str = "base"  # base snapshot or PR head

    def render(self) -> str:
        loc = f"{self.path}:{self.start}-{self.end}" if self.start else self.path
        return (f'<evidence id="{self.id}" kind="{self.kind}" location="{loc}" '
                f'source="{self.source}" why="{self.reason}">\n{self.text}\n</evidence>')

    def brief(self) -> dict:
        return {"id": self.id, "kind": self.kind, "path": self.path, "start": self.start,
                "end": self.end, "reason": self.reason, "source": self.source}


@dataclass(eq=False)
class EvidenceStore:
    snapshot_id: int
    repo_dir: Path
    base_sha: str
    head_files: dict[str, str] = field(default_factory=dict)  # PR head contents by path
    items: list[Evidence] = field(default_factory=list)
    seen_spans: set[tuple[str, int, int]] = field(default_factory=set)
    seen_chunks: set[int] = field(default_factory=set)
    store: object | None = None  # vector store for search
    on_add: object | None = None  # called with each new item, for live progress

    def add(self, kind: str, path: str, start: int | None, end: int | None, text: str,
            reason: str, source: str = "base", dedupe: bool = True,
            max_chars: int = MAX_ITEM_CHARS) -> Evidence | None:
        if dedupe and start is not None and end is not None:
            key = (path, start, end)
            for (p, s, e) in self.seen_spans:
                if p == path and s <= start and end <= e:
                    return None
            self.seen_spans.add(key)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n... [truncated]"
        ev = Evidence(f"E{len(self.items) + 1}", kind, path, start, end, text, reason, source)
        self.items.append(ev)
        if self.on_add is not None:
            self.on_add(ev)
        return ev

    def get(self, eid: str) -> Evidence | None:
        for ev in self.items:
            if ev.id == eid:
                return ev
        return None

    def total_chars(self) -> int:
        return sum(len(e.text) for e in self.items)

    # -- lookups against the base snapshot -------------------------------------------------
    def base_text(self, path: str) -> str | None:
        full = self.repo_dir / path
        try:
            return full.read_text(errors="replace")
        except OSError:
            return None

    def symbol_rows(self, name: str, limit: int = 5) -> list:
        conn = db.get()
        if "." in name:
            rows = conn.execute(
                "SELECT s.*, f.path FROM symbols s JOIN files f ON f.id = s.file_id "
                "WHERE s.snapshot_id = ? AND s.qualname = ? LIMIT ?",
                (self.snapshot_id, name, limit)).fetchall()
            if rows:
                return rows
            name = name.rsplit(".", 1)[-1]
        return conn.execute(
            "SELECT s.*, f.path FROM symbols s JOIN files f ON f.id = s.file_id "
            "WHERE s.snapshot_id = ? AND s.name = ? AND s.kind != 'module' "
            "ORDER BY f.is_test, (s.end_line - s.start_line) DESC LIMIT ?",
            (self.snapshot_id, name, limit)).fetchall()

    def symbol_snippet(self, row, max_lines: int = 60) -> tuple[str, int, int]:
        text = self.base_text(row["path"]) or ""
        start, end = row["start_line"], min(row["end_line"], row["start_line"] + max_lines - 1)
        return numbered(text, start, end), start, end

    def add_symbol(self, row, kind: str, reason: str, max_lines: int = 60) -> Evidence | None:
        snippet, start, end = self.symbol_snippet(row, max_lines)
        if not snippet.strip():
            return None
        return self.add(kind, row["path"], start, end, snippet, reason)

    def neighbours(self, symbol_id: int, kind: str, direction: str, min_conf: float = 0.5,
                   limit: int = 4) -> list:
        conn = db.get()
        col, other = ("dst", "src") if direction == "in" else ("src", "dst")
        return conn.execute(
            f"SELECT s.*, f.path, e.weight FROM edges e JOIN symbols s ON s.id = e.{other} "
            f"JOIN files f ON f.id = s.file_id WHERE e.snapshot_id = ? AND e.kind = ? "
            f"AND e.{col} = ? AND e.weight >= ? ORDER BY e.weight DESC, f.is_test LIMIT ?",
            (self.snapshot_id, kind, symbol_id, min_conf, limit)).fetchall()

    # -- investigation tools (model-requested) ---------------------------------------------
    def tool(self, name: str, args: dict) -> list[Evidence]:
        name = (name or "").lower()
        try:
            if name == "search":
                return self.t_search(str(args.get("query", ""))[:300])
            if name in ("symbol", "definition"):
                return self.t_symbol(str(args.get("name", "")))
            if name == "callers":
                return self.t_rel(str(args.get("name", "")), "calls", "in", "caller")
            if name == "callees":
                return self.t_rel(str(args.get("name", "")), "calls", "out", "callee")
            if name == "tests":
                return self.t_rel(str(args.get("name", "")), "tests", "in", "test")
            if name == "history":
                return self.t_history(str(args.get("path", "")))
            if name == "read":
                return self.t_read(str(args.get("path", "")), int(args.get("start", 1)),
                                   int(args.get("end", 0)) or None)
        except Exception as e:  # noqa: BLE001
            ev = self.add("tool_error", name, None, None, f"tool failed: {e}", "tool error")
            return [ev] if ev else []
        return []

    def t_search(self, query: str) -> list[Evidence]:
        hits = retrieval.search(self.snapshot_id, query, k=4, store=self.store,
                                exclude=self.seen_chunks, use_rerank=False)
        out = []
        for h in hits:
            self.seen_chunks.add(h.chunk_id)
            ev = self.add("search", h.path, h.start_line, h.end_line,
                          numbered(self.base_text(h.path) or h.text, h.start_line, h.end_line),
                          f"search: {query[:80]}")
            if ev:
                out.append(ev)
        return out

    def t_symbol(self, name: str) -> list[Evidence]:
        out = []
        for row in self.symbol_rows(name, 3):
            ev = self.add_symbol(row, "definition", f"definition of {row['qualname']}")
            if ev:
                out.append(ev)
        return out

    def t_rel(self, name: str, kind: str, direction: str, label: str) -> list[Evidence]:
        out = []
        for row in self.symbol_rows(name, 2):
            for nb in self.neighbours(row["id"], kind, direction, limit=4):
                ev = self.add_symbol(nb, label, f"{label} of {row['qualname']}", max_lines=40)
                if ev:
                    out.append(ev)
        return out

    def t_history(self, path: str) -> list[Evidence]:
        rows = gitops.file_log(self.repo_dir, self.base_sha, path, limit=8)
        if not rows:
            return []
        text = "\n".join(f"{r['sha']} {r['author']}: {r['subject']}" for r in rows)
        ev = self.add("history", path, None, None, text, f"recent commits touching {path}")
        return [ev] if ev else []

    def t_read(self, path: str, start: int, end: int | None) -> list[Evidence]:
        source = "head" if path in self.head_files else "base"
        text = self.head_files.get(path) if source == "head" else self.base_text(path)
        if text is None:
            return []
        end = min(end or start + 60, start + 120)
        ev = self.add("read", path, start, end, numbered(text, start, end),
                      f"requested lines {start}-{end}", source)
        return [ev] if ev else []

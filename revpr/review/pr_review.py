"""PR review workflow (ADR 0008)."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Callable

from .. import db, embed, gitops, retrieval
from ..config import settings
from ..github import GitHub, GitHubError, PRFile, PRInfo, parse_pr_url
from ..indexer import index_snapshot
from ..langs import detect, is_test_path
from ..llm.client import complete_json, role_label
from ..parsing import parse_source
from ..tracing import span
from ..vectorstore import get_store
from . import analyzers
from .diffparse import Hunk, annotate_patch, changed_new_lines, in_hunks, numbered, parse_patch
from .evidence import EvidenceStore
from .prompts import (REVIEW_SCHEMA, REVIEW_SYSTEM, SEVERITIES, VERIFY_SCHEMA, VERIFY_SYSTEM)

PIPELINE_VERSION = "pr-2"
MAX_ROUNDS = 2
MAX_REQUESTS = 3
CONTEXT_BUDGET = 70_000
DIFF_BUDGET = 60_000
MAX_CHANGED_SYMBOLS = 10

_SKIP_SUFFIXES = (".lock", "-lock.json", ".min.js", ".min.css", ".map", ".snap", ".svg",
                  ".png", ".jpg", ".gif", ".ico", ".pdf", ".woff", ".woff2", ".ttf")
_SKIP_NAMES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Cargo.lock",
               "go.sum", "composer.lock", "Gemfile.lock", "uv.lock"}

Progress = Callable[[str, dict], None]


class ReviewError(Exception):
    pass


@dataclass
class ChangedSymbol:
    path: str
    name: str
    qualname: str
    kind: str
    status: str  # added, modified, removed
    head_range: tuple[int, int] | None
    base_id: int | None
    base_range: tuple[int, int] | None
    changed_lines: int
    callee_names: list[str]


def _reviewable(f: PRFile) -> bool:
    name = f.path.rsplit("/", 1)[-1]
    if name in _SKIP_NAMES or f.path.endswith(_SKIP_SUFFIXES):
        return False
    return detect(f.path)[0] is not None and bool(f.patch)


def admit(pr: PRInfo) -> tuple[list[PRFile], list[str]]:
    """Pick the files to review under the size limits; return (files, notes)."""
    notes: list[str] = []
    files = [f for f in pr.files if _reviewable(f)]
    skipped = len(pr.files) - len(files)
    if skipped:
        notes.append(f"{skipped} generated, binary or lock files were skipped.")
    if pr.changed_files > len(pr.files):
        notes.append(f"GitHub listed {len(pr.files)} of {pr.changed_files} changed files.")
    files.sort(key=lambda f: (is_test_path(f.path), -(f.additions + f.deletions)))
    kept: list[PRFile] = []
    total = 0
    for f in files:
        size = f.additions + f.deletions
        if len(kept) >= settings.max_pr_files or total + size > settings.max_pr_changed_lines:
            continue
        kept.append(f)
        total += size
    if len(kept) < len(files):
        notes.append(f"Reviewed the {len(kept)} largest source files of {len(files)} to stay "
                     f"within {settings.max_pr_changed_lines} changed lines.")
    if not kept:
        raise ReviewError("This PR has no reviewable source changes.")
    return kept, notes


def _changed_symbols(ev: EvidenceStore, files: list[PRFile], hunks: dict[str, list[Hunk]],
                     head: dict[str, str]) -> list[ChangedSymbol]:
    conn = db.get()
    out: dict[tuple[str, str], ChangedSymbol] = {}
    for f in files:
        hs = hunks[f.path]
        base_path = f.previous_path or f.path
        # Base side: symbols overlapping removed lines or modified hunks.
        base_rows = conn.execute(
            "SELECT s.* FROM symbols s JOIN files fl ON fl.id = s.file_id WHERE "
            "s.snapshot_id = ? AND fl.path = ? AND s.kind != 'module'",
            (ev.snapshot_id, base_path)).fetchall()
        removed = {n for h in hs for n in h.removed}
        old_touched = removed | {h.old_start + i for h in hs if h.added and not h.removed
                                 for i in range(0, 1)}
        base_by_qual = {r["qualname"]: r for r in base_rows}
        # Head side: parse the PR version to find symbols containing added lines.
        added_lines = changed_new_lines(hs)
        head_syms = []
        head_refs = []
        if f.status != "removed" and f.path in head:
            lang, parsed = detect(f.path)
            pf = parse_source(f.path, head[f.path].encode(), lang, parsed)
            head_syms = pf.symbols
            head_refs = pf.refs
        for idx, s in enumerate(head_syms):
            n = sum(1 for ln in added_lines if s.start_line <= ln <= s.end_line)
            if not n:
                continue
            # Only the innermost symbols: skip a class if one of its methods carries the change.
            inner = any(c.parent == idx and any(c.start_line <= ln <= c.end_line
                                                for ln in added_lines) for c in head_syms)
            if inner:
                continue
            base = base_by_qual.get(s.qualname)
            callees = sorted({r.name for r in head_refs if r.scope == idx})[:12]
            out[(f.path, s.qualname)] = ChangedSymbol(
                f.path, s.name, s.qualname, s.kind, "modified" if base else "added",
                (s.start_line, s.end_line), base["id"] if base else None,
                (base["start_line"], base["end_line"]) if base else None, n, callees)
        for r in base_rows:
            n = sum(1 for ln in old_touched if r["start_line"] <= ln <= r["end_line"])
            if not n or (f.path, r["qualname"]) in out:
                continue
            if any(o.base_id == r["id"] for o in out.values()):
                continue
            still_there = any(s.qualname == r["qualname"] for s in head_syms)
            status = "modified" if still_there else "removed"
            # Prefer innermost base symbols too.
            if any(c["parent_id"] == r["id"] and any(c["start_line"] <= ln <= c["end_line"]
                                                     for ln in old_touched) for c in base_rows):
                continue
            out[(f.path, r["qualname"])] = ChangedSymbol(
                f.path, r["name"], r["qualname"], r["kind"], status, None, r["id"],
                (r["start_line"], r["end_line"]), n, [])
    ranked = sorted(out.values(), key=lambda c: (is_test_path(c.path), -c.changed_lines))
    return ranked


def _build_context(ev: EvidenceStore, pr: PRInfo, files: list[PRFile],
                   changed: list[ChangedSymbol], head: dict[str, str]) -> None:
    pr_paths = {f.path for f in files} | {f.previous_path for f in files if f.previous_path}
    conn = db.get()

    with span("context.symbols", "CHAIN", changed=len(changed)):
        for cs in changed[:MAX_CHANGED_SYMBOLS]:
            if ev.total_chars() > CONTEXT_BUDGET:
                break
            if cs.head_range and cs.path in head:
                a, b = cs.head_range
                ev.add("head_symbol", cs.path, a, min(b, a + 90),
                       numbered(head[cs.path], a, min(b, a + 90)),
                       f"PR version of {cs.qualname} ({cs.status})", source="head")
            elif cs.base_range:
                row = conn.execute("SELECT s.*, f.path FROM symbols s JOIN files f ON "
                                   "f.id = s.file_id WHERE s.id = ?", (cs.base_id,)).fetchone()
                if row:
                    ev.add_symbol(row, "definition", f"base version of removed {cs.qualname}")
            if cs.base_id:
                for nb in ev.neighbours(cs.base_id, "calls", "in", limit=3):
                    if nb["path"] in pr_paths and nb["path"] in head:
                        continue  # caller changed in this PR: the diff shows it
                    ev.add_symbol(nb, "caller", f"calls {cs.qualname}", max_lines=30)
                for nb in ev.neighbours(cs.base_id, "tests", "in", limit=2):
                    ev.add_symbol(nb, "test", f"tests {cs.qualname}", max_lines=30)
                for nb in ev.neighbours(cs.base_id, "inherits", "in", limit=2):
                    ev.add_symbol(nb, "subclass", f"subclass of {cs.qualname}", max_lines=20)
                for nb in ev.neighbours(cs.base_id, "calls", "out", min_conf=0.8, limit=3):
                    if nb["path"] not in pr_paths:
                        ev.add_symbol(nb, "callee", f"called by {cs.qualname}", max_lines=25)
            else:
                for name in cs.callee_names[:6]:
                    rows = ev.symbol_rows(name, 1)
                    if rows and rows[0]["path"] not in pr_paths:
                        ev.add_symbol(rows[0], "callee", f"called by new {cs.qualname}",
                                      max_lines=25)

    with span("context.cochange", "CHAIN"):
        changed_names = " ".join(c.name for c in changed[:MAX_CHANGED_SYMBOLS])
        for f in files[:8]:
            if ev.total_chars() > CONTEXT_BUDGET:
                break
            rows = conn.execute(
                "SELECT f2.path, e.weight, e.line AS n FROM files f1 "
                "JOIN symbols m1 ON m1.file_id = f1.id AND m1.kind = 'module' "
                "JOIN edges e ON e.snapshot_id = f1.snapshot_id AND e.kind = 'cochange' "
                "AND e.src = m1.id JOIN symbols m2 ON m2.id = e.dst "
                "JOIN files f2 ON f2.id = m2.file_id "
                "WHERE f1.snapshot_id = ? AND f1.path = ? AND e.weight >= 0.3 "
                "ORDER BY e.weight DESC LIMIT 4", (ev.snapshot_id, f.path)).fetchall()
            partners = [r for r in rows if r["path"] not in pr_paths]
            if not partners:
                continue
            listing = "\n".join(f"{r['path']}: changed together in {r['n']} commits "
                                f"(coupling {r['weight']:.2f})" for r in partners)
            ev.add("cochange", f.path, None, None, listing,
                   f"files that usually change with {f.path} but are not in this PR")
            top = partners[0]["path"]
            for cid in retrieval.lexical(ev.snapshot_id, changed_names or f.path, limit=60):
                row = conn.execute("SELECT c.start_line, c.end_line, fl.path FROM chunks c "
                                   "JOIN files fl ON fl.id = c.file_id WHERE c.id = ?",
                                   (cid,)).fetchone()
                if row and row["path"] == top:
                    text = ev.base_text(top) or ""
                    ev.add("cochange", top, row["start_line"], row["end_line"],
                           numbered(text, row["start_line"], row["end_line"]),
                           f"part of {top} most related to the changed symbols")
                    break

    with span("context.search", "CHAIN"):
        query = f"{pr.title}\n{pr.body[:600]}\n" + " ".join(c.qualname for c in changed[:8])
        seeds = [c.base_id for c in changed if c.base_id][:6]
        hits = retrieval.search(ev.snapshot_id, query, k=5, seeds=seeds, store=ev.store,
                                use_rerank=True)
        for h in hits:
            if ev.total_chars() > CONTEXT_BUDGET:
                break
            if h.path in pr_paths:
                continue
            ev.seen_chunks.add(h.chunk_id)
            ev.add("search", h.path, h.start_line, h.end_line,
                   numbered(ev.base_text(h.path) or h.text, h.start_line, h.end_line),
                   "; ".join(h.reasons[:2]) or "related code")


def _prompt(pr: PRInfo, files: list[PRFile], hunks: dict[str, list[Hunk]], ev: EvidenceStore,
            analyzer_items: list[dict], notes: list[str], draft: dict | None = None) -> str:
    commits = "\n".join(f"- {c['message'].splitlines()[0][:120]}" for c in pr.commits[:20])
    discussion = "\n".join(
        f"- {c.get('author')} on {c.get('path') or 'PR'}: {c['body'][:300]}"
        for c in (pr.review_comments + pr.issue_comments)[:12])
    diff_parts, used = [], 0
    for f in files:
        block = annotate_patch(f.path + (f" (renamed from {f.previous_path})"
                                         if f.previous_path else "") + f" [{f.status}]",
                               hunks[f.path])
        if used + len(block) > DIFF_BUDGET:
            diff_parts.append(f"--- {f.path}: diff omitted for length "
                              f"(+{f.additions} -{f.deletions})")
            continue
        diff_parts.append(block)
        used += len(block)
    analyzer = "\n".join(f"{a['path']}:{a['line']} {a['tool']} {a['rule']}: {a['message']}"
                         for a in analyzer_items) or "(no findings on changed lines)"
    parts = [
        f"<pr>\nRepository: {pr.repo}\nPR #{pr.number}: {pr.title}\nAuthor: {pr.author}\n"
        f"Base: {pr.base_ref} ({pr.base_sha[:10]})  Head: {pr.head_ref} ({pr.head_sha[:10]})\n"
        f"Description:\n{pr.body[:3000] or '(none)'}\n\nCommits:\n{commits}\n"
        f"\nExisting discussion:\n{discussion or '(none)'}\n</pr>",
        "<diff>\n" + "\n\n".join(diff_parts) + "\n</diff>",
        "\n".join(e.render() for e in ev.items),
        f"<analyzer>\n{analyzer}\n</analyzer>",
    ]
    if notes:
        parts.append("Notes: " + " ".join(notes))
    if draft is not None:
        parts.append(
            "Your previous draft is below. New evidence from your requests has been added "
            "above. Produce the final review now; only add requests if something essential "
            "is still missing.\n<draft>\n" + json.dumps(
                {k: draft.get(k) for k in ("summary", "findings")})[:12000] + "\n</draft>")
    parts.append("Return the review JSON now.")
    return "\n\n".join(parts)


def _validate_review(obj: dict) -> dict:
    for key in ("summary", "findings"):
        if key not in obj:
            raise ValueError(f"missing field {key}")
    obj.setdefault("walkthrough", [])
    obj.setdefault("impact", {"components": [], "risk": "medium", "risk_reason": ""})
    obj.setdefault("tests_assessment", "")
    obj.setdefault("requests", [])
    for f in obj["findings"]:
        for key in ("title", "path", "line_start", "explanation"):
            if key not in f:
                raise ValueError(f"finding missing {key}")
        f["line_start"] = int(f["line_start"])
        f["line_end"] = int(f.get("line_end") or f["line_start"])
        f.setdefault("side", "new")
        f.setdefault("evidence", [])
        f.setdefault("severity", "minor")
        f.setdefault("category", "bug")
        f.setdefault("confidence", "medium")
        f.setdefault("suggestion", None)
    return obj


def ground(findings: list[dict], files: list[PRFile], hunks: dict[str, list[Hunk]],
           head: dict[str, str], ev: EvidenceStore) -> tuple[list[dict], list[dict]]:
    """Deterministic grounding checks. Returns (kept, dropped)."""
    by_path = {f.path: f for f in files}
    kept, dropped = [], []
    for i, f in enumerate(findings, start=1):
        f["id"] = f"F{i}"
        path = f["path"].lstrip("./")
        f["path"] = path
        problems = []
        valid_ev = [e for e in f.get("evidence", []) if ev.get(e) is not None]
        f["evidence"] = valid_ev
        in_diff = path in by_path and in_hunks(hunks[path], f["line_start"], f.get("side", "new"))
        if path in by_path:
            text = head.get(path) if f["side"] == "new" else ev.base_text(
                by_path[path].previous_path or path)
            n_lines = len(text.splitlines()) if text else 0
            if n_lines and not (1 <= f["line_start"] <= n_lines):
                problems.append(f"line {f['line_start']} is outside the file ({n_lines} lines)")
        else:
            cited_paths = {ev.get(e).path for e in valid_ev}
            if path not in cited_paths and ev.base_text(path) is None:
                problems.append("points at a file that is neither in the PR nor in the evidence")
        if not in_diff and not valid_ev:
            problems.append("not on a changed line and cites no valid evidence")
        f["grounding"] = {"in_diff": in_diff, "evidence_ok": bool(valid_ev),
                          "problems": problems}
        (dropped if problems else kept).append(f)
    # Collapse duplicates: same path, overlapping lines, same category.
    unique: list[dict] = []
    for f in kept:
        dup = next((u for u in unique if u["path"] == f["path"] and u["category"] == f["category"]
                    and not (f["line_end"] < u["line_start"] or f["line_start"] > u["line_end"])),
                   None)
        if dup is None:
            unique.append(f)
        else:
            f["grounding"]["problems"].append(f"duplicate of {dup['id']}")
            dropped.append(f)
    return unique, dropped


def verify(findings: list[dict], files: list[PRFile], hunks: dict[str, list[Hunk]],
           ev: EvidenceStore) -> dict[str, dict]:
    if not findings:
        return {}
    blocks = []
    for f in findings:
        cited = "\n".join(ev.get(e).render() for e in f["evidence"] if ev.get(e))
        hunk_txt = ""
        if f["path"] in hunks:
            rel = [h for h in hunks[f["path"]] if in_hunks([h], f["line_start"], f["side"], 10)]
            hunk_txt = annotate_patch(f["path"], rel or hunks[f["path"]][:2])[:5000]
        blocks.append(
            f"<finding id=\"{f['id']}\">\n{json.dumps({k: f[k] for k in ('title', 'severity', 'category', 'path', 'line_start', 'line_end', 'side', 'explanation', 'suggestion')})}\n"
            f"<diff>\n{hunk_txt}\n</diff>\n{cited}\n</finding>")
    prompt = "\n\n".join(blocks) + "\n\nReturn verdicts for every finding id."
    obj, _ = complete_json("verifier", VERIFY_SYSTEM, prompt, VERIFY_SCHEMA)
    return {v["id"]: v for v in obj.get("verdicts", []) if "id" in v}


def to_markdown(result: dict) -> str:
    lines = [f"## Review of #{result['pr']['number']}: {result['pr']['title']}", "",
             result["summary"], ""]
    impact = result.get("impact") or {}
    if impact:
        lines += [f"**Risk:** {impact.get('risk', 'unknown')}. {impact.get('risk_reason', '')}",
                  ""]
    if result["findings"]:
        lines.append("### Findings")
        for f in result["findings"]:
            lines += ["", f"**{f['severity'].upper()}** `{f['path']}:{f['line_start']}` "
                          f"{f['title']}", "", f["explanation"]]
            if f.get("suggestion"):
                sug = f["suggestion"].strip()
                is_diff = any(ln.startswith(("+", "-")) for ln in sug.splitlines())
                lines += ["", "```diff" if is_diff else "```", sug, "```"]
    else:
        lines.append("No blocking issues found.")
    if result.get("tests_assessment"):
        lines += ["", "### Tests", result["tests_assessment"]]
    return "\n".join(lines)


def review_pr(url: str, progress: Progress | None = None) -> dict:
    emit = progress or (lambda stage, data: None)
    t0 = time.monotonic()
    timings: dict[str, float] = {}

    def lap(name: str, since: float) -> float:
        timings[name] = round(time.monotonic() - since, 2)
        return time.monotonic()

    full_name, number = parse_pr_url(url)
    gh = GitHub()
    with span("pr_review", "AGENT", input=url, repo=full_name, pr=number):
        t = time.monotonic()
        emit("fetch", {"repo": full_name, "pr": number})
        repo = gh.repo(full_name)
        if repo.size_kb > settings.max_repo_kb:
            raise GitHubError(f"Repository is {repo.size_kb // 1024} MB; the limit is "
                              f"{settings.max_repo_kb // 1024} MB.", 413)
        pr = gh.pull(full_name, number)
        files, notes = admit(pr)
        hunks = {f.path: parse_patch(f.patch) for f in files}
        emit("fetched", {"title": pr.title, "files": len(files), "additions": pr.additions,
                         "deletions": pr.deletions})
        t = lap("fetch", t)

        emit("index", {"sha": pr.base_sha[:10]})
        snap = index_snapshot(full_name, pr.base_sha, {
            "default_branch": repo.default_branch, "size_kb": repo.size_kb,
            "stars": repo.stars, "description": repo.description},
            progress=lambda s, d: emit(f"index.{s}", d))
        t = lap("index", t)

        rdir = gitops.repo_dir(full_name)
        with gitops.repo_lock(full_name):
            gitops.fetch_commit(rdir, f"pull/{number}/head")
            head = {}
            for f in files:
                if f.status != "removed":
                    text = gitops.show_file(rdir, pr.head_sha, f.path)
                    if text is not None:
                        head[f.path] = text
            # The evidence store reads base files from the working tree.
            gitops.checkout(rdir, pr.base_sha)
        t = lap("head", t)

        return review_change(pr, files, hunks, head, snap, rdir, notes, emit, timings, t0)


def review_change(pr: PRInfo, files: list[PRFile], hunks: dict[str, list[Hunk]],
                  head: dict[str, str], snap, rdir, notes: list[str], emit: Progress,
                  timings: dict[str, float] | None = None, t0: float | None = None) -> dict:
    """Review one change against an indexed base snapshot. Used for GitHub PRs and for the
    benchmark, which builds synthetic changes from reverted fixes."""
    timings = timings if timings is not None else {}
    t0 = t0 if t0 is not None else time.monotonic()
    costs: list[float] = []

    def lap(name: str, since: float) -> float:
        timings[name] = round(time.monotonic() - since, 2)
        return time.monotonic()

    t = time.monotonic()
    with span("review_change", "CHAIN", input=pr.title) as root:
        store = get_store()
        ev = EvidenceStore(snap.id, rdir, pr.base_sha, head, store=store)

        # Embed the neighbourhood of the change first so dense search covers it.
        emit("embed", {})
        _prioritize(snap.id, [f.previous_path or f.path for f in files])
        embed.embed_pending(snap.id, 96, store, time_budget_s=12, min_priority=5.0)
        t = lap("embed", t)

        emit("context", {})
        changed = _changed_symbols(ev, files, hunks, head)
        _build_context(ev, pr, files, changed, head)
        lines_by_path = {f.path: changed_new_lines(hunks[f.path]) for f in files}
        analyzer_items = analyzers.ruff({p: head[p] for p in head}, lines_by_path)
        for a in analyzer_items:
            ev.add("analyzer", a["path"], a["line"], a["line"],
                   f"{a['tool']} {a['rule']}: {a['message']}", "static analysis on a changed line",
                   source="head")
        emit("context_ready", {"changed_symbols": len(changed), "evidence": len(ev.items),
                               "chars": ev.total_chars()})
        t = lap("context", t)

        draft = None
        rounds = []
        for rnd in range(MAX_ROUNDS + 1):
            emit("review", {"round": rnd + 1, "model": role_label("reviewer")})
            prompt = _prompt(pr, files, hunks, ev, analyzer_items, notes, draft)
            with span(f"review.round{rnd + 1}", "CHAIN") as s:
                draft, res = complete_json("reviewer", REVIEW_SYSTEM, prompt, REVIEW_SCHEMA,
                                           _validate_review)
                if res.cost_usd:
                    costs.append(res.cost_usd)
                s.set("findings", len(draft["findings"]))
                s.set("requests", len(draft["requests"]))
            rounds.append({"round": rnd + 1, "findings": len(draft["findings"]),
                           "requests": draft["requests"][:MAX_REQUESTS],
                           "latency_ms": res.latency_ms, "prompt_chars": len(prompt)})
            if not draft["requests"] or rnd == MAX_ROUNDS:
                break
            new_ids = []
            for req in draft["requests"][:MAX_REQUESTS]:
                with span(f"tool.{req.get('tool')}", "TOOL", input=req.get("args")) as s:
                    items = ev.tool(req.get("tool", ""), req.get("args") or {})
                    s.set("evidence", [e.id for e in items])
                    new_ids += [e.id for e in items]
            rounds[-1]["new_evidence"] = new_ids
            emit("investigate", {"requests": draft["requests"][:MAX_REQUESTS],
                                 "new_evidence": len(new_ids)})
            if not new_ids:
                break
        t = lap("review", t)

        emit("verify", {"candidates": len(draft["findings"])})
        kept, dropped = ground(draft["findings"], files, hunks, head, ev)
        verdicts = verify(kept, files, hunks, ev) if kept else {}
        final, hidden = [], []
        for f in kept:
            v = verdicts.get(f["id"])
            f["verification"] = v or {"verdict": "uncertain", "reason": "no verdict returned"}
            if v and v["severity"] in SEVERITIES:
                f["severity_original"] = f["severity"]
                f["severity"] = v["severity"]
            if f["verification"]["verdict"] == "confirmed":
                final.append(f)
            else:
                hidden.append(f)
        for f in dropped:
            f["verification"] = {"verdict": "dropped", "reason": "; ".join(
                f["grounding"]["problems"])}
            hidden.append(f)
        order = {s: i for i, s in enumerate(SEVERITIES)}
        final.sort(key=lambda f: (order.get(f["severity"], 9), f["path"], f["line_start"]))
        t = lap("verify", t)

        result = {
            "kind": "pr_review",
            "pipeline": PIPELINE_VERSION,
            "pr": {"repo": pr.repo, "number": pr.number, "title": pr.title, "author": pr.author,
                   "url": pr.url, "state": "merged" if pr.merged else pr.state,
                   "base_sha": pr.base_sha, "head_sha": pr.head_sha,
                   "additions": pr.additions, "deletions": pr.deletions,
                   "files": [{"path": f.path, "status": f.status, "additions": f.additions,
                              "deletions": f.deletions} for f in files]},
            "summary": draft["summary"],
            "walkthrough": draft["walkthrough"],
            "impact": draft["impact"],
            "tests_assessment": draft["tests_assessment"],
            "findings": final,
            "hidden_findings": hidden,
            "changed_symbols": [{"path": c.path, "qualname": c.qualname, "kind": c.kind,
                                 "status": c.status, "lines": c.changed_lines}
                                for c in changed[:30]],
            "evidence": [e.brief() for e in ev.items],
            "evidence_text": {e.id: e.text for e in ev.items},
            "analyzer": analyzer_items,
            "rounds": rounds,
            "notes": notes,
            "models": {"reviewer": role_label("reviewer"), "verifier": role_label("verifier")},
            "stats": {"timings_s": timings, "total_s": round(time.monotonic() - t0, 1),
                      "cost_usd": round(sum(costs), 4) if costs else None,
                      "index": json.loads(db.get().execute(
                          "SELECT stats FROM snapshots WHERE id = ?",
                          (snap.id,)).fetchone()["stats"] or "{}"),
                      "dense_coverage": _dense_coverage(snap.id)},
        }
        result["markdown"] = to_markdown(result)
        root.output({"findings": len(final), "hidden": len(hidden)})
        emit("done", {"findings": len(final)})
        return result


def _prioritize(snapshot_id: int, paths: list[str]) -> None:
    """Raise embedding priority for changed files and their graph neighbours."""
    conn = db.get()
    q = ",".join("?" * len(paths))
    fids = [r["id"] for r in conn.execute(
        f"SELECT id FROM files WHERE snapshot_id = ? AND path IN ({q})", [snapshot_id, *paths])]
    if not fids:
        return
    fq = ",".join("?" * len(fids))
    neighbours = [r["fid"] for r in conn.execute(
        f"SELECT DISTINCT s2.file_id AS fid FROM symbols m JOIN edges e ON e.snapshot_id = ? "
        f"AND (e.src = m.id OR e.dst = m.id) AND e.kind IN ('imports', 'cochange') "
        f"JOIN symbols s2 ON s2.id = CASE WHEN e.src = m.id THEN e.dst ELSE e.src END "
        f"WHERE m.kind = 'module' AND m.file_id IN ({fq}) LIMIT 40", [snapshot_id, *fids])]
    with db.transaction(conn):
        conn.execute(f"UPDATE chunks SET priority = 10 WHERE file_id IN ({fq}) AND embedded = 0",
                     fids)
        if neighbours:
            nq = ",".join("?" * len(neighbours))
            conn.execute(f"UPDATE chunks SET priority = MAX(priority, 6) WHERE file_id IN ({nq}) "
                         f"AND embedded = 0", neighbours)


def _dense_coverage(snapshot_id: int) -> dict:
    r = db.get().execute("SELECT dense_done, (SELECT COUNT(*) FROM chunks WHERE snapshot_id = ?) "
                         "AS total FROM snapshots WHERE id = ?",
                         (snapshot_id, snapshot_id)).fetchone()
    return {"embedded": r["dense_done"], "chunks": r["total"]}

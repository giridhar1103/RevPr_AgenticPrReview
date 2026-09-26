"""Repository review: architecture map, hotspots, coupling, test gaps and hotspot review."""

from __future__ import annotations

import json
import math
import time
from typing import Callable

from .. import db, embed, gitops
from ..config import settings
from ..github import GitHub, GitHubError, parse_repo_url
from ..indexer import index_snapshot
from ..llm.client import complete_json, role_label
from ..tracing import span
from ..vectorstore import get_store
from .diffparse import numbered
from .evidence import EvidenceStore
from .pr_review import SEVERITIES, verify
from .prompts import HOTSPOT_SCHEMA, HOTSPOT_SYSTEM, UNTRUSTED

PIPELINE_VERSION = "repo-1"
HOTSPOT_REVIEWS = 3
MAX_FILE_CHARS = 36_000

Progress = Callable[[str, dict], None]

ARCH_SYSTEM = f"""You are onboarding onto an unfamiliar repository. From the repository map
(most central files by PageRank over the import and call graph, with their main symbols), the
README and the statistics, describe the architecture for a new engineer.
{UNTRUSTED}
Be specific: name real directories, files and symbols from the input. Do not invent components
that are not shown. Reply with JSON only."""

ARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "components": {"type": "array", "items": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "paths": {"type": "array",
                                                                  "items": {"type": "string"}},
                           "role": {"type": "string"}},
            "required": ["name", "paths", "role"]}},
        "entry_points": {"type": "array", "items": {"type": "string"}},
        "data_flow": {"type": "string"},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "components", "entry_points", "data_flow", "notes"],
}


def _norm(values: dict[int, float]) -> dict[int, float]:
    if not values:
        return {}
    hi = max(values.values()) or 1.0
    return {k: v / hi for k, v in values.items()}


def hotspots(snapshot_id: int, limit: int = 12) -> list[dict]:
    rows = db.get().execute(
        "SELECT id, path, lang, loc, complexity, churn, churn_recent, authors, last_commit_at, "
        "pagerank FROM files WHERE snapshot_id = ? AND is_test = 0 AND complexity > 0",
        (snapshot_id,)).fetchall()
    churn = _norm({r["id"]: math.log1p(r["churn"] + 2 * r["churn_recent"]) for r in rows})
    cx = _norm({r["id"]: math.log1p(r["complexity"]) for r in rows})
    scored = []
    for r in rows:
        score = churn.get(r["id"], 0) * cx.get(r["id"], 0)
        if score > 0:
            scored.append({"path": r["path"], "lang": r["lang"], "loc": r["loc"],
                           "complexity": r["complexity"], "churn": r["churn"],
                           "churn_recent": r["churn_recent"], "authors": r["authors"],
                           "last_commit_at": r["last_commit_at"],
                           "centrality": round(r["pagerank"], 3), "score": round(score, 3)})
    scored.sort(key=lambda x: -x["score"])
    return scored[:limit]


def hidden_coupling(snapshot_id: int, limit: int = 10) -> list[dict]:
    """File pairs that change together often but have no import edge between them."""
    rows = db.get().execute(
        "SELECT f1.path AS a, f2.path AS b, e.weight, e.line AS n FROM edges e "
        "JOIN symbols m1 ON m1.id = e.src JOIN symbols m2 ON m2.id = e.dst "
        "JOIN files f1 ON f1.id = m1.file_id JOIN files f2 ON f2.id = m2.file_id "
        "WHERE e.snapshot_id = ? AND e.kind = 'cochange' AND e.src < e.dst AND e.line >= 4 "
        "AND f1.is_test = 0 AND f2.is_test = 0 AND f1.lang = f2.lang "
        "AND EXISTS (SELECT 1 FROM symbols x WHERE x.file_id = f1.id AND x.kind != 'module') "
        "AND NOT EXISTS (SELECT 1 FROM edges i WHERE i.snapshot_id = e.snapshot_id "
        "AND i.kind = 'imports' AND ((i.src = e.src AND i.dst = e.dst) OR "
        "(i.src = e.dst AND i.dst = e.src))) ORDER BY e.weight * e.line DESC LIMIT ?",
        (snapshot_id, limit)).fetchall()
    return [{"a": r["a"], "b": r["b"], "commits": r["n"], "coupling": r["weight"]}
            for r in rows]


def _reached_by_tests(snapshot_id: int, depth: int = 3) -> set[int]:
    """Symbols reachable from test code within `depth` resolved calls."""
    conn = db.get()
    frontier = {r["dst"] for r in conn.execute(
        "SELECT dst FROM edges WHERE snapshot_id = ? AND kind = 'tests' AND weight >= 0.6",
        (snapshot_id,))}
    calls: dict[int, list[int]] = {}
    for r in conn.execute("SELECT src, dst FROM edges WHERE snapshot_id = ? AND kind = 'calls' "
                          "AND weight >= 0.6", (snapshot_id,)):
        calls.setdefault(r["src"], []).append(r["dst"])
    # Methods and functions defined inside a tested class count as reached through it.
    reached = set(frontier)
    for _ in range(depth):
        nxt = {d for s in frontier for d in calls.get(s, ())} - reached
        reached |= nxt
        frontier = nxt
    return reached


def test_gaps(snapshot_id: int, limit: int = 12) -> list[dict]:
    """Widely used symbols that no test reaches, directly or within three calls."""
    reached = _reached_by_tests(snapshot_id)
    rows = db.get().execute(
        "SELECT s.id, s.qualname, s.kind, s.start_line, f.path, COUNT(DISTINCT e.src) AS callers "
        "FROM symbols s JOIN files f ON f.id = s.file_id "
        "JOIN edges e ON e.snapshot_id = s.snapshot_id AND e.kind = 'calls' AND e.dst = s.id "
        "AND e.weight >= 0.6 "
        "WHERE s.snapshot_id = ? AND f.is_test = 0 AND s.kind IN ('function', 'method', 'class') "
        "AND s.name NOT LIKE '\\_%' ESCAPE '\\' "
        "AND NOT EXISTS (SELECT 1 FROM edges t WHERE t.snapshot_id = s.snapshot_id "
        "AND t.kind = 'tests' AND t.dst = s.id) "
        "AND NOT EXISTS (SELECT 1 FROM edges t JOIN symbols m ON m.id = t.dst "
        "WHERE t.snapshot_id = s.snapshot_id AND t.kind = 'tests_file' AND m.file_id = s.file_id) "
        "GROUP BY s.id HAVING callers >= 3 ORDER BY callers DESC LIMIT ?",
        (snapshot_id, limit * 4)).fetchall()
    return [{"symbol": r["qualname"], "kind": r["kind"], "path": r["path"],
             "line": r["start_line"], "callers": r["callers"]}
            for r in rows if r["id"] not in reached][:limit]


def repo_map(snapshot_id: int, files: int = 18, per_file: int = 6) -> str:
    conn = db.get()
    top = conn.execute(
        "SELECT id, path, loc FROM files WHERE snapshot_id = ? AND is_test = 0 "
        "ORDER BY pagerank DESC LIMIT ?", (snapshot_id, files)).fetchall()
    out = []
    for f in top:
        syms = conn.execute(
            "SELECT s.kind, s.signature FROM symbols s LEFT JOIN edges e ON e.snapshot_id = "
            "s.snapshot_id AND e.kind = 'calls' AND e.dst = s.id WHERE s.file_id = ? "
            "AND s.kind != 'module' GROUP BY s.id ORDER BY COUNT(e.src) DESC, s.start_line "
            "LIMIT ?", (f["id"], per_file)).fetchall()
        out.append(f"{f['path']} ({f['loc']} lines)")
        out += [f"    {s['signature'][:150]}" for s in syms if s["signature"]]
    return "\n".join(out)


def _readme(snapshot_id: int) -> str:
    row = db.get().execute(
        "SELECT c.text FROM chunks c JOIN files f ON f.id = c.file_id WHERE c.snapshot_id = ? "
        "AND lower(f.path) IN ('readme.md', 'readme.rst', 'readme') ORDER BY c.start_line "
        "LIMIT 1", (snapshot_id,)).fetchone()
    return row["text"][:3000] if row else "(no README)"


def _review_hotspot(ev: EvidenceStore, hs: dict) -> list[dict]:
    text = ev.base_text(hs["path"]) or ""
    lines = text.splitlines()
    end = len(lines)
    # Very long files: review the densest region around the most-called symbols.
    rendered = numbered(text, 1, end)
    start = 1
    if len(rendered) > MAX_FILE_CHARS:
        row = db.get().execute(
            "SELECT s.start_line FROM symbols s JOIN files f ON f.id = s.file_id "
            "LEFT JOIN edges e ON e.snapshot_id = s.snapshot_id AND e.kind = 'calls' "
            "AND e.dst = s.id WHERE f.snapshot_id = ? AND f.path = ? AND s.kind != 'module' "
            "GROUP BY s.id ORDER BY COUNT(e.src) DESC LIMIT 1",
            (ev.snapshot_id, hs["path"])).fetchone()
        center = row["start_line"] if row else 1
        span_lines = MAX_FILE_CHARS // 60
        start = max(1, center - span_lines // 4)
        end = min(len(lines), start + span_lines)
        rendered = numbered(text, start, end)
    base = ev.add("file", hs["path"], start, end, rendered, "hotspot under review",
                  max_chars=MAX_FILE_CHARS)
    conn = db.get()
    top_syms = conn.execute(
        "SELECT s.id, s.qualname FROM symbols s JOIN files f ON f.id = s.file_id "
        "LEFT JOIN edges e ON e.snapshot_id = s.snapshot_id AND e.kind = 'calls' AND e.dst = s.id "
        "WHERE f.snapshot_id = ? AND f.path = ? AND s.kind != 'module' AND s.start_line "
        "BETWEEN ? AND ? GROUP BY s.id ORDER BY COUNT(e.src) DESC LIMIT 4",
        (ev.snapshot_id, hs["path"], start, end)).fetchall()
    for s in top_syms:
        for nb in ev.neighbours(s["id"], "calls", "in", limit=2):
            if nb["path"] != hs["path"]:
                ev.add_symbol(nb, "caller", f"calls {s['qualname']}", max_lines=25)
    prompt = (f"Hotspot: {hs['path']} (churn {hs['churn']} commits, complexity "
              f"{hs['complexity']}, {hs['authors']} authors)\n\n" +
              "\n".join(e.render() for e in ev.items) + "\n\nReview this file.")
    obj, _ = complete_json("reviewer", HOTSPOT_SYSTEM, prompt, HOTSPOT_SCHEMA)
    findings = []
    for f in obj.get("findings", []):
        try:
            f["line_start"] = int(f["line_start"])
            f["line_end"] = int(f.get("line_end") or f["line_start"])
        except (KeyError, TypeError, ValueError):
            continue
        f["path"] = hs["path"]
        f.setdefault("side", "new")
        f.setdefault("suggestion", None)
        if not (start <= f["line_start"] <= end):
            continue
        # The verifier sees a window around the finding instead of the whole file.
        lo, hi = max(start, f["line_start"] - 25), min(end, f["line_end"] + 25)
        win = ev.add("read", hs["path"], lo, hi, numbered(text, lo, hi),
                     "code around the finding", dedupe=False, max_chars=6000)
        f["evidence"] = [win.id] + [e for e in f.get("evidence", [])
                                    if ev.get(e) and e != base.id]
        findings.append(f)
    hs["role"] = obj.get("role", "")
    return findings


def review_repo(url: str, progress: Progress | None = None) -> dict:
    emit = progress or (lambda stage, data: None)
    t0 = time.monotonic()
    full_name = parse_repo_url(url)
    gh = GitHub()
    with span("repo_review", "AGENT", input=url, repo=full_name) as root:
        emit("fetch", {"repo": full_name})
        repo = gh.repo(full_name)
        if repo.size_kb > settings.max_repo_kb:
            raise GitHubError(f"Repository is {repo.size_kb // 1024} MB; the limit is "
                              f"{settings.max_repo_kb // 1024} MB.", 413)
        snap = index_snapshot(full_name, repo.head_sha, {
            "default_branch": repo.default_branch, "size_kb": repo.size_kb,
            "stars": repo.stars, "description": repo.description},
            progress=lambda s, d: emit(f"index.{s}", d))
        store = get_store()
        emit("embed", {})
        embed.embed_pending(snap.id, 64, store, time_budget_s=12)

        emit("analyze", {})
        hot = hotspots(snap.id)
        coupling = hidden_coupling(snap.id)
        gaps = test_gaps(snap.id)
        stats = json.loads(db.get().execute("SELECT stats FROM snapshots WHERE id = ?",
                                            (snap.id,)).fetchone()["stats"])

        emit("architecture", {"model": role_label("reviewer")})
        rmap = repo_map(snap.id)
        arch, _ = complete_json(
            "reviewer", ARCH_SYSTEM,
            f"<pr>\nRepository: {full_name}\nDescription: {repo.description}\n"
            f"Languages (lines): {stats.get('languages')}\n</pr>\n"
            f"<evidence id=\"README\">\n{_readme(snap.id)}\n</evidence>\n"
            f"<evidence id=\"MAP\">\n{rmap}\n</evidence>", ARCH_SCHEMA)

        rdir = gitops.repo_dir(full_name)
        findings: list[dict] = []
        reviewed = []
        with gitops.repo_lock(full_name):
            gitops.checkout(rdir, repo.head_sha)
            for i, hs in enumerate(hot[:HOTSPOT_REVIEWS]):
                emit("hotspot", {"path": hs["path"], "n": i + 1})
                ev = EvidenceStore(snap.id, rdir, repo.head_sha, store=store)
                with span("hotspot_review", "CHAIN", input=hs["path"]):
                    cand = _review_hotspot(ev, hs)
                    for j, f in enumerate(cand, start=1):
                        f["id"] = f"H{i + 1}.{j}"
                    verdicts = verify(cand, [], {}, ev) if cand else {}
                for f in cand:
                    v = verdicts.get(f["id"]) or {"verdict": "uncertain",
                                                  "reason": "no verdict returned"}
                    f["verification"] = v
                    if v.get("severity") in SEVERITIES:
                        f["severity"] = v["severity"]
                    f["evidence_text"] = {e: ev.get(e).text[:2500] for e in f["evidence"]
                                          if ev.get(e) and ev.get(e).kind != "file"}
                    findings.append(f)
                reviewed.append({"path": hs["path"], "role": hs.get("role", ""),
                                 "candidates": len(cand)})

        confirmed = [f for f in findings if f["verification"]["verdict"] == "confirmed"]
        hidden = [f for f in findings if f["verification"]["verdict"] != "confirmed"]
        order = {s: i for i, s in enumerate(SEVERITIES)}
        confirmed.sort(key=lambda f: order.get(f["severity"], 9))
        result = {
            "kind": "repo_review",
            "pipeline": PIPELINE_VERSION,
            "repo": {"full_name": full_name, "sha": repo.head_sha, "stars": repo.stars,
                     "description": repo.description, "default_branch": repo.default_branch,
                     "url": f"https://github.com/{full_name}"},
            "snapshot_id": snap.id,
            "architecture": arch,
            "repo_map": rmap,
            "hotspots": hot,
            "coupling": coupling,
            "test_gaps": gaps,
            "reviewed_hotspots": reviewed,
            "findings": confirmed,
            "hidden_findings": hidden,
            "models": {"reviewer": role_label("reviewer"), "verifier": role_label("verifier")},
            "stats": {"index": stats, "total_s": round(time.monotonic() - t0, 1),
                      "dense_coverage": {"embedded": db.get().execute(
                          "SELECT dense_done FROM snapshots WHERE id = ?",
                          (snap.id,)).fetchone()[0], "chunks": stats.get("chunks")}},
        }
        root.output({"findings": len(confirmed), "hotspots": len(hot)})
        emit("done", {"findings": len(confirmed)})
        return result

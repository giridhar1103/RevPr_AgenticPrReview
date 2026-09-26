"""Code graph construction from parsed files (ADR 0006).

Nodes are symbols; every file also has a `module` symbol so file-level edges (imports,
co-change) live in the same table. Reference edges carry a confidence weight describing how the
name was resolved.
"""

from __future__ import annotations

import posixpath
from collections import defaultdict
from dataclasses import dataclass, field

from .identifiers import STOP_NAMES
from .parsing import Import, ParsedFile

# Resolution confidence by strategy.
CONF_QUALIFIED_IMPORT = 0.95
CONF_EXPLICIT_IMPORT = 0.95
CONF_SAME_FILE = 0.9
CONF_IMPORTED_FILE = 0.8
CONF_GLOBAL_UNIQUE = 0.6
CONF_GLOBAL_AMBIGUOUS = 0.3
MAX_AMBIGUOUS = 4

_JS_EXTS = ("", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".d.ts",
            "/index.ts", "/index.tsx", "/index.js", "/index.jsx")


@dataclass
class FileImports:
    files: set[int] = field(default_factory=set)            # imported file indexes
    names: dict[str, tuple[int, str]] = field(default_factory=dict)  # alias -> (file, name)
    modules: dict[str, set[int]] = field(default_factory=dict)       # alias -> files
    external: set[str] = field(default_factory=set)  # names bound by imports outside the repo


class Resolver:
    def __init__(self, files: list[ParsedFile]):
        self.files = files
        self.by_path = {f.path: i for i, f in enumerate(files)}
        self.py_modules: dict[str, int] = {}
        self.suffix: dict[str, list[int]] = defaultdict(list)
        self.dirs: dict[str, list[int]] = defaultdict(list)
        for i, f in enumerate(files):
            self.dirs[posixpath.dirname(f.path)].append(i)
            parts = f.path.split("/")
            for k in range(1, min(len(parts), 4) + 1):
                self.suffix["/".join(parts[-k:])].append(i)
            if f.path.endswith(".py"):
                mod = f.path[:-3].replace("/", ".")
                if mod.endswith(".__init__"):
                    mod = mod[: -len(".__init__")]
                for prefix in ("", "src.", "lib.", "python."):
                    if mod.startswith(prefix):
                        self.py_modules.setdefault(mod[len(prefix):], i)
                self.py_modules.setdefault(mod, i)

    # -- imports -------------------------------------------------------------------------
    def _py_module(self, importer: str, module: str) -> str:
        if not module.startswith("."):
            return module
        level = len(module) - len(module.lstrip("."))
        pkg = posixpath.dirname(importer).split("/") if posixpath.dirname(importer) else []
        base = pkg[: len(pkg) - (level - 1)] if level > 1 else pkg
        rest = module.lstrip(".")
        return ".".join([*base, rest] if rest else base)

    def _resolve_module(self, fi: int, imp: Import) -> list[int]:
        f = self.files[fi]
        lang = f.lang
        mod = imp.module
        if lang == "python":
            full = self._py_module(f.path, mod)
            hit = self.py_modules.get(full)
            return [hit] if hit is not None else []
        if lang in ("javascript", "typescript", "tsx"):
            if mod.startswith("."):
                base = posixpath.normpath(posixpath.join(posixpath.dirname(f.path), mod))
            elif mod.startswith(("@/", "~/")):
                base = "src/" + mod[2:]
            else:
                return []
            stem = base[:-3] if base.endswith((".js", ".jsx")) else base
            for cand in (base, stem):
                for ext in _JS_EXTS:
                    hit = self.by_path.get(cand + ext)
                    if hit is not None:
                        return [hit]
            return []
        if lang == "go":
            parts = mod.split("/")
            for k in range(min(len(parts), 4), 0, -1):
                suffix = "/".join(parts[-k:])
                for d, idxs in self.dirs.items():
                    if d == suffix or d.endswith("/" + suffix):
                        return [i for i in idxs if self.files[i].lang == "go"][:30]
            return []
        if lang == "java" or lang == "kotlin" or lang == "scala":
            path = mod.replace(".", "/")
            for ext in (".java", ".kt", ".scala"):
                hits = self.suffix.get("/".join((path + ext).split("/")[-3:]), [])
                if hits:
                    return hits[:1]
            return []
        if lang in ("c", "cpp"):
            local = posixpath.normpath(posixpath.join(posixpath.dirname(f.path), mod))
            if local in self.by_path:
                return [self.by_path[local]]
            return self.suffix.get("/".join(mod.split("/")[-2:]), [])[:1]
        if lang == "rust":
            segs = [s for s in mod.replace("{", " ").split("::") if s.strip()]
            if segs and segs[0] in ("crate", "self", "super"):
                segs = segs[1:]
            for k in range(len(segs), 0, -1):
                stem = "/".join(s.strip() for s in segs[:k])
                for cand in (f"src/{stem}.rs", f"src/{stem}/mod.rs", f"{stem}.rs"):
                    hits = self.suffix.get("/".join(cand.split("/")[-3:]), [])
                    if hits:
                        return hits[:1]
            return []
        return []

    def imports_for(self, fi: int) -> FileImports:
        fimp = FileImports()
        f = self.files[fi]
        for imp in f.imports:
            targets = self._resolve_module(fi, imp)
            resolved_subs: set[str] = set()
            if f.lang == "python" and imp.names:
                # `from pkg import submodule` resolves to the submodule file.
                full = self._py_module(f.path, imp.module)
                for name, alias in imp.names:
                    sub = self.py_modules.get(f"{full}.{name}" if full else name)
                    if sub is not None:
                        fimp.files.add(sub)
                        fimp.modules.setdefault(alias, set()).add(sub)
                        resolved_subs.add(alias)
                    elif targets:
                        fimp.names[alias] = (targets[0], name)
            else:
                for name, alias in imp.names:
                    if targets and name != "default":
                        fimp.names[alias] = (targets[0], name)
                    elif targets:
                        fimp.modules.setdefault(alias, set()).update(targets)
            if not targets:
                # Imported from outside the repository: these local names must never be
                # resolved to an in-repo definition that happens to share the name.
                fimp.external.update(alias for _, alias in imp.names
                                     if alias not in resolved_subs)
                if imp.alias:
                    fimp.external.add(imp.alias)
            fimp.files.update(targets)
            if imp.alias and targets:
                fimp.modules.setdefault(imp.alias, set()).update(targets)
        fimp.files.discard(fi)
        return fimp


@dataclass
class GraphEdges:
    # (kind, src_file, src_symbol_index | None, dst_file, dst_symbol_index | None, weight, line)
    edges: list[tuple[str, int, int | None, int, int | None, float, int | None]]


def build_edges(files: list[ParsedFile], is_test: list[bool]) -> GraphEdges:
    res = Resolver(files)
    defs: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for fi, f in enumerate(files):
        for si, s in enumerate(f.symbols):
            defs[s.name].append((fi, si))

    out: list[tuple[str, int, int | None, int, int | None, float, int | None]] = []
    for fi, f in enumerate(files):
        if not f.symbols and not f.refs and not f.imports:
            continue
        fimp = res.imports_for(fi)
        for tgt in fimp.files:
            out.append(("imports", fi, None, tgt, None, 1.0, None))

        seen: set[tuple[int | None, int, int]] = set()
        for ref in f.refs:
            name = ref.name
            if name in STOP_NAMES or len(name) < 2:
                continue
            qual_head = (ref.qualifier or "").split(".")[0].split("(")[0].strip()
            if (not ref.qualifier and name in fimp.external) or qual_head in fimp.external:
                continue
            cands: list[tuple[int, int]] = []
            conf = 0.0
            qual_root = (ref.qualifier or "").split(".")[0].split("(")[0].strip()
            if qual_root and qual_root in fimp.modules:
                cands = [(tf, si) for tf, si in defs.get(name, []) if tf in fimp.modules[qual_root]]
                conf = CONF_QUALIFIED_IMPORT
            if not cands and name in fimp.names:
                tf, orig = fimp.names[name]
                cands = [(t, si) for t, si in defs.get(orig, []) if t == tf]
                conf = CONF_EXPLICIT_IMPORT
            if not cands:
                same = [(t, si) for t, si in defs.get(name, []) if t == fi]
                if same:
                    cands, conf = same, CONF_SAME_FILE
            if not cands:
                imported = [(t, si) for t, si in defs.get(name, []) if t in fimp.files]
                if imported:
                    cands, conf = imported, CONF_IMPORTED_FILE
            if not cands:
                glob = defs.get(name, [])
                if len(glob) == 1:
                    cands, conf = glob, CONF_GLOBAL_UNIQUE
                elif 1 < len(glob) <= MAX_AMBIGUOUS:
                    cands, conf = glob, CONF_GLOBAL_AMBIGUOUS
            for tf, si in cands[:MAX_AMBIGUOUS]:
                if tf == fi and ref.scope == si:
                    continue  # recursion
                key = (ref.scope, tf, si)
                if key in seen:
                    continue
                seen.add(key)
                kind = "inherits" if ref.kind == "inherits" else "calls"
                if is_test[fi] and not is_test[tf]:
                    kind = "tests"
                out.append((kind, fi, ref.scope, tf, si, conf, ref.line))

        # Test files that import a module test that module even without a resolved call.
        if is_test[fi]:
            for tgt in fimp.files:
                if not is_test[tgt]:
                    out.append(("tests_file", fi, None, tgt, None, 0.7, None))
    return GraphEdges(out)


def pagerank(n: int, edges: list[tuple[int, int, float]], damping: float = 0.85,
             iters: int = 40, personalization: dict[int, float] | None = None) -> list[float]:
    """Weighted PageRank over n nodes; edges are (src, dst, weight)."""
    if n == 0:
        return []
    out_w = [0.0] * n
    adj: list[list[tuple[int, float]]] = [[] for _ in range(n)]
    for s, d, w in edges:
        if s == d:
            continue
        adj[s].append((d, w))
        out_w[s] += w
    if personalization:
        total = sum(personalization.values()) or 1.0
        base = [personalization.get(i, 0.0) / total for i in range(n)]
    else:
        base = [1.0 / n] * n
    rank = base[:]
    for _ in range(iters):
        nxt = [(1 - damping) * b for b in base]
        dangling = sum(rank[i] for i in range(n) if out_w[i] == 0)
        for i in range(n):
            if out_w[i] == 0:
                continue
            share = damping * rank[i] / out_w[i]
            for d, w in adj[i]:
                nxt[d] += share * w
        for i in range(n):
            nxt[i] += damping * dangling * base[i]
        rank = nxt
    return rank

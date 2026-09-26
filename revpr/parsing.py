"""Tree-sitter parsing: symbols, references, imports, complexity and AST-aligned chunks."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from functools import lru_cache

import tree_sitter_language_pack as tslp

from .config import settings
from .langs import GRAMMAR, LANGS, LangSpec

_NAME_TYPES = {
    "identifier", "property_identifier", "field_identifier", "type_identifier", "constant",
    "name", "simple_identifier", "package_identifier", "private_property_identifier",
    "shorthand_property_identifier", "operator_name", "destructor_name",
}
_MEMBER_TYPES = {
    "attribute", "member_expression", "selector_expression", "field_expression",
    "scoped_identifier", "navigation_expression", "qualified_identifier",
    "scoped_type_identifier", "member_access_expression", "generic_name", "generic_type",
    "call", "call_expression", "template_function", "optional_chain",
}
_FUNC_VALUES = {"arrow_function", "function_expression", "function", "generator_function"}


@dataclass
class Symbol:
    name: str
    qualname: str
    kind: str
    start_line: int  # 1-based inclusive
    end_line: int
    signature: str
    parent: int | None  # index into ParsedFile.symbols


@dataclass
class Ref:
    name: str
    qualifier: str | None
    line: int
    kind: str  # call, inherits, decorator
    scope: int | None  # index of enclosing symbol


@dataclass
class Import:
    module: str
    names: list[tuple[str, str]]  # (imported name, local alias)
    alias: str | None  # local alias for the module itself
    line: int


@dataclass
class Chunk:
    start_line: int
    end_line: int
    symbol: int | None
    header: str
    text: str
    card: str

    @property
    def card_hash(self) -> str:
        return hashlib.blake2b(self.card.encode(), digest_size=16).hexdigest()


@dataclass
class ParsedFile:
    path: str
    lang: str | None
    loc: int
    complexity: int = 0
    symbols: list[Symbol] = field(default_factory=list)
    refs: list[Ref] = field(default_factory=list)
    imports: list[Import] = field(default_factory=list)
    chunks: list[Chunk] = field(default_factory=list)


@lru_cache(maxsize=None)
def _parser(lang: str):
    return tslp.get_parser(GRAMMAR.get(lang, lang))


def _text(node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", "replace")


def _reduce_name(node, src: bytes) -> tuple[str | None, str | None]:
    """Reduce a callee expression to (name, qualifier)."""
    depth = 0
    while node is not None and depth < 8:
        depth += 1
        if node.type in _NAME_TYPES:
            return _text(node, src), None
        if node.type in _MEMBER_TYPES:
            for f in ("attribute", "property", "field", "name", "function"):
                child = node.child_by_field_name(f)
                if child is not None:
                    if f == "function":  # nested call such as a()() or decorator call
                        node = child
                        break
                    name, _ = _reduce_name(child, src)
                    obj = (node.child_by_field_name("object")
                           or node.child_by_field_name("operand")
                           or node.child_by_field_name("path")
                           or node.child_by_field_name("scope")
                           or node.child_by_field_name("expression"))
                    qual = _text(obj, src)[:80] if obj is not None else None
                    return name, qual
            else:
                named = [c for c in node.named_children]
                if not named:
                    return None, None
                node = named[-1]
            continue
        named = node.named_children
        if not named:
            return None, None
        node = named[0]
    return None, None


def _def_name(node, src: bytes) -> str | None:
    n = node.child_by_field_name("name")
    if n is not None:
        name, _ = _reduce_name(n, src)
        return name
    d = node.child_by_field_name("declarator")
    depth = 0
    while d is not None and depth < 8:
        depth += 1
        if d.type in _NAME_TYPES:
            return _text(d, src)
        if d.type in ("qualified_identifier", "scoped_identifier"):
            name, _ = _reduce_name(d, src)
            return name
        nxt = d.child_by_field_name("declarator") or d.child_by_field_name("name")
        if nxt is None:
            nxt = next((c for c in d.named_children if c.type in _NAME_TYPES), None)
        d = nxt
    if node.type == "impl_item":
        t = node.child_by_field_name("type")
        return _text(t, src) if t is not None else None
    return None


def _signature(node, src: bytes, lang: str) -> str:
    body = node.child_by_field_name("body")
    end = body.start_byte if body is not None else node.end_byte
    sig = src[node.start_byte:end].decode("utf-8", "replace")
    sig = " ".join(sig.split())
    return sig.rstrip(" :{")[:240]


def _docstring(node, src: bytes, lang: str) -> str:
    if lang == "python":
        body = node.child_by_field_name("body")
        if body is not None and body.named_children:
            first = body.named_children[0]
            if first.type == "expression_statement" and first.named_children \
                    and first.named_children[0].type == "string":
                return _text(first.named_children[0], src).strip("\"' \n")[:300]
        return ""
    prev = node.prev_named_sibling
    if prev is not None and prev.type in ("comment", "line_comment", "block_comment") \
            and node.start_point[0] - prev.end_point[0] <= 1:
        return _text(prev, src).strip("/*# \n")[:300]
    return ""


def _parse_import(node, src: bytes, lang: str) -> Import | None:
    line = node.start_point[0] + 1
    if lang == "python":
        if node.type == "import_statement":
            # import a.b as c, d
            for child in node.named_children:
                if child.type == "aliased_import":
                    mod = _text(child.child_by_field_name("name"), src)
                    alias = _text(child.child_by_field_name("alias"), src)
                    return Import(mod, [], alias, line)
                if child.type == "dotted_name":
                    mod = _text(child, src)
                    return Import(mod, [], mod.split(".")[0], line)
            return None
        mod_node = node.child_by_field_name("module_name")
        mod = _text(mod_node, src) if mod_node is not None else ""
        names: list[tuple[str, str]] = []
        for child in node.named_children:
            if child == mod_node:
                continue
            if child.type == "aliased_import":
                n = _text(child.child_by_field_name("name"), src)
                a = _text(child.child_by_field_name("alias"), src)
                names.append((n, a))
            elif child.type == "dotted_name":
                n = _text(child, src)
                names.append((n, n.split(".")[-1]))
        return Import(mod, names, None, line)

    if lang in ("javascript", "typescript", "tsx"):
        source = node.child_by_field_name("source")
        if source is None:
            return None
        mod = _text(source, src).strip("'\"`")
        names = []
        alias = None
        for clause in node.named_children:
            if clause.type != "import_clause":
                continue
            for c in clause.named_children:
                if c.type == "identifier":
                    names.append(("default", _text(c, src)))
                elif c.type == "namespace_import":
                    ident = next((x for x in c.named_children if x.type == "identifier"), None)
                    alias = _text(ident, src) if ident is not None else None
                elif c.type == "named_imports":
                    for spec in c.named_children:
                        if spec.type == "import_specifier":
                            n = spec.child_by_field_name("name")
                            a = spec.child_by_field_name("alias")
                            nt = _text(n, src) if n is not None else ""
                            names.append((nt, _text(a, src) if a is not None else nt))
        return Import(mod, names, alias, line)

    if lang == "go":
        path = node.child_by_field_name("path")
        if path is None:
            return None
        mod = _text(path, src).strip('"`')
        name = node.child_by_field_name("name")
        alias = _text(name, src) if name is not None else mod.rsplit("/", 1)[-1]
        return Import(mod, [], alias, line)

    if lang in ("c", "cpp"):
        path = node.child_by_field_name("path")
        if path is None:
            return None
        return Import(_text(path, src).strip('"<>'), [], None, line)

    raw = " ".join(_text(node, src).split())
    raw = re.sub(r"^(import|use|using|namespace\s+use)\s+(static\s+)?", "", raw).rstrip(";")
    last = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", raw.split("{")[-1])
    names = [(n, n) for n in last[-6:]] if "{" in raw else ([(last[-1], last[-1])] if last else [])
    return Import(raw[:200], names, None, line)


def _is_func_declarator(node) -> bool:
    value = node.child_by_field_name("value")
    return value is not None and value.type in _FUNC_VALUES


def parse_source(path: str, src: bytes, lang: str | None, parsed: bool) -> ParsedFile:
    text = src.decode("utf-8", "replace")
    loc = text.count("\n") + (0 if text.endswith("\n") else 1)
    pf = ParsedFile(path, lang, loc)
    spec = LANGS.get(lang) if parsed and lang else None
    if spec is None:
        pf.chunks = _chunk_lines(path, text)
        return pf

    try:
        tree = _parser(spec.name).parse(src)
    except Exception:  # grammar failure: fall back to text chunking
        pf.chunks = _chunk_lines(path, text)
        return pf

    _walk(tree.root_node, src, spec, pf)
    pf.chunks = _chunk_tree(tree.root_node, src, pf, spec)
    return pf


def _walk(root, src: bytes, spec: LangSpec, pf: ParsedFile) -> None:
    lang = spec.name
    # Iterative DFS carrying the enclosing symbol index and qualname prefix.
    stack: list[tuple[object, int | None, str]] = [(root, None, "")]
    while stack:
        node, scope, prefix = stack.pop()
        t = node.type
        new_scope, new_prefix = scope, prefix

        if t in spec.defs and not (t == "variable_declarator" and not _is_func_declarator(node)):
            name = _def_name(node, src)
            if name:
                kind = spec.defs[t]
                parent_kind = pf.symbols[scope].kind if scope is not None else None
                if kind == "function" and parent_kind in ("class", "interface"):
                    kind = "method"
                qual = f"{prefix}.{name}" if prefix else name
                if lang == "go" and t == "method_declaration":
                    recv = node.child_by_field_name("receiver")
                    rt = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", _text(recv, src)) if recv else []
                    if rt:
                        qual = f"{rt[-1]}.{name}"
                pf.symbols.append(Symbol(
                    name=name, qualname=qual, kind=kind,
                    start_line=node.start_point[0] + 1, end_line=node.end_point[0] + 1,
                    signature=_signature(node, src, lang), parent=scope,
                ))
                new_scope, new_prefix = len(pf.symbols) - 1, qual
                # Superclasses become inherits references.
                for f in ("superclasses", "superclass"):
                    sup = node.child_by_field_name(f)
                    if sup is not None:
                        for m in re.finditer(r"[A-Za-z_][A-Za-z0-9_]*", _text(sup, src)):
                            if m.group(0) not in ("object", "extends", "implements"):
                                pf.refs.append(Ref(m.group(0), None, node.start_point[0] + 1,
                                                   "inherits", new_scope))
        elif t == "impl_item":  # rust: methods qualify under the implemented type
            name = _def_name(node, src)
            if name:
                new_prefix = name

        if t in spec.calls:
            f = spec.calls[t]
            callee = node.child_by_field_name(f) if f else (
                node.named_children[0] if node.named_children else None)
            if callee is not None:
                name, qual = _reduce_name(callee, src)
                if name:
                    kind = "decorator" if t == "decorator" else "call"
                    pf.refs.append(Ref(name, qual, node.start_point[0] + 1, kind, scope))
                    if name == "require" and lang in ("javascript", "typescript", "tsx"):
                        args = node.child_by_field_name("arguments")
                        if args is not None and args.named_children \
                                and args.named_children[0].type == "string":
                            mod = _text(args.named_children[0], src).strip("'\"`")
                            pf.imports.append(Import(mod, [], None, node.start_point[0] + 1))

        if t in spec.imports:
            imp = _parse_import(node, src, lang)
            if imp is not None:
                pf.imports.append(imp)

        if t in spec.branches:
            pf.complexity += 1

        for child in reversed(node.children):
            if child.is_named:
                stack.append((child, new_scope, new_prefix))

    pf.complexity += len([s for s in pf.symbols if s.kind in ("function", "method")])


def _innermost_symbol(pf: ParsedFile, line: int) -> int | None:
    best, best_size = None, None
    for i, s in enumerate(pf.symbols):
        if s.start_line <= line <= s.end_line:
            size = s.end_line - s.start_line
            if best_size is None or size < best_size:
                best, best_size = i, size
    return best


def _scope_chain(pf: ParsedFile, idx: int | None) -> str:
    parts = []
    while idx is not None:
        s = pf.symbols[idx]
        parts.append(f"{s.kind} {s.name}")
        idx = s.parent
    return " > ".join(reversed(parts))


def _make_chunk(pf: ParsedFile, text: str, start_line: int, end_line: int,
                lang: str | None, src_node=None, src: bytes | None = None,
                spec: LangSpec | None = None) -> Chunk:
    enclosing = _innermost_symbol(pf, start_line)
    while enclosing is not None and pf.symbols[enclosing].start_line >= start_line:
        enclosing = pf.symbols[enclosing].parent
    defined = [i for i, s in enumerate(pf.symbols)
               if start_line <= s.start_line <= end_line
               and (s.parent is None or s.parent == enclosing
                    or pf.symbols[s.parent].start_line < start_line)]
    # The symbol a chunk is "about": the first definition it contains, else its enclosing scope.
    sym_idx = defined[0] if defined else enclosing
    header = pf.path
    chain = _scope_chain(pf, enclosing)
    if chain:
        header += f" :: in {chain}"
    if defined:
        names = ", ".join(f"{pf.symbols[i].kind} {pf.symbols[i].name}" for i in defined[:5])
        header += f" :: defines {names}"
    sig = pf.symbols[sym_idx].signature if sym_idx is not None else ""
    if sig:
        header += f"\n{sig}"
    doc = ""
    if src_node is not None and src is not None and spec is not None \
            and src_node.type in spec.defs:
        doc = _docstring(src_node, src, spec.name)
    body_preview = "\n".join(line for line in text.splitlines() if line.strip())
    card = header + ("\n" + doc if doc else "") + "\n" + body_preview
    card = card[: settings.card_chars]
    return Chunk(start_line, end_line, sym_idx, header, text, card)


def _chunk_tree(root, src: bytes, pf: ParsedFile, spec: LangSpec) -> list[Chunk]:
    limit = settings.chunk_chars
    spans: list[tuple[int, int, object]] = []  # start_byte, end_byte, first node

    def emit(group: list) -> None:
        if group:
            spans.append((group[0].start_byte, group[-1].end_byte, group[0]))

    def visit(nodes: list, depth: int) -> None:
        group: list = []
        size = 0
        for n in nodes:
            n_size = n.end_byte - n.start_byte
            if n_size > limit:
                emit(group)
                group, size = [], 0
                kids = [c for c in n.children]
                body = n.child_by_field_name("body")
                if body is not None and body.end_byte - body.start_byte > limit // 2:
                    # Keep the definition line with the first part of the body.
                    head_end = body.start_byte
                    spans.append((n.start_byte, head_end, n))
                    kids = list(body.children)
                if depth < 6 and len(kids) > 1:
                    visit(kids, depth + 1)
                else:
                    spans.append((n.start_byte, n.end_byte, n))
                continue
            if size + n_size > limit and group:
                emit(group)
                group, size = [], 0
            group.append(n)
            size += n_size
        emit(group)

    visit(list(root.children), 0)

    # Merge definition-header spans into the following span when they are adjacent and small.
    merged: list[tuple[int, int, object]] = []
    for s in sorted(spans, key=lambda x: x[0]):
        if merged and s[0] - merged[-1][1] < 200 \
                and (s[1] - merged[-1][0]) <= limit and (merged[-1][1] - merged[-1][0]) < 300:
            merged[-1] = (merged[-1][0], s[1], merged[-1][2])
        else:
            merged.append(s)

    chunks = []
    for start_b, end_b, node in merged:
        text = src[start_b:end_b].decode("utf-8", "replace")
        if not text.strip():
            continue
        if len(text) > limit * 2:  # pathological single nodes (huge literals)
            first_line = src[:start_b].count(b"\n") + 1
            chunks.extend(_chunk_lines(pf.path, text, first_line, pf))
            continue
        start_line = src[:start_b].count(b"\n") + 1
        end_line = start_line + text.count("\n")
        chunks.append(_make_chunk(pf, text, start_line, end_line, pf.lang, node, src, spec))
    return chunks


def _chunk_lines(path: str, text: str, first_line: int = 1,
                 pf: ParsedFile | None = None) -> list[Chunk]:
    limit = settings.chunk_chars
    pf = pf or ParsedFile(path, None, 0)
    lines = text.splitlines(keepends=True)
    chunks: list[Chunk] = []
    buf: list[str] = []
    size = 0
    start = first_line
    for i, line in enumerate(lines):
        boundary = not line.strip() or line.startswith("#")
        if size + len(line) > limit and buf and (boundary or size > limit * 1.3):
            body = "".join(buf)
            if body.strip():
                chunks.append(_make_chunk(pf, body, start, start + len(buf) - 1, pf.lang))
            start = first_line + i
            buf, size = [], 0
        buf.append(line[:limit])
        size += len(line[:limit])
    if buf and "".join(buf).strip():
        chunks.append(_make_chunk(pf, "".join(buf), start, start + len(buf) - 1, pf.lang))
    return chunks

"""Identifier handling for code-aware lexical search."""

from __future__ import annotations

import re

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,63}")
_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")

# Names too common to be useful as graph edges or lexical anchors.
STOP_NAMES = frozenset("""
self this super cls len str int float bool dict list set tuple print range open type object
get set add put pop push append extend update keys values items join split strip format map
filter reduce sort sorted min max sum any all abs next iter isinstance hasattr getattr setattr
log info debug warn warning error exception then catch resolve reject require new return
string number boolean console window document toString valueOf equals hashCode length size
""".split())


def split_identifier(name: str) -> list[str]:
    """`parseHTTPRequest_v2` -> ['parse', 'http', 'request', 'v', '2']."""
    parts: list[str] = []
    for piece in name.split("_"):
        if piece:
            parts.extend(m.group(0).lower() for m in _CAMEL.finditer(piece))
    return parts


def identifier_terms(text: str, limit: int = 400) -> str:
    """Space-joined identifiers plus their sub-tokens, deduplicated, for the FTS idents column."""
    seen: dict[str, None] = {}
    for m in _IDENT.finditer(text):
        ident = m.group(0)
        low = ident.lower()
        if low in seen:
            continue
        seen[low] = None
        subs = split_identifier(ident)
        if len(subs) > 1:
            for s in subs:
                if len(s) > 1:
                    seen.setdefault(s, None)
        if len(seen) >= limit:
            break
    return " ".join(seen)


def fts_query(text: str, max_terms: int = 24) -> str:
    """Build a safe FTS5 OR-query from free text or code."""
    terms: dict[str, None] = {}
    for m in _IDENT.finditer(text):
        ident = m.group(0)
        low = ident.lower()
        if low in STOP_NAMES or len(low) < 2:
            continue
        terms.setdefault(low, None)
        for s in split_identifier(ident):
            if len(s) > 2 and s not in STOP_NAMES:
                terms.setdefault(s, None)
        if len(terms) >= max_terms:
            break
    return " OR ".join(f'"{t}"' for t in terms)

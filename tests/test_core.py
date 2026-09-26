"""Unit tests for parsing, graph resolution, diff handling, retrieval fusion and grounding."""

from revpr.graph import build_edges, pagerank
from revpr.identifiers import fts_query, identifier_terms, split_identifier
from revpr.langs import detect, is_test_path
from revpr.parsing import parse_source
from revpr.retrieval import rrf
from revpr.review.diffparse import annotate_patch, in_hunks, parse_patch
from revpr.github import GitHubError, parse_pr_url, parse_repo_url

import pytest


def _parse(path, src):
    lang, parsed = detect(path)
    return parse_source(path, src.encode(), lang, parsed)


def test_split_identifier():
    assert split_identifier("parseHTTPRequest_v2") == ["parse", "http", "request", "v", "2"]
    assert "http" in identifier_terms("def parseHTTPRequest(): pass").split()


def test_fts_query_is_quoted_and_drops_stopwords():
    q = fts_query('self.get_user("x"); DROP TABLE users; -- "quoted"')
    assert '"get_user"' in q and '"self"' not in q
    assert all(part.startswith('"') and part.endswith('"') for part in q.split(" OR "))


def test_python_symbols_refs_imports():
    pf = _parse("pkg/mod.py", (
        "from .util import helper as h\n"
        "import os\n"
        "class A(Base):\n"
        "    def run(self):\n"
        "        return h(os.getcwd())\n"
    ))
    assert [s.qualname for s in pf.symbols] == ["A", "A.run"]
    assert pf.symbols[1].kind == "method"
    assert any(r.name == "h" for r in pf.refs)
    assert any(r.kind == "inherits" and r.name == "Base" for r in pf.refs)
    assert pf.imports[0].names == [("helper", "h")]


def test_typescript_arrow_functions_and_imports():
    pf = _parse("src/a.ts", "import { b } from './b';\nexport const f = (x: number) => b(x);\n")
    assert [s.name for s in pf.symbols] == ["f"]
    assert pf.imports[0].module == "./b"


def test_chunks_cover_definitions_with_headers():
    body = "\n".join(f"    x{i} = {i}" for i in range(80))
    pf = _parse("m.py", f"def big():\n{body}\n\ndef small():\n    return 1\n")
    assert pf.chunks, "file should be chunked"
    assert all(c.header.startswith("m.py") for c in pf.chunks)
    assert any("small" in c.header for c in pf.chunks)


def test_graph_resolves_imports_and_ignores_external_names():
    util = _parse("pkg/util.py", "def helper(x):\n    return x\ndef unquote(v):\n    return v\n")
    mod = _parse("pkg/mod.py", "from .util import helper\n"
                               "from urllib.parse import unquote\n"
                               "def run():\n    return helper(unquote('a'))\n")
    test = _parse("tests/test_mod.py", "from pkg.mod import run\ndef test_run():\n    run()\n")
    edges = build_edges([util, mod, test], [False, False, True]).edges
    kinds = {(k, sf, df) for k, sf, _, df, _, _, _ in edges}
    assert ("imports", 1, 0) in kinds
    calls = [(sf, ss, df, ds, w) for k, sf, ss, df, ds, w, _ in edges if k == "calls"]
    # run -> helper resolved through the explicit import
    assert any(df == 0 and util.symbols[ds].name == "helper" and w >= 0.9
               for _, _, df, ds, w in calls)
    # run -> unquote must NOT resolve to pkg/util.py: it comes from urllib
    assert not any(df == 0 and util.symbols[ds].name == "unquote" for _, _, df, ds, _ in calls)
    assert any(k == "tests" for k, *_ in edges)


def test_pagerank_prefers_hub():
    ranks = pagerank(3, [(0, 2, 1.0), (1, 2, 1.0)])
    assert ranks[2] == max(ranks)


def test_rrf_rewards_agreement():
    fused = rrf({"lexical": [1, 2, 3], "dense": [3, 4, 1]})
    order = [c for c, _, _ in fused]
    assert order[0] in (1, 3) and set(order[:2]) == {1, 3}


def test_patch_parsing_and_annotation():
    patch = "@@ -10,3 +10,4 @@ def f():\n a\n-b\n+c\n+d\n e\n"
    hunks = parse_patch(patch)
    assert hunks[0].added == [11, 12] and hunks[0].removed == [11]
    assert in_hunks(hunks, 12) and not in_hunks(hunks, 40)
    text = annotate_patch("f.py", hunks)
    assert "   11 + c" in text


def test_url_parsing_is_strict():
    assert parse_pr_url("https://github.com/Owner/Repo/pull/12/files") == ("owner/repo", 12)
    assert parse_repo_url("https://github.com/a/b.git") == "a/b"
    for bad in ("https://gitlab.com/a/b", "https://github.com/a/../b", "file:///etc/passwd",
                "https://github.com/a/b/pull/x"):
        with pytest.raises(GitHubError):
            parse_pr_url(bad) if "pull" in bad else parse_repo_url(bad)


def test_test_path_detection():
    assert is_test_path("tests/test_x.py") and is_test_path("src/a.spec.ts")
    assert not is_test_path("src/contest.py")


def test_client_ip_trusts_forwarded_header_only_from_cloudflare():
    from starlette.requests import Request

    from revpr.api import _ip

    def req(peer, fwd=None):
        headers = [(b"x-real-ip", peer.encode())]
        if fwd:
            headers.append((b"x-revpr-client-ip", fwd.encode()))
        return Request({"type": "http", "headers": headers, "client": ("127.0.0.1", 1)})

    assert _ip(req("162.158.1.2", "203.0.113.9")) == "203.0.113.9"   # via Cloudflare
    assert _ip(req("198.51.100.7", "203.0.113.9")) == "198.51.100.7"  # spoof attempt
    assert _ip(req("162.158.1.2", "not-an-ip")) == "162.158.1.2"

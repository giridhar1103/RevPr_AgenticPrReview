"""End-to-end retrieval regression on a small synthetic repository (no network, no models).

Builds a git repo on disk, indexes it through the real pipeline and checks that lexical,
symbol and graph channels find the right code. Guards against regressions in parsing,
FTS scoping and graph expansion.
"""

import subprocess

import pytest

FILES = {
    "shop/cart.py": (
        "from .pricing import apply_discount\n\n"
        "class Cart:\n"
        "    def __init__(self):\n        self.items = []\n\n"
        "    def total(self):\n"
        "        subtotal = sum(i.price for i in self.items)\n"
        "        return apply_discount(subtotal)\n"
    ),
    "shop/pricing.py": (
        "DISCOUNT_THRESHOLD = 100\n\n"
        "def apply_discount(amount):\n"
        "    \"\"\"Ten percent off orders above the threshold.\"\"\"\n"
        "    if amount > DISCOUNT_THRESHOLD:\n        return amount * 0.9\n"
        "    return amount\n"
    ),
    "shop/__init__.py": "",
    "tests/test_pricing.py": (
        "from shop.pricing import apply_discount\n\n"
        "def test_discount():\n    assert apply_discount(200) == 180\n"
    ),
}


@pytest.fixture(scope="module")
def snapshot(tmp_path_factory, monkeypatch_module):
    root = tmp_path_factory.mktemp("data")
    monkeypatch_module.setenv("REVPR_DATA", str(root))
    import importlib

    import revpr.config as config
    importlib.reload(config)
    from revpr import db, gitops, indexer
    for mod in (db, gitops, indexer):
        importlib.reload(mod)
    db.init()
    repo = config.settings.repos_dir / "acme__shop"
    repo.mkdir(parents=True)
    for path, text in FILES.items():
        p = repo / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin", "HOME": str(root)}
    for cmd in (["git", "init", "-q"], ["git", "add", "."], ["git", "commit", "-qm", "init"]):
        subprocess.run(cmd, cwd=repo, check=True, env=env)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True,
                         text=True, env=env).stdout.strip()
    snap = indexer.index_snapshot("acme/shop", sha)
    return snap


@pytest.fixture(scope="module")
def monkeypatch_module():
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


def test_lexical_finds_identifier(snapshot):
    from revpr import retrieval
    hits = retrieval.search(snapshot.id, "DISCOUNT_THRESHOLD", k=3,
                            channels=("lexical",), use_rerank=False)
    assert hits and hits[0].path == "shop/pricing.py"


def test_symbol_and_graph_channels(snapshot):
    from revpr import retrieval
    hits = retrieval.search(snapshot.id, "why is apply_discount wrong for large orders", k=6,
                            channels=("symbols", "graph"), use_rerank=False)
    paths = [h.path for h in hits]
    assert "shop/pricing.py" in paths          # the definition
    assert "shop/cart.py" in paths             # its caller, via the graph
    assert "tests/test_pricing.py" in paths    # its test, via the graph

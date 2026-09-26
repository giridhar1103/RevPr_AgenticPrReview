"""Runtime settings.

Secrets live outside the repository in an env file (default /root/.secrets/code-review.env).
Everything else has a default that suits a 4 vCPU / 8 GB host.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_env_file(path: str) -> None:
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file(os.environ.get("REVPR_ENV_FILE", "/root/.secrets/code-review.env"))


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path(os.environ.get("REVPR_DATA", "/root/revpr/data"))
    github_token: str = os.environ.get("GITHUB_TOKEN", "")
    qdrant_url: str = os.environ.get("QDRANT_URL", "")
    qdrant_api_key: str = os.environ.get("QDRANT_API_KEY", "")
    qdrant_collection: str = os.environ.get("REVPR_QDRANT_COLLECTION", "revpr_cards_v1")
    providers_file: str = os.environ.get("REVPR_PROVIDERS", "/root/.secrets/revpr-providers.json")
    phoenix_endpoint: str = os.environ.get("REVPR_PHOENIX", "http://127.0.0.1:6006/v1/traces")

    embed_model: str = os.environ.get("REVPR_EMBED_MODEL", "jinaai/jina-embeddings-v2-base-code")
    rerank_model: str = os.environ.get("REVPR_RERANK_MODEL", "jinaai/jina-reranker-v1-turbo-en")
    model_threads: int = _int("REVPR_MODEL_THREADS", 3)

    # Admission limits for public requests.
    max_repo_kb: int = _int("REVPR_MAX_REPO_KB", 150_000)
    max_source_files: int = _int("REVPR_MAX_SOURCE_FILES", 5_000)
    max_file_bytes: int = _int("REVPR_MAX_FILE_BYTES", 400_000)
    max_pr_files: int = _int("REVPR_MAX_PR_FILES", 50)
    max_pr_changed_lines: int = _int("REVPR_MAX_PR_LINES", 3_000)

    # Indexing budgets.
    chunk_chars: int = _int("REVPR_CHUNK_CHARS", 1_500)
    card_chars: int = _int("REVPR_CARD_CHARS", 600)
    history_commits: int = _int("REVPR_HISTORY_COMMITS", 1_000)
    cochange_max_files: int = _int("REVPR_COCHANGE_MAX_FILES", 50)
    dense_cap_per_snapshot: int = _int("REVPR_DENSE_CAP", 12_000)
    clone_timeout_s: int = _int("REVPR_CLONE_TIMEOUT", 180)

    excluded_dirs: tuple[str, ...] = field(default=(
        ".git", "node_modules", "vendor", "third_party", "dist", "build", ".venv", "venv",
        "__pycache__", ".tox", ".mypy_cache", "site-packages", "target", ".next", "coverage",
    ))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "revpr.db"

    @property
    def repos_dir(self) -> Path:
        return self.data_dir / "repos"


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.repos_dir.mkdir(parents=True, exist_ok=True)

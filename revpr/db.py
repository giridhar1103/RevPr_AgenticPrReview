"""SQLite storage: metadata, code graph, lexical index, embeddings cache, jobs."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import settings

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS repos (
    id INTEGER PRIMARY KEY,
    full_name TEXT NOT NULL UNIQUE,          -- owner/name, lowercase
    default_branch TEXT,
    size_kb INTEGER,
    stars INTEGER,
    description TEXT,
    updated_at REAL
);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY,
    repo_id INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    sha TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, indexing, ready, failed
    stage TEXT,
    error TEXT,
    stats TEXT,                              -- json
    dense_done INTEGER NOT NULL DEFAULT 0,
    dense_total INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    last_used_at REAL NOT NULL,
    UNIQUE (repo_id, sha)
);

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    lang TEXT,
    loc INTEGER NOT NULL DEFAULT 0,
    complexity INTEGER NOT NULL DEFAULT 0,
    is_test INTEGER NOT NULL DEFAULT 0,
    churn INTEGER NOT NULL DEFAULT 0,        -- commits touching the file in the history window
    churn_recent INTEGER NOT NULL DEFAULT 0, -- in the last 90 days
    authors INTEGER NOT NULL DEFAULT 0,
    last_commit_at REAL,
    pagerank REAL NOT NULL DEFAULT 0,
    UNIQUE (snapshot_id, path)
);

CREATE TABLE IF NOT EXISTS symbols (
    id INTEGER PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    qualname TEXT NOT NULL,
    kind TEXT NOT NULL,                      -- function, method, class, interface, type, module
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    signature TEXT,
    parent_id INTEGER
);
CREATE INDEX IF NOT EXISTS ix_symbols_name ON symbols (snapshot_id, name);
CREATE INDEX IF NOT EXISTS ix_symbols_file ON symbols (file_id);

-- Edges between symbols (kind in calls, inherits, tests) or files (imports, cochange, tests_file).
CREATE TABLE IF NOT EXISTS edges (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    src INTEGER NOT NULL,
    dst INTEGER NOT NULL,
    weight REAL NOT NULL DEFAULT 1,
    line INTEGER,
    PRIMARY KEY (snapshot_id, kind, src, dst)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_edges_dst ON edges (snapshot_id, kind, dst);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    symbol_id INTEGER,                       -- innermost enclosing symbol, if any
    header TEXT NOT NULL,
    text TEXT NOT NULL,
    card TEXT NOT NULL,
    card_hash TEXT NOT NULL,
    priority REAL NOT NULL DEFAULT 0,
    embedded INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_chunks_file ON chunks (file_id, start_line);
CREATE INDEX IF NOT EXISTS ix_chunks_embed ON chunks (snapshot_id, embedded, priority);

-- rowid = chunks.id. `snap` holds a per-snapshot token (s<id>) so a MATCH can be scoped
-- to one snapshot inside the index instead of filtering after ranking.
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    snap, idents, body, content='', contentless_delete=1, tokenize='unicode61'
);

CREATE TABLE IF NOT EXISTS embeddings (
    card_hash TEXT NOT NULL,
    model TEXT NOT NULL,
    vector BLOB NOT NULL,                    -- float16
    PRIMARY KEY (card_hash, model)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,                      -- pr_review, repo_review, ask
    cache_key TEXT,
    input TEXT NOT NULL,                     -- json
    status TEXT NOT NULL DEFAULT 'queued',   -- queued, running, done, failed
    error TEXT,
    result TEXT,                             -- json
    client_ip TEXT,
    created_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL
);
CREATE INDEX IF NOT EXISTS ix_jobs_status ON jobs (status, created_at);
CREATE INDEX IF NOT EXISTS ix_jobs_cache ON jobs (cache_key, status);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    job_id TEXT NOT NULL,
    at REAL NOT NULL,
    type TEXT NOT NULL,
    data TEXT NOT NULL                       -- json
);
CREATE INDEX IF NOT EXISTS ix_events_job ON events (job_id, id);
"""

_local = threading.local()


def connect(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or settings.db_path, timeout=30, isolation_level=None,
                           check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def get() -> sqlite3.Connection:
    """One connection per thread."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = connect()
        _local.conn = conn
    return conn


def init(path: Path | None = None) -> None:
    conn = connect(path)
    conn.executescript(SCHEMA)
    conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection | None = None) -> Iterator[sqlite3.Connection]:
    conn = conn or get()
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")

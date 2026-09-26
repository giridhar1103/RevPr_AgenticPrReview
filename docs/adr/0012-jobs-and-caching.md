# 0012. Jobs, streaming and caching

Status: accepted, 2026-09-23

## Context
Indexing takes minutes on CPU; the site must stay responsive and cheap.

## Decision
Jobs are rows in SQLite processed by a separate worker process (one indexing job at a time). Progress events stream to the browser over SSE. Caches: snapshot index by (repo, sha); PR review by (PR, head sha, pipeline version); embeddings by content hash. Rate limits per IP and a global daily cap on model calls.

## Consequences
Repeat requests are instant; a new PR on an already indexed repo only indexes the changed files.

## Evidence
See [research bibliography](../research/bibliography.md): [157][161][249][250]

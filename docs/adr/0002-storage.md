# 0002. Storage: SQLite locally, Qdrant Cloud for dense vectors

Status: accepted, 2026-09-23

## Context
We need metadata, a code graph, lexical search and vector search on a server with about 4.8 GB of free RAM, and the user wants load moved off the VPS where possible.

## Decision
SQLite in WAL mode holds all metadata, the graph, git statistics and the FTS5 lexical index. Dense vectors go to one Qdrant Cloud collection using multitenancy (payload index on `snapshot_id` marked as tenant), int8 scalar quantization kept in RAM and float32 originals on disk. Every vector is also stored locally as float16 keyed by content hash, which gives an exact-search fallback when Qdrant is unavailable and lets us rebuild the cluster if the free tier deletes it after inactivity.

## Consequences
One process-local database, no extra services. The vector store sits behind an interface with two implementations. Local vectors cost about 1.5 KB per chunk.

## Evidence
See [research bibliography](../research/bibliography.md): [127][128][129][130][131][242][275][277]

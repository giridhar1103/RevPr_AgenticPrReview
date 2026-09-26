# RevPr architecture

RevPr reviews public GitHub pull requests and repositories. It indexes the repository, retrieves
the context a change actually touches, reasons about the impact, and returns findings that cite
the code they are based on. Design rationale is in [`research/README.md`](research/README.md) and
the individual decisions are in [`adr/`](adr/).

## Modes

**PR review.** Input: a public PR URL. Output: a walkthrough of the change (intent, affected
components, risk), verified findings with file and line evidence and a suggested diff, and a
markdown review ready to paste into GitHub.

**Repo review.** Input: a public repository URL. Output: an architecture map, hotspots ranked by
churn and complexity, untested important symbols, a focused review of the top hotspots, and
"ask the repo" question answering with citations.

Both modes expose a retrieval trace: every query the system ran, what came back from each channel,
the fused ranking, and which results were used.

## System

```
                    giriworks.com/code-review  (static page)
                                 │  HTTPS + SSE
                                 ▼
nginx (api.giriworks.com/revpr/) ── rate limits ──►  FastAPI  :8020
                                                          │
                            SQLite (WAL) ◄────────────────┤  jobs, results, cache
                                                          │
                                                   Worker process
      ┌───────────────┬───────────────┬──────────────┬───┴────────────┬──────────────────┐
      ▼               ▼               ▼              ▼                ▼                  ▼
  GitHub REST     git (blobless   Tree-sitter    Embedder +      Static analyzers    Inference
  (PR, diff,      partial clone,  chunks,        reranker        (ruff, semgrep)     provider
   comments)      history)        symbols,       (ONNX, CPU)     read-only           (pluggable)
                                  graph                │
                                    │                  ▼
                                    ▼           Qdrant Cloud (dense, int8)
                              SQLite: FTS5,      + local vector copy
                              graph, git stats   (fallback and rebuild)

                         OpenTelemetry (OpenInference) ──► Phoenix :6006 (localhost)
```

## Pipeline

### Indexing (per repository snapshot)
1. **Fetch.** Blobless partial clone of the default branch or the PR base commit, hardened (see
   ADR 0010). Size and file-count caps enforced from the GitHub API before cloning.
2. **Parse.** Tree-sitter parses each source file. Definitions and references come from tag
   queries. Imports are resolved to files for Python and JS/TS.
3. **Chunk.** AST-aligned chunks in the cAST style: one function or class per chunk where it fits,
   large nodes split recursively, small siblings merged. Each chunk gets a deterministic header
   (path, enclosing scope, signature, imports used).
4. **Lexical index.** SQLite FTS5 over chunk text plus identifier sub-tokens
   (`parseHttpRequest` also indexed as `parse http request`).
5. **Dense index.** Chunks embedded on CPU, cached by content hash, so a later snapshot of the same
   repo re-embeds only changed chunks. Vectors are written to Qdrant (tenant = snapshot) and kept
   locally as float16.
6. **Graph.** Nodes are files, classes and functions. Edges: contains, imports, calls/references
   (name-resolved, with confidence), tests (test file or function referencing a symbol),
   co-change (from git history).
7. **History.** Per-file churn, authors and last-modified from `git log`; co-change pairs from the
   last 1,000 commits; blame on demand.

### Retrieval
Three channels run in parallel for any query (text or a code span):
- lexical (FTS5 BM25),
- dense (Qdrant, filtered to the snapshot),
- structural (graph expansion from seed symbols: callers, callees, tests, co-changed files).

Results are fused with Reciprocal Rank Fusion (k = 60), deduplicated by span, and reranked with a
CPU cross-encoder. Every step emits an OpenInference span.

### PR review workflow
1. Fetch PR metadata, commits, diff and existing comments.
2. Index the base snapshot (or reuse the cache), then map diff hunks to changed symbols.
3. Build a context pack per changed symbol: its definition, callers, callees, tests, co-changed
   files, recent history, and similar code. Budgeted by tokens and ranked.
4. Run static analyzers on changed files only, restricted to changed lines.
5. **Review pass.** The model receives the diff, the context pack and analyzer output as
   delimited data. It returns a structured envelope: walkthrough, candidate findings, and up to
   three requests for more context (tool calls).
6. **Investigation.** Requested tools run (search, callers, tests, history, read range), results are
   appended, and the review pass repeats. Hard cap of two rounds.
7. **Verification.** Deterministic checks first (cited file and lines exist, fall inside the diff
   or the retrieved evidence). Then a separate verifier call judges each surviving finding
   against its evidence and drops weak ones.
8. Render: walkthrough, findings ordered by severity, markdown review, retrieval trace.

### Repo review workflow
Index, compute hotspots (churn x complexity) and a PageRank repository map, find important symbols
with no test edges, review the top N hotspot files with the same review pass and verifier, and
serve "ask the repo" through the retrieval stack.

## Data model (SQLite)

`repos`, `snapshots(repo, sha, status, stats)`, `files(snapshot, path, lang, loc, complexity,
churn)`, `symbols(snapshot, file, name, kind, span, signature)`, `edges(snapshot, src, dst, kind,
weight)`, `chunks(snapshot, file, span, content_hash, header, text)`, `chunks_fts` (FTS5),
`embeddings(content_hash, model, vector f16)`, `jobs`, `results`, `events`.

## Budgets (4 vCPU, 7.8 GB RAM shared with other services)
- One indexing job at a time; two LLM calls in flight.
- Repos up to 150 MB and 5,000 source files; PRs up to 50 files and 3,000 changed lines.
- Embedding model and reranker loaded once in the worker (about 1 GB combined).
- Qdrant Cloud free tier: 1 GB RAM, 4 GB disk; least recently used snapshots evicted beyond
  600k points.

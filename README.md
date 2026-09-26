# RevPr

Repository-aware code review for public GitHub pull requests and repositories.

Paste a PR link and RevPr indexes the repository at the PR's base commit, maps the diff to the
functions and classes it changes, retrieves the code around them (callers, callees, tests, files
that historically change together, related code found by search), and asks a model to review the
change with that evidence. A second pass verifies every finding before it is shown. Paste a
repository link and you get its architecture, its riskiest files, hidden coupling, test gaps and
a verified review of the top hotspots, plus question answering over the code with citations.

Live at [giriworks.com/code_review](https://giriworks.com/code_review).

## Why it is built this way

The design follows a literature and industry review of 277 sources, summarized in
[`docs/research/README.md`](docs/research/README.md). Each major decision has an ADR in
[`docs/adr/`](docs/adr/). The short version:

- **Precision is the product.** Noisy reviewers get ignored. Every finding must cite evidence ids
  and real lines; deterministic grounding checks run first, then a separate verification pass.
  Rejected candidates stay visible in a "filtered" section instead of disappearing.
- **Structure beats flat chunks for code.** Retrieval combines four channels (BM25 over
  code-aware identifier tokens, dense vectors, exact symbol lookup and code-graph expansion)
  fused with reciprocal rank fusion, then reranked.
- **Git history is a retrieval signal.** Co-change and churn surface files that usually change
  with the edited code, which is how "you forgot to update X" findings are found.
- **Workflow first, agent where it pays.** A fixed pipeline builds the context; the model may
  request up to two rounds of extra context through search, callers, callees, tests, history
  and read tools.
- **Repositories are hostile input.** Hardened blobless clones (no hooks, submodules, symlinks
  or local transports), nothing from the repository is executed, and repository text is passed
  to the model as delimited, untrusted data.

## Architecture

```
Browser ──► nginx ──► FastAPI (rate limits, cache, SSE) ──► SQLite job queue ──► Worker
                                                                                   │
   ┌──────────────┬──────────────┬───────────────┬────────────────┬──────────────┤
   ▼              ▼              ▼               ▼                ▼              ▼
GitHub API   git (blobless)  Tree-sitter     ONNX embedder     ruff (read   Model provider
             + history       symbols, graph, and reranker      only)        (pluggable)
                             AST chunks      on CPU
                                  │               │
                                  ▼               ▼
                        SQLite: FTS5, graph   Qdrant Cloud (int8) + local fallback
                                  │
                                  └──► OpenTelemetry / OpenInference ──► Arize Phoenix
```

See [`docs/architecture.md`](docs/architecture.md) for the pipeline, data model and budgets.

## Running on a 4 vCPU, 8 GB server

Everything except model inference runs locally on CPU. Measured on the production host:

| Step | Cost |
|---|---|
| Index click (151 files, 2k symbols, 3.8k graph edges, 1k commits) | 3 s |
| Index httpx (89 files) | 2.3 s |
| Embed one chunk card, jina-embeddings-v2-base-code | about 0.28 s |
| Rerank 20 candidates, jina-reranker-v1-turbo | about 0.8 s |
| PR review end to end (5 files) | 60 to 90 s, about $0.10 to $0.15 |

Because full-chunk embedding on CPU would take hours for a mid-size repository, dense search
embeds a compact per-chunk card and fills in progressively in priority order, starting with the
neighbourhood of the change (ADR 0004). Lexical, symbol and graph search are available as soon as
indexing finishes.

## Evaluation

Three suites, results recorded as Arize Phoenix experiments and published on the site:

1. **Retrieval** ([`evals/retrieval_eval.py`](evals/retrieval_eval.py)). SWE-bench Lite: the
   query is the original issue text; gold is what the reference patch changed. Measures file
   recall@k, MRR and function recall per retrieval configuration. No model involved.
2. **Bug reintroduction** ([`evals/review_bench.py`](evals/review_bench.py)). Reverse a real
   fix to get a change that re-introduces the bug, review it, and check whether a verified
   finding lands on the bug. Reports detection before and after verification, other findings per
   PR, cost, and pass^k across repeated runs.
3. **Precision.** Findings outside the gold region are judged by a model from a different vendor
   than the reviewer, calibrated against hand labels.

## Layout

```
revpr/
  config.py, db.py            settings and SQLite schema
  github.py, gitops.py        GitHub REST client, hardened git
  langs.py, parsing.py        Tree-sitter tables, symbols, references, imports, chunking
  graph.py, history.py        code graph with resolution confidence, churn and co-change
  indexer.py                  snapshot indexing
  embed.py, vectorstore.py    CPU embeddings, Qdrant + local fallback
  retrieval.py                hybrid retrieval and RRF
  review/                     PR review, repo review, ask, evidence, prompts, verification
  llm/client.py               provider-agnostic model client
  tracing.py                  OpenInference spans to Phoenix
  jobs.py, worker.py, api.py  queue, worker, HTTP API
evals/                        retrieval eval and review benchmark
docs/                         research, architecture, ADRs
tests/                        unit tests
```

## Development

```bash
python3 -m venv venv && venv/bin/pip install -e ".[dev]"
venv/bin/pytest
venv/bin/uvicorn revpr.api:app --port 8020      # API
venv/bin/python -m revpr.worker                  # worker
```

Configuration is read from environment variables (see `revpr/config.py`); secrets and the
model provider file live outside the repository.

# 0004. CPU embedding model and reranker

Status: accepted, 2026-09-23 (revised after benchmarking the same day)

## Context
Query-time and index-time inference must run on 4 shared vCPUs (AVX2, no VNNI, about 170 GFLOPS
measured with a float32 matmul) with no GPU and about 4.8 GB of free RAM.

The first plan was jina-embeddings-v2-base-code over full chunks plus jina-reranker-v2. Measured
on this machine with FastEmbed (ONNX Runtime, 4 threads):

| Model | Input | Throughput | Peak RSS |
|---|---|---|---|
| jina-embeddings-v2-base-code (161M) | full chunk, about 1,400 chars | 1.2 to 2.1 chunks/s | about 1 GB |
| jina-embeddings-v2-base-code | 600-char card | 3.7 chunks/s | |
| bge-small-en-v1.5 (33M) | 600-char card | 19.4 chunks/s | 370 MB |
| jina-embeddings-v2-small-en (33M) | 600-char card | 20.5 chunks/s | |
| jina-reranker-v2-base-multilingual (278M) | 40 candidates | 8.6 s | |
| ms-marco-MiniLM-L-6-v2 (22M) | 20 candidates | 0.86 s | |
| jina-reranker-v1-turbo-en (38M) | 20 candidates | 0.78 s | |

These numbers match the compute bound (about 2 x parameters x tokens FLOPs per input). Embedding
every full chunk of a 2,000-file repository with a 161M model would take hours.

## Decision
1. **Embed a compact card, not the whole chunk.** The card is the deterministic header (path,
   scope, signature), the docstring or leading comment, and the first lines of the body, capped at
   600 characters. Bodies are still fully covered by the lexical index and the graph.
2. **Progressive dense index.** Lexical, graph and history channels are ready in seconds. Dense
   embeddings are computed in priority order in the background: first the neighborhood of the
   request (changed files, their imports, callers and co-changed files), then files by PageRank,
   up to a per-snapshot cap. Retrieval uses whatever is embedded at query time and the trace
   reports dense coverage.
3. **Content-hash cache.** Cards are cached by hash across snapshots, so popular repositories fill
   in over time and a new PR re-embeds only changed chunks.
4. **Model choice by measurement.** Default embedder: jina-embeddings-v2-base-code. Candidate:
   bge-small-en-v1.5 at 5x the speed. The retrieval eval (ADR 0011) picks the default by recall
   gained per second of CPU.
5. **Small reranker, small candidate set.** jina-reranker-v1-turbo-en over the top 20 fused
   candidates, about 0.8 s. The review pass reorders evidence itself, so reranking is applied to
   ask-the-repo and to context packs only where the eval shows a gain.

## Consequences
Indexing is interactive for lexical and structural search and eventually complete for dense
search. The design depends on the retrieval eval to justify dense retrieval's CPU cost, which is a
useful result either way.

## Evidence
See [research bibliography](../research/bibliography.md): [11][16][17][114][121][122][245][252][254][255]

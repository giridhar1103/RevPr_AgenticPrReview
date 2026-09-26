# 0011. Evaluation with Phoenix

Status: accepted, 2026-09-23

## Context
We need evidence that retrieval and reviews are good, not just a demo.

## Decision
Self-host Phoenix on localhost and send OpenInference spans for every retrieval, rerank, LLM and tool step. Three suites: (1) retrieval eval, no LLM, gold files from real fix commits, recall@k and MRR per channel and fused, run in CI; (2) bug-reintroduction benchmark, reverting real fix commits in well-tested Python repos and scoring file and line detection; (3) precision, a binary LLM judge calibrated against a hand-labeled sample, plus a deterministic invalid-citation rate. Report pass^k for detection. Results are published on a public evals page.

## Consequences
Ground truth comes from real history, not vendor-style self-scoring.

## Evidence
See [research bibliography](../research/bibliography.md): [178][179][186][191][196][211][212][216]

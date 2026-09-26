# 0006. Code graph from Tree-sitter, not from an LLM

Status: accepted, 2026-09-23

## Context
Graph retrieval is the biggest reported gain for repository tasks, but precise indexers (SCIP, stack graphs) are heavy and per-language.

## Decision
Build the graph from Tree-sitter tag queries: definitions, references, imports, containment. Resolve references by name with import-aware scoping for Python and JS/TS, and record a confidence on each edge (exact import match, same file, unique global name, ambiguous). Tests are linked when a test file or function references a symbol. Rank the graph with personalized PageRank for the repository map. SCIP is a later upgrade for Python.

## Consequences
Fast and language-broad. Some call edges are approximate; the confidence value is shown in the trace and used in ranking.

## Evidence
See [research bibliography](../research/bibliography.md): [25][27][28][30][42][46][139][142][148][149]

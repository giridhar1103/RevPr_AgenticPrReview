# 0003. AST-aligned chunking with deterministic context headers

Status: accepted, 2026-09-23

## Context
Fixed-size chunks split functions; contextual retrieval helps but calling an LLM per chunk is too slow and expensive on this hardware.

## Decision
Parse with Tree-sitter. Chunk in the cAST style (one definition per chunk where it fits, recursive split for large nodes, merge small siblings, budget about 1,500 characters). Prepend a header generated from the tree: file path, enclosing class, signature, and imported names used in the chunk. The header is indexed lexically and embedded.

## Consequences
Works for every language Tree-sitter supports. Gets most of the benefit of contextual retrieval with zero model calls.

## Evidence
See [research bibliography](../research/bibliography.md): [21][22][23][24][124][126][135]

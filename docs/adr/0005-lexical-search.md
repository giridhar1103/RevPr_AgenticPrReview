# 0005. Code-aware lexical search

Status: accepted, 2026-09-23

## Context
Code queries are dominated by identifiers, which dense retrieval handles poorly.

## Decision
SQLite FTS5 with the unicode61 tokenizer over two columns: raw chunk text, and an identifier column that expands camelCase, PascalCase and snake_case into sub-tokens. Ranking uses bm25() with the identifier column weighted higher.

## Consequences
Exact identifier hits rank first; natural-language queries still match through the sub-tokens.

## Evidence
See [research bibliography](../research/bibliography.md): [114][242][244][5]

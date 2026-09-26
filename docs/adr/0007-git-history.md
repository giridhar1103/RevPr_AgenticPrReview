# 0007. Git history as a retrieval channel

Status: accepted, 2026-09-23

## Context
Files that change together are coupled even without an import edge, and hotspots predict defects.

## Decision
Use a blobless partial clone so full history is available without downloading every file version. Compute per-file churn and author counts, and co-change pairs from the last 1,000 non-merge commits (ignoring commits touching more than 50 files). Blame is computed on demand for changed hunks.

## Consequences
Adds a signal commercial tools rely on at low cost. History-heavy repos are bounded by the commit window.

## Evidence
See [research bibliography](../research/bibliography.md): [104][105][107][108][260][261]

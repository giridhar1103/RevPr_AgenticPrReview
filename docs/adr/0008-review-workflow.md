# 0008. Fixed workflow with bounded investigation and a verifier

Status: accepted, 2026-09-23

## Context
Free-form agents are costly and unpredictable; fixed pipelines are competitive and easier to evaluate. Precision is what users care about.

## Decision
PR review runs a fixed pipeline: context pack, static analysis, review pass, up to two investigation rounds where the model may request tools (search, callers, callees, tests, history, read range), then verification. Verification is deterministic first (cited locations must exist and lie in the diff or retrieved evidence), then a separate verifier call that must affirm each finding from its evidence. Findings have severity and confidence; low-confidence findings are hidden by default.

## Consequences
Bounded cost per review. Every step is traceable and individually evaluable.

## Evidence
See [research bibliography](../research/bibliography.md): [34][38][80][85][176][230][94][226]

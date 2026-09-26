# 0009. Pluggable inference layer

Status: accepted, 2026-09-23

## Context
The reasoning model must be replaceable without code changes, and different steps may use different models.

## Decision
All model calls go through `LLMClient.complete(system, prompt, schema)`. Providers are configured outside the repository (`REVPR_PROVIDERS` file) and selected per role (reviewer, verifier, judge). Outputs are validated against JSON schemas and retried once on invalid output.

## Consequences
Swapping models is a config change. Each call is traced with latency and token counts where the provider reports them.

## Evidence
See [research bibliography](../research/bibliography.md): [170][177]

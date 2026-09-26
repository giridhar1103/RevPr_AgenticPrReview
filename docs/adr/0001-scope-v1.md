# 0001. Scope of v1

Status: accepted, 2026-09-23

## Context
The product must be usable by anyone without signing in, and cheap enough to host on one small VPS.

## Decision
v1 supports two inputs: a public PR URL (PR review) and a public repository URL (repo review). No OAuth, no GitHub App, no private repositories, no automatic posting to GitHub, and no execution of repository code. Suggested fixes are shown as diffs but never applied or run.

## Consequences
Removes the largest security and privacy surface (stored credentials, private code, sandboxed execution). Private repos and a GitHub App can be added later behind the same pipeline.

## Evidence
See [research bibliography](../research/bibliography.md): [73][76][80][270][273]

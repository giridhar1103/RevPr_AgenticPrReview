# 0010. Treat repositories as hostile input

Status: accepted, 2026-09-23

## Context
Anyone can submit any public repository. Git clone has had RCE bugs, and repository text can carry prompt injection.

## Decision
Only `https://github.com/<owner>/<repo>` URLs are accepted. Clones run with submodules disabled, `core.hooksPath=/dev/null`, `core.symlinks=false`, `protocol.file.allow=never`, no credential helper, a timeout, and a size cap checked before cloning. Repository code is never executed; ruff and semgrep only read files. Repository text is passed to the model as delimited data with an instruction that it is untrusted, the model has no side-effecting tools, all output is schema-validated, and the UI renders model output as escaped text with no raw HTML.

## Consequences
Reviewing is read-only by construction, so a successful injection can at worst degrade one review.

## Evidence
See [research bibliography](../research/bibliography.md): [199][200][201][204][206][207][208][209]

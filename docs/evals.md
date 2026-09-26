# Evaluation results

All runs are recorded as Arize Phoenix experiments (self-hosted) and summarized in
`data/evals/latest.json`, which the site shows on the code review page. Methodology follows
ADR 0011.

## Suite 1: retrieval (no model involved)

**Setup.** 120 SWE-bench Lite tasks stratified across all 12 repositories (up to 15 per repo,
including Django and SymPy). The query is the original issue text. Gold is what the reference
patch changed: the files, and the innermost function or class around each changed hunk at the
base commit. Each task's repository is indexed at its base commit, scored and deleted.

| Configuration | File recall@1 | File recall@5 | File recall@10 | File MRR | Function recall@10 | p50 latency |
|---|---|---|---|---|---|---|
| lexical (BM25 over code-aware tokens) | 0.16 | 0.38 | 0.53 | 0.27 | 0.20 | 35 ms |
| structural (symbols + graph) | 0.20 | 0.38 | 0.54 | 0.29 | 0.20 | 15 ms |
| lexical + structural (RRF) | 0.18 | 0.45 | 0.54 | 0.31 | 0.28 | 46 ms |
| lexical + structural + rerank | **0.23** | **0.59** | **0.70** | **0.39** | **0.31** | 4.0 s |

**Reading.** Lexical and structural retrieval find different things: fusing them lifts recall@5
by about 20% relative and function recall by about 40%. The CPU cross-encoder adds another 32%
relative at recall@5, at a cost of about 4 s per query with 40 candidates, which is acceptable
for a review that takes a minute but not for interactive search. Dense retrieval is evaluated
separately on a smaller subset because full CPU embedding of 120 repositories is not practical
on this host (ADR 0004).

## Suite 2: bug reintroduction

**Setup.** Single-file SWE-bench Lite fixes, stratified by repository. Each reference fix is
reversed, producing a change that puts the bug back. The change runs through the same
`review_change` pipeline as a GitHub PR. Detected means a verified finding overlaps the
re-introduced lines (3 lines of slack).

### Run 1 (flawed base, kept for the record)

The first version indexed the buggy commit as the base. Result: 87% detected after
verification, 100% before, zero off-target findings, pass^3 0.56 over 9 tasks, $0.063 per
review. Reading the misses showed that two of three were artifacts: base-side evidence showed
the buggy code, so a finding such as "this change removes the `socket.error` handler" was
contradicted by the evidence ("the base has no such handler") and the verifier correctly
rejected it. The benchmark was fixed to apply the reference patch as a local commit and index
that fixed state as the base. Raw results: `data/evals/review_bench_v1_buggy_base.json`.

### Run 2 (fixed base)

24 tasks across 12 repositories; the first 10 repeated three times.

| Metric | Run 1 (flawed base) | Run 2 (fixed base) |
|---|---|---|
| Detected after verification | 87% | **87.5%** (21/24) |
| Detected before verification | 100% | 91.7% |
| Verified findings off the bug, per PR | 0 | 0.04 (1 in 24 reviews) |
| Reviews with no off-target finding | 100% | 95.8% |
| pass^3 (every run detected) | 0.56 (9 tasks) | **0.70** (10 tasks) |
| pass@3 (any run detected) | 1.0 | 1.0 |
| Mean cost per review | $0.063 | $0.054 |
| p50 latency | 61 s | 50 s |

**Reading.** With a correct base the verifier removes one true hit out of 22 candidates
instead of three, while keeping off-target noise near zero. The largest gap is reliability:
every repeated task is caught at least once in three runs, but only 70% are caught every time,
so a single review should not be read as a guarantee. The one off-target finding (a missing
test for a new code path in pylint) was judged valid by the independent judge.

**Caveat.** These fixes are public, so models may have seen them. The before/after verification
comparison, the off-target finding rate and the run-to-run reliability (pass^k) are less exposed
to that than raw detection.

## Suite 3: precision

Run 2 produced one off-target verified finding; the judge (GPT-5.6-sol, a different vendor from
the reviewer) labelled it valid. The sample is too small to estimate a false-positive rate, so the
next step is to judge findings from real PR reviews on the site as they accumulate.

Verified findings outside the gold region are judged valid or invalid by a model from a
different vendor than the reviewer, and exported to `data/evals/judge_labels.csv` with an empty
`human_label` column for calibration by hand.

## What the evals changed

- Rerank depth and input caps: the first reranker configuration used 2.5 GB on long issue
  queries (attention memory is quadratic in length); inputs are now capped and batched.
- Streaming indexer: indexing Django was OOM-killed at 2.7 GB; it now peaks at 152 MB.
- Graph precision: names imported from outside the repository were being linked to in-repo
  functions with the same name; they are now excluded.
- Benchmark validity: the base-state bug described above.

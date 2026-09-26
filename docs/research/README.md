# Research: state of the art in repository-aware code review

September 2026. This document summarizes what the literature and production systems say about
retrieval over code, automated code review, and how to evaluate both. Every claim is cited to
[`bibliography.md`](bibliography.md) (277 sources). The decisions that follow from it are in
[`../architecture.md`](../architecture.md) and [`../adr/`](../adr/).

## 1. The problem

Modern code review is mostly about understanding a change, not finding defects. Microsoft's
field study found that reviewers spend most of their time building an understanding of the code
and the change, and that existing tools rarely meet that need [273]. Comment usefulness drops as
the number of files in a change grows [270], and useful comments are the ones that lead to a code
change nearby [270][271][272]. Any tool that wants to help has to do two things well:

1. Explain the change and its blast radius.
2. Raise a small number of findings that are correct, grounded in the repository, and actionable.

LLM reviewers are now common in industry. Google resolves 7.5% of reviewer comments with an
ML-suggested edit [71][72] and uses a best-practice commenter at scale [74]. Meta layers policy
gates, risk scoring, LLM review and deterministic validation to absorb the extra volume created by
AI-written code [76], and reports that structured reasoning templates make LLM review much more
reliable [78][79]. ByteDance runs a two-stage generate-then-filter reviewer [80]. Developers prefer
an AI-led first pass on large or unfamiliar PRs [61][77], but react badly to noisy or wrong
comments [73].

## 2. What goes wrong: noise

The dominant failure is false positives. Practitioner and academic studies agree that noisy
reviewers get ignored or disabled [93][94][95][96][97]. Root causes identified in the literature:
rules applied without the surrounding project context, missing cross-file information, and
hallucinated references [94][97]. Commercial reviewers converged on the same fix: gather much more
context before commenting, then verify each comment before posting. CodeRabbit spends 80 to 90% of
its tokens on context enrichment and runs verification agents on every suggestion [83][84][85].
Greptile builds a full code graph first and attaches a confidence score to each comment [81][82].
Qodo's PR-Agent compresses large diffs to fit a budget [89][91].

Takeaway: **precision is the product**. Context gathering and a verification stage matter more
than the reviewing prompt.

## 3. Retrieval over code

### 3.1 Chunking

Fixed-size chunking splits functions and hurts retrieval. AST-aligned chunking (cAST) recursively
splits large nodes and merges small siblings under a size budget, improving Recall@5 by 4.3 points
on RepoEval and SWE-bench Pass@1 by 2.67 [21][22]. A controlled study confirms chunk boundaries
matter for repository-level tasks [23], and production systems chunk syntactically [24][157].

Contextual retrieval (prepending a short description of where a chunk sits) cut failed retrievals
by 49%, and by 67% with reranking [124][125][126]. For code, most of that context is available
deterministically from the syntax tree: file path, enclosing class, signature, imports. No
per-chunk LLM call is needed.

### 3.2 Lexical, dense, or both

Dense retrievers fail silently on exact identifiers and rare strings, which dominate code queries
[114]. CodeRAG-Bench found retrievers struggle when lexical overlap is low, and that generators
cannot always use extra context [5][6]. Hybrid retrieval fused with Reciprocal Rank Fusion is the
default across search engines because it needs no score calibration [109][110][111][112][131].
Sourcegraph moved Cody away from embeddings-only context toward search plus code graph [153][154][156].

### 3.3 Code embedding models

CoIR is the standard code retrieval benchmark, covering 10 datasets and 14 languages [11][12].
Code-specialized small bi-encoders are competitive with much larger general models: CodeRankEmbed
(137M params, 8k context) [16][17], jina-embeddings-v2-base-code (161M, 30 languages) [252][253],
CodeSage and CodeXEmbed families [13][19]. Qwen3-Embedding-0.6B is strong but heavier [256][258].
The 7B nomic-embed-code is state of the art and far too large for CPU serving [16][18]. ONNX
runtimes such as FastEmbed make small models practical on CPU [245][246][247].

### 3.4 Reranking

Cross-encoder reranking over a wide candidate set is the highest-leverage quality step in RAG
[122][123][134]. Code-aware options that run on CPU include jina-reranker-v2-base-multilingual,
trained with code search data [254][255]. Qwen3-Reranker-0.6B is stronger but slower [257].
SweRank shows listwise reranking helps issue localization specifically [121].

### 3.5 Structure: graphs beat free text

Graph-based repository retrieval consistently beats flat chunk retrieval. RepoGraph adds a
line-level code graph and improves SWE-bench agents by 32.8% relative [28]. CodexGraph lets an
agent query a code graph database [27]. LocAgent builds a heterogeneous graph of files, classes,
functions, imports, calls and inheritance, and reaches 92.7% file-level localization [42][43][44].
CoSIL searches the module call graph and then the function call graph with context pruning [46][47].
OrcaLoca, GraphLocator, ARISE, LARGER and knowledge-graph approaches point the same way
[29][48][49][50][4][3].

Importantly, graphs derived from the syntax tree are more reliable than graphs extracted by an LLM
[30]. Tree-sitter provides fast, error-tolerant parsing and tag queries for definitions and
references across 40+ languages [135][136][137][138][25]. Exact name resolution needs heavier
machinery: stack graphs [139][140][141] or SCIP indexers built on type checkers [142][143][144][145].

Aider shows how far a cheap structural signal goes: a tree-sitter symbol graph ranked with
personalized PageRank produces a compact repository map that fits a token budget [148][149][150][151][152].

### 3.6 Git history is a retrieval signal

Behavioral code analysis ranks files by churn times complexity (hotspots), and uses change
coupling to reveal hidden dependencies between files that change together [104][105][106][107][108].
Just-in-time defect prediction uses change features to score risky commits [98][99][100][101][102][103].
SZZ and its successors link fixes to the commits that introduced bugs [217][218][219][220][221][222][223][224][225].

### 3.7 Iteration and agents

Iterative retrieve-then-generate beats one-shot retrieval [9][10]. Agent-computer interfaces
(purpose-built tools for the model) change outcomes more than prompt wording [31][32][177].
AutoCodeRover exposes AST-level search APIs such as `search_class` and `search_method_in_class`
[38][39][40]. Agentless shows a fixed hierarchical pipeline (file, then function, then line) is
competitive with free-form agents at far lower cost [34][35]. Anthropic's guidance is to start
with workflows and add agency only where it pays [176], and to keep context minimal and high
signal [170][171][172][173].

### 3.8 Why not just send the whole repository

Performance degrades with context length in every frontier model tested [166][167][168][169].
Models attend poorly to the middle of long inputs [162][163][164][165]. Coding benchmarks at 1M
tokens confirm the drop [70][174]. Retrieval is still necessary.

## 4. Static analysis plus LLMs

Neuro-symbolic pipelines outperform either part alone. IRIS uses an LLM to infer taint
specifications and to filter CodeQL alerts, detecting 103.7% more known vulnerabilities and
cutting false positives by up to 80% [226][227][228][229]. Semgrep runs fast pattern rules across
30+ languages and has moved to LLM triage behind an evidence gate [263][264][265]. CodeRabbit feeds
40+ linters into its context [85].

## 5. Verification and self-correction

Chain-of-Verification asks independent verification questions about a draft and reduces
hallucination [230][231][232]. Self-Refine and Reflexion improve outputs through feedback without
training [237][238][239][240]. For review, the analogue is a verifier that checks each finding
against retrieved evidence before it is shown.

## 6. Security of a public code-reading service

Repositories are untrusted input. Indirect prompt injection through code comments, READMEs and
issues is an active attack on coding agents [199][200][201][202][203][205]. A reviewer should read
and never act [204]. `git clone` itself has had remote code execution bugs through submodules,
symlinks and hooks [206][207][208][209].

## 7. Evaluation

### 7.1 Benchmarks and their limits

SWE-bench Verified is contaminated and partly mis-specified [54][55][56]. Live and harder
successors exist: SWE-bench-Live, SWE-Bench Pro, SWE-Bench++ [51][52][53][266][267][268].
Benchmarks drift from real agentic work [67][269]. Code-review benchmarks are fragmented
[58]. Recent ones add repository context: AACR-Bench, SWE Context Bench, CR-Bench, SWR-Bench
[65][66][93][94]. Vendors benchmark themselves and always win [211].

### 7.2 Constructing ground truth from history

Reverting a real bug fix produces a realistic buggy change whose correct location is known
[212][216]. Qodo injected issues into real merged PRs [210]. Execution-backed arenas score
detection separately from fix validity [213][214]. Repository QA sets such as SWE-QA provide
question and answer pairs over real repos [68][69].

### 7.3 Judges and reliability

LLM judges show position, verbosity and self-preference bias [186][187][188][189][190]. The
recommended practice is binary pass or fail judgments aligned against a small set of human labels
[196][197][198]. Agent outcomes vary run to run, so reliability should be reported as pass^k
[191][192][193][194][195].

### 7.4 Observability

Phoenix ingests OpenTelemetry traces using OpenInference conventions, which define retriever,
reranker, LLM and tool span kinds [178][179][180][181][182]. RAG-specific metrics such as
faithfulness and context relevance come from Ragas-style evaluators [183][184][185].

## 8. Serving on small hardware

Qdrant supports int8 scalar quantization (4x smaller) with originals on disk and quantized vectors
in RAM [127][128][129][130], and a Query API that fuses sparse and dense prefetches with RRF
[131][132][133]. SQLite FTS5 provides BM25 ranking and custom tokenizers in-process [242][243][244].
Embedded vector search (sqlite-vec, USearch) is a viable fallback [275][276][277]. Cursor caches
embeddings by chunk content hash and syncs with a Merkle tree, so unchanged code is never
re-embedded [157][158][159][160]; CocoIndex applies the same incremental idea [161]. Blobless
partial clones fetch history without file contents and cut clone time sharply [260][261][262].
GitHub's REST API allows 5,000 authenticated requests per hour and caps PR file listings at 3,000
files [248][249][250][251].

## 9. Conclusions that drive the design

1. Chunk by syntax tree, and generate chunk context deterministically from the tree [21][124].
2. Retrieve with three signals (lexical, dense, structural) and fuse with RRF [109][114][28].
3. Treat git history (co-change, churn, blame) as a first-class retrieval channel [104][107].
4. Use a mostly fixed workflow with a bounded agentic investigation step, not a free agent [34][176].
5. Feed static analyzer output in as evidence, and let the model triage it [226][265].
6. Verify every finding against evidence before showing it; optimize precision [85][94][230].
7. Treat repository text as data, never instructions; never execute repository code [199][204][206].
8. Build ground truth from real history (reverted fixes) and report retrieval, detection,
   precision and pass^k separately, with the judge calibrated on human labels [212][191][196].

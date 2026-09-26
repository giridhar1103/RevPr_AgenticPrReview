# Bibliography

Every source consulted during the research phase (September 2026). Numbers match the `[n]` citations in [`README.md`](README.md).

1. [Retrieval-Augmented Code Generation: A Survey with Focus on Repository-Level Approaches (Tao et al. 2026)](https://arxiv.org/abs/2510.04905). survey; graph vs non-graph RAG; 853 papers screened
2. [TICoder: Repository-Level Code Generation with Test-Driven Planning](https://arxiv.org/pdf/2606.08135). repo-level gen
3. [Context Retrieval via Partial Dependency Graph for Repository-Level Code Generation](https://arxiv.org/pdf/2608.01927). dependency-graph retrieval
4. [Context-Augmented Code Generation Using Programming Knowledge Graphs](https://arxiv.org/pdf/2601.20810). PKG retrieval
5. [CodeRAG-Bench: Can Retrieval Augment Code Generation? (NAACL Findings 2025)](https://aclanthology.org/2025.findings-naacl.176/). retrievers struggle with low lexical overlap
6. [CodeRAG-Bench arXiv](https://arxiv.org/abs/2406.14497)
7. [CodeRAG-Bench code](https://github.com/code-rag-bench/code-rag-bench)
8. [CodeRAG-Bench site](https://code-rag-bench.github.io/)
9. [RepoCoder: Repository-Level Code Completion Through Iterative Retrieval and Generation (EMNLP 2023)](https://aclanthology.org/2023.emnlp-main.151/). iterative retrieve-generate beats one-shot
10. [RepoCoder arXiv](https://arxiv.org/abs/2303.12570). RepoEval benchmark
11. [CoIR: A Comprehensive Benchmark for Code Information Retrieval (ACL 2025)](https://arxiv.org/abs/2407.02883). 10 datasets, 14 languages
12. [CoIR code](https://github.com/coir-team/coir)
13. [CodeXEmbed: Generalist Embedding Model Family for Code Retrieval](https://arxiv.org/pdf/2411.12644)
14. [CORE-Bench: Code Retrieval in the Era of Agentic Coding](https://arxiv.org/pdf/2606.11864). agentic code retrieval benchmark
15. [Granite Embedding R2 Models](https://arxiv.org/pdf/2508.21085). code-capable small embedder
16. [Nomic Embed Code: State-of-the-Art Code Retriever](https://www.nomic.ai/news/introducing-state-of-the-art-nomic-embed-code). 7B code embedder; CoRNStack
17. [nomic-ai/CodeRankEmbed model card](https://huggingface.co/nomic-ai/CodeRankEmbed/blob/1b6c1978d5308da3eb901b57d73cea914ebd6be8/README.md). 137M, 8192 ctx
18. [nomic-ai/nomic-embed-code model card](https://huggingface.co/nomic-ai/nomic-embed-code)
19. [6 Best Code Embedding Models Compared (Modal)](https://modal.com/blog/6-best-code-embedding-models-compared)
20. [From Code Foundation Models to Agents and Applications: Survey of Code Intelligence](https://arxiv.org/pdf/2511.18538)
21. [cAST: Structural Chunking via Abstract Syntax Tree (EMNLP Findings 2025)](https://arxiv.org/abs/2506.15655). +4.3 Recall@5 RepoEval
22. [cAST ACL Anthology](https://aclanthology.org/2025.findings-emnlp.430/)
23. [How Does Chunking Affect Retrieval-Augmented Code Completion? Controlled Study](https://arxiv.org/pdf/2605.04763)
24. [code-chunk: AST-Aware Code Chunking (supermemory)](https://supermemory.ai/blog/building-code-chunk-ast-aware-code-chunking/)
25. [Codebase-Memory: Tree-Sitter-Based Knowledge Graphs for LLM Code Exploration via MCP](https://arxiv.org/html/2603.27277v1). tree-sitter KG
26. [CodeCompass: Navigating the Navigation Paradox in Agentic Code Intelligence](https://arxiv.org/pdf/2602.20048)
27. [CodexGraph: Bridging LLMs and Code Repositories via Code Graph Databases (NAACL 2025)](https://arxiv.org/abs/2408.03910). graph DB queries by agent
28. [RepoGraph: Repository-level Code Graph (ICLR 2025)](https://arxiv.org/html/2410.14684v1). +32.8% rel on SWE-bench
29. [LARGER: Lexically Anchored Repository Graph Exploration and Retrieval](https://arxiv.org/pdf/2605.16352). lexical anchors + graph
30. [Reliable Graph-RAG for Codebases: AST-Derived Graphs vs LLM-Extracted KGs](https://arxiv.org/pdf/2601.08773). AST graphs more reliable than LLM KGs
31. [SWE-agent: Agent-Computer Interfaces (NeurIPS 2024)](https://arxiv.org/abs/2405.15793). ACI design matters
32. [SWE-agent NeurIPS proceedings](https://proceedings.neurips.cc/paper_files/paper/2024/file/5a7c947568c1b1328ccc5230172e1e7c-Paper-Conference.pdf)
33. [SWE-Bench-CL: Continual Learning for Coding Agents](https://arxiv.org/pdf/2507.00014)
34. [Agentless: Demystifying LLM-based Software Engineering Agents (FSE 2025)](https://arxiv.org/abs/2407.01489). hierarchical localization file->function->line, no agent
35. [Agentless ACM PACMSE](https://dl.acm.org/doi/full/10.1145/3715754)
36. [SHERLOC: Structured Diagnostic Localization for Code Repair Agents](https://arxiv.org/pdf/2606.24820)
37. [PatchPilot: Cost-Efficient Software Engineering Agent](https://arxiv.org/pdf/2502.02747)
38. [AutoCodeRover: Autonomous Program Improvement (ISSTA 2024)](https://dl.acm.org/doi/abs/10.1145/3650212.3680384). AST-level search APIs search_class/search_method
39. [AutoCodeRover arXiv](https://arxiv.org/abs/2404.05427)
40. [AutoCodeRover repo](https://github.com/AutoCodeRoverSG/auto-code-rover)
41. [Inside the Scaffold: A Source-Code Taxonomy of Coding Agent Architectures](https://arxiv.org/pdf/2604.03515)
42. [LocAgent: Graph-Guided LLM Agents for Code Localization (ACL 2025)](https://aclanthology.org/2025.acl-long.426/). heterogeneous graph; SearchEntity/TraverseGraph/RetrieveEntity
43. [LocAgent arXiv](https://arxiv.org/abs/2503.09089). 92.7% file-level localization
44. [LocAgent code](https://github.com/gersteinlab/LocAgent)
45. [Learning Adaptive Parallel Execution for Efficient Code Localization](https://arxiv.org/pdf/2601.19568)
46. [CoSIL: Issue Localization via LLM-Driven Iterative Code Graph Searching (ASE 2025)](https://arxiv.org/abs/2503.22424). module call graph then function call graph, context pruning
47. [CoSIL code](https://github.com/ZhonghaoJiang/CoSIL)
48. [GraphLocator: Graph-guided Causal Reasoning for Issue Localization](https://arxiv.org/html/2512.22469v1)
49. [ARISE: Repository-level Graph Representation and Toolset for Agentic Program Repair](https://arxiv.org/pdf/2605.03117)
50. [OrcaLoca: LLM Agent Framework for Software Issue Localization (ICML 2025)](https://github.com/fishmingyu/OrcaLoca)
51. [SWE-bench-Live dataset](https://huggingface.co/datasets/SWE-bench-Live/SWE-bench-Live). contamination-resistant monthly tasks
52. [SWE-bench-Live leaderboard](https://swe-bench-live.github.io/)
53. [SWE-Bench++: Scalable Generation of SWE Benchmarks](https://arxiv.org/pdf/2512.17419)
54. [SWE-bench Verified review (Epoch AI)](https://epoch.ai/benchmarks/swe-bench-verified/review)
55. [Why SWE-bench Verified no longer measures frontier coding capabilities (OpenAI)](https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/). contamination, flawed tests
56. [Cross-Context Verification: Detection of Benchmark Contamination](https://arxiv.org/pdf/2603.21454)
57. [SWE-bench overview](https://www.swebench.com/SWE-bench/)
58. [A Survey of Code Review Benchmarks and Evaluation Practices in Pre-LLM and LLM Era](https://arxiv.org/abs/2602.13377). 99 papers 2015-2025
59. [Evaluating LLM-Generated Code: A Benchmark and Developer Study](https://arxiv.org/html/2605.09059v1)
60. [Context-Aware Code Review Automation: A Retrieval-Augmented Approach (Applied Sciences 2026)](https://www.mdpi.com/2076-3417/16/4/1875). RAG for review comments
61. [Rethinking Code Review Workflows with LLM Assistance (IEEE)](https://ieeexplore.ieee.org/abstract/document/11323409/). devs prefer AI-led review on large/unfamiliar PRs
62. [CodeReviewer: Automating Code Review Activities by Large-Scale Pre-training (FSE 2022)](https://arxiv.org/abs/2203.09095). quality estimation, comment gen, refinement
63. [CodeReviewer ACM](https://dl.acm.org/doi/10.1145/3540250.3549081)
64. [CodeReviewer README](https://github.com/microsoft/CodeBERT/blob/master/CodeReviewer/README.md)
65. [SWE Context Bench: Context Learning in Coding](https://arxiv.org/abs/2602.08316)
66. [AACR-Bench: Automatic Code Review with Holistic Repository-Level Context](https://arxiv.org/pdf/2601.19494). repo-level context for review
67. [Code Benchmarks Should Prioritize Rigor, Reliability, and Reproducibility](https://arxiv.org/pdf/2501.10711)
68. [SWE-QA: Dataset and Benchmark for Complex Code Understanding](https://arxiv.org/pdf/2604.24814)
69. [SWE-QA: Can LMs Answer Repository-level Code Questions?](https://arxiv.org/pdf/2509.14635). 720 QA over 15 repos
70. [LongCodeBench: Coding LLMs at 1M Context](https://arxiv.org/pdf/2505.07897)
71. [Resolving code review comments with ML (Google Research blog)](https://research.google/blog/resolving-code-review-comments-with-ml/). 7.5% of reviewer comments resolved by ML edit
72. [Resolving Code Review Comments with Machine Learning (ICSE-SEIP 2024)](https://dl.acm.org/doi/10.1145/3639477.3639746)
73. [Go Home Copilot, You're Drunk: Developer Responses to Agent-Generated Code Review Comments](https://arxiv.org/pdf/2607.21997). developer reactions to AI review
74. [AI-Assisted Assessment of Coding Practices in Modern Code Review (Google AutoCommenter)](https://arxiv.org/abs/2405.13565). best-practice comments at scale
75. [AI-Assisted Fixes to Code Review Comments at Scale (Meta)](https://arxiv.org/pdf/2507.13499)
76. [Automating Low-Risk Code Review at Meta: RADAR, Risk Calibration](https://arxiv.org/html/2605.30208v1). layered automation: policy gates, risk scoring, LLM review, deterministic validation
77. [Rethinking Code Review Workflows with LLM Assistance: An Empirical Study](https://arxiv.org/pdf/2505.16339)
78. [Meta structured prompting for code review (VentureBeat)](https://venturebeat.com/orchestration/metas-new-structured-prompting-technique-makes-llms-significantly-better-at). structured reasoning templates
79. [Meta structured prompts for code review (InfoWorld)](https://www.infoworld.com/article/4153054/meta-shows-structured-prompts-can-make-llms-more-reliable-for-code-review.html)
80. [BitsAI-CR: Automated Code Review via LLM in Practice (ByteDance)](https://arxiv.org/pdf/2501.15134). two-stage generate + filter; outdated-rate metric
81. [AI Code Reviews Need Codebase Context (Greptile)](https://www.greptile.com/blog/ai-reviews-need-context). code graph before review
82. [Greptile docs overview](https://www.greptile.com/docs/introduction)
83. [Context Engineering: Level up your AI Code Reviews (CodeRabbit)](https://www.coderabbit.ai/blog/context-engineering-ai-code-reviews)
84. [The art and science of context engineering (CodeRabbit)](https://www.coderabbit.ai/blog/the-art-and-science-of-context-engineering). 80-90% tokens on context enrichment
85. [Explainable AI Code Reviews: Inside CodeRabbit's Context Engine](https://www.coderabbit.ai/blog/explainable-reviews-coderabbit-review-context-engine). verification agents
86. [See the Context Behind Every CodeRabbit Review Comment](https://www.coderabbit.ai/blog/context-behind-code-review-comments)
87. [Case Study: CodeRabbit on LanceDB](https://www.lancedb.com/blog/case-study-coderabbit)
88. [Code context: evidence behind trustworthy AI code review (CodeRabbit guide)](https://www.coderabbit.ai/guides/code-context)
89. [PR-Agent docs](https://docs.pr-agent.ai/). PR compression strategy
90. [PR-Agent repo (community)](https://github.com/The-PR-Agent/pr-agent)
91. [How Qodo PR-Agent compresses large code changes](https://thamizhelango.medium.com/how-qodo-pr-agent-smartly-compresses-and-reviews-large-code-changes-72db8898f622)
92. [Qodo Code Review docs](https://docs.qodo.ai/code-review)
93. [SWR-Bench: LLM Performance in Real-World Code Review Comment Generation](https://arxiv.org/pdf/2509.01494)
94. [CR-Bench: Real-World Utility of AI Code Review Agents](https://arxiv.org/html/2603.11078v1)
95. [The false positive problem in AI code reviewers (cubic)](https://www.cubic.dev/blog/the-false-positive-problem-why-most-ai-code-reviewers-fail-and-how-cubic-solved-it)
96. [Framework to Measure Signal vs Noise in AI Code Review](https://jetxu-llm.github.io/posts/low-noise-code-review/)
97. [LLM Hallucinations in AI Code Review (diffray)](https://diffray.ai/blog/llm-hallucinations-code-review/)
98. [Explaining Risk of Code Changes using LLM-Based Prediction Models](https://arxiv.org/abs/2607.02782). diff risk score attention highlighting
99. [ReDef: Do Code LMs Understand Code Changes for JIT Defect Prediction?](https://dl.acm.org/doi/10.1145/3808179)
100. [CodeFlowLM: Incremental JIT Defect Prediction with PLMs](https://arxiv.org/html/2512.00231)
101. [Deployment Risk Assessment Using Diff-Aware Features (Prime Video)](https://arxiv.org/pdf/2607.06766)
102. [Feature Sets in Just-in-Time Defect Prediction](https://arxiv.org/pdf/2209.13978)
103. [Investigation of Dataset Features for JIT Defect Prediction](https://arxiv.org/pdf/2109.13634)
104. [Change coupling: visualize the cost of change (CodeScene)](https://codescene.com/blog/change-coupling-visualize-the-cost-of-change)
105. [Behavioral Code Analysis (CodeScene)](https://codescene.com/product/behavioral-code-analysis)
106. [Enhancing Hotspot Detection with Behavioral Analysis and AI-Assisted Code Review](https://link.springer.com/chapter/10.1007/978-3-032-09318-9_25)
107. [Your Code as a Crime Scene (Tornhill)](http://www.r-5.org/files/books/computers/dev-teams/trenches/Adam_Tornhill-Your_Code_as_a_Crime_Scene-EN.pdf). hotspots = churn x complexity
108. [Git Hotspot Analysis (repowise)](https://repowise.dev/blog/guides/git-hotspot-analysis-risky-files)
109. [Reciprocal Rank Fusion outperforms Condorcet and Individual Rank Learning Methods (SIGIR 2009)](https://dl.acm.org/doi/10.1145/1571941.1572114). RRF k=60
110. [RRF paper PDF (Cormack)](https://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf)
111. [Reciprocal Rank Fusion explained](https://blog.serghei.pl/posts/reciprocal-rank-fusion-explained/)
112. [Advanced RAG: Understanding RRF in Hybrid Search (Laforge)](https://glaforge.dev/posts/2026/02/10/advanced-rag-understanding-reciprocal-rank-fusion-in-hybrid-search/)
113. [Exact Adaptive Hybrid Retrieval Without Fixed Top-L Cutoffs](https://arxiv.org/pdf/2608.07152)
114. [Hybrid Search in Production: Why BM25 Still Wins on the Queries That Matter](https://tianpan.co/blog/2026/04/12/hybrid-search-production-bm25-dense-embeddings). dense fails silently on identifiers
115. [CeQe: Grounding Lexical Retrieval in Semantic Evidence](https://arxiv.org/pdf/2608.00452)
116. [Hierarchical BM25: Lexical Search at Billion-Document Scale](https://arxiv.org/pdf/2608.00229)
117. [From BM25 to Corrective RAG: Benchmarking Retrieval](https://arxiv.org/pdf/2604.01733)
118. [A Replication Study of Dense Passage Retriever](https://arxiv.org/pdf/2104.05740)
119. [Beyond Retrieval: A Multitask Benchmark and Model for Code Search](https://arxiv.org/pdf/2605.04615)
120. [Beyond Repository Boundaries: Cross-Repository Graph Retrieval for Code Generation](https://arxiv.org/pdf/2609.09987)
121. [SweRank: Software Issue Localization with Code Ranking](https://arxiv.org/pdf/2505.07849). listwise code reranking for localization
122. [Top Reranking Models to Boost RAG Accuracy in 2026 (Redis)](https://redis.io/blog/top-reranking-models-rag-accuracy/)
123. [Advanced RAG Retrieval: Cross-Encoders & Reranking (TDS)](https://towardsdatascience.com/advanced-rag-retrieval-cross-encoders-reranking/)
124. [Contextual Retrieval in AI Systems (Anthropic)](https://www.anthropic.com/engineering/contextual-retrieval). -49% failed retrievals, -67% with rerank
125. [Enhancing RAG with contextual retrieval (Claude Cookbook)](https://platform.claude.com/cookbook/capabilities-contextual-embeddings-guide)
126. [Reconstructing Context: Evaluating Advanced Chunking Strategies for RAG](https://arxiv.org/pdf/2504.19754)
127. [Qdrant Quantization docs](https://qdrant.tech/documentation/manage-data/quantization/). int8 4x; originals on disk + quantized in RAM
128. [Qdrant Scalar Quantization article](https://qdrant.tech/articles/scalar-quantization/)
129. [Qdrant Vector Search Resource Optimization Guide](https://qdrant.tech/articles/vector-search-resource-optimization/)
130. [Reduce Qdrant RAM with on-disk vectors, payloads, quantization](https://oneuptime.com/blog/post/2026-08-28-reduce-qdrant-ram-on-disk-vectors-payloads-quantization/view)
131. [Qdrant Hybrid Queries docs (Query API, prefetch, RRF/DBSF)](https://qdrant.tech/documentation/search/hybrid-queries/)
132. [Qdrant Hybrid Search article](https://qdrant.tech/articles/hybrid-search/)
133. [Qdrant Hybrid Search text-search docs](https://qdrant.tech/documentation/search/text-search/hybrid-search/)
134. [Qdrant hybrid search with reranking tutorial](https://qdrant.tech/documentation/tutorials-search-engineering/reranking-hybrid-search/)
135. [tree-sitter repository](https://github.com/tree-sitter/tree-sitter). incremental error-tolerant parsing
136. [Tree-sitter: How Incremental Parsing Works](https://tomassetti.me/incremental-parsing-using-tree-sitter/)
137. [AST Parsing at Scale: Tree-sitter Across 40 Languages](https://www.dropstone.io/blog/ast-parsing-tree-sitter-40-languages)
138. [Tree-sitter and its queries (Topiary book)](https://topiary.tweag.io/book/getting-started/on-tree-sitter.html)
139. [Stack graphs: Name resolution at scale](https://arxiv.org/abs/2211.01224). file-incremental name resolution
140. [Introducing stack graphs (GitHub Blog)](https://github.blog/open-source/introducing-stack-graphs/)
141. [OpenHands issue: stack graphs for code context](https://github.com/OpenHands/OpenHands/issues/742)
142. [SCIP Code Intelligence Protocol repo](https://github.com/sourcegraph/scip/tree/main)
143. [SCIP: a better code indexing format than LSIF (Sourcegraph)](https://sourcegraph.com/blog/announcing-scip)
144. [scip-python: a precise Python indexer (Sourcegraph)](https://sourcegraph.com/blog/scip-python). built on Pyright
145. [scip-python repo](https://github.com/sourcegraph/scip-python)
146. [Cross-repository code navigation (Sourcegraph)](https://sourcegraph.com/blog/cross-repository-code-navigation)
147. [SCIP site](https://scip-code.org/)
148. [Building a better repository map with tree sitter (Aider)](https://aider.chat/2023/10/22/repomap.html). tree-sitter tags + PageRank, token budget
149. [How Aider's repomap uses PageRank](https://anishgandhi.com/aider-pagerank-codebase-ranking/). personalized PageRank
150. [Repository Map Pattern: AST + PageRank (AgentPatterns)](https://agentpatterns.ai/context-engineering/repository-map-pattern/)
151. [RepoMapper](https://github.com/pdavis68/RepoMapper)
152. [goldfish: token-budgeted repo maps](https://github.com/dereira/goldfish)
153. [How Cody understands your codebase (Sourcegraph)](https://sourcegraph.com/blog/how-cody-understands-your-codebase). moved from embeddings to search-based context
154. [How Cody provides remote repository awareness](https://sourcegraph.com/blog/how-cody-provides-remote-repository-context)
155. [Cody Context docs](https://sourcegraph.com/docs/cody/core-concepts/context)
156. [AI-assisted Coding with Cody: Lessons from Context Retrieval and Evaluation](https://arxiv.org/html/2408.05344v1)
157. [Securely indexing large codebases (Cursor)](https://cursor.com/blog/secure-codebase-indexing). merkle tree, content-hash embedding cache
158. [How Cursor Actually Indexes Your Codebase (TDS)](https://towardsdatascience.com/how-cursor-actually-indexes-your-codebase/)
159. [How Cursor Indexes Codebases Fast (Engineer's Codex)](https://read.engineerscodex.com/p/how-cursor-indexes-codebases-fast)
160. [Cursor semantic search: 12.5% better agent accuracy](https://www.digitalapplied.com/blog/cursor-semantic-search-coding-ai-guide)
161. [Index Your Codebase for AI Agents with CocoIndex](https://cocoindex.io/blogs/index-codebase-v1/). incremental indexing
162. [Lost in the Middle: How Language Models Use Long Contexts (TACL 2024)](https://aclanthology.org/2024.tacl-1.9/). U-shaped position curve
163. [Lost in the Middle arXiv](https://arxiv.org/abs/2307.03172)
164. [Found in the Middle: Plug-and-Play Positional Encoding](https://arxiv.org/html/2403.04797v1)
165. [Lost in the Middle, and In-Between: Multi-Hop QA](https://arxiv.org/pdf/2412.10079)
166. [Context Rot guide (Morph)](https://www.morphllm.com/context-rot). Chroma study: 18 models degrade with length
167. [Context Rot notes (Hamel)](https://hamel.dev/notes/llm/rag/p6-context_rot.html)
168. [Diagnosing and Mitigating Context Rot in Long-horizon Search](https://arxiv.org/pdf/2606.29718)
169. [APCE: Adaptive Progressive Context Expansion](https://arxiv.org/pdf/2510.12051)
170. [Effective context engineering for AI agents (Anthropic)](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents). minimal high-signal tokens; curated tool sets
171. [Context engineering: memory, compaction, tool clearing (Claude Cookbook)](https://platform.claude.com/cookbook/tool-use-context-engineering-context-engineering-tools)
172. [Context Engineering for Agents (LangChain)](https://www.langchain.com/blog/context-engineering-for-agents)
173. [Context Engineering: A Practical Guide for AI Agents (Sourcegraph)](https://sourcegraph.com/blog/context-engineering)
174. [LOCA-bench: Language Agents Under Extreme Context Growth](https://arxiv.org/pdf/2602.07962)
175. [Everything is Context: Agentic File System Abstraction](https://arxiv.org/pdf/2512.05470)
176. [Building Effective AI Agents (Anthropic)](https://www.anthropic.com/engineering/building-effective-agents). workflows vs agents; simplest thing first
177. [Writing effective tools for AI agents (Anthropic)](https://www.anthropic.com/engineering/writing-tools-for-agents)
178. [OpenInference Semantic Conventions (Phoenix docs)](https://arize.com/docs/phoenix/tracing/concepts-tracing/otel-openinference/semantic-conventions). RETRIEVER/RERANKER/LLM/TOOL span kinds
179. [OpenInference semantic_conventions spec](https://github.com/Arize-ai/openinference/blob/main/spec/semantic_conventions.md)
180. [OpenInference Specification](https://arize-ai.github.io/openinference/spec/)
181. [OpenInference issue: span-level context confidence in multi-hop RAG](https://github.com/Arize-ai/openinference/issues/3256)
182. [Arize Phoenix LLM tracing + evaluations guide 2026](https://qaskills.sh/blog/arize-phoenix-llm-observability-tracing-evaluations-2026)
183. [Ragas: Automated Evaluation of RAG (EACL 2024 demo)](https://aclanthology.org/2024.eacl-demo.16/). faithfulness, context relevance
184. [Ragas arXiv](https://arxiv.org/abs/2309.15217)
185. [A Systematic Review of Key RAG Systems](https://arxiv.org/pdf/2507.18910)
186. [Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena](https://arxiv.org/abs/2306.05685). position, verbosity, self-enhancement bias
187. [Reliability without Validity: Large-Scale Evaluation of LLM-as-a-Judge](https://arxiv.org/pdf/2606.19544)
188. [Judging the Judges: Bias Mitigation Strategies in LLM-as-a-Judge](https://arxiv.org/pdf/2604.23178)
189. [The Coin Flip Judge? Reliability and Bias in LLM-as-a-Judge](https://arxiv.org/pdf/2606.13685)
190. [LLM-as-a-judge guide (Evidently)](https://www.evidentlyai.com/llm-guide/llm-as-a-judge)
191. [tau-bench: Tool-Agent-User Interaction Benchmark](https://arxiv.org/abs/2406.12045). pass^k reliability
192. [tau-bench (Sierra blog)](https://sierra.ai/blog/benchmarking-ai-agents)
193. [Noise Floor Audit for Agent Benchmarks](https://arxiv.org/pdf/2608.22331). run-to-run variance
194. [On the Reliability of Computer Use Agents](https://arxiv.org/pdf/2604.17849)
195. [Benchmarking AI Agents: Measuring Trade-offs (Alan)](https://medium.com/alan/benchmarking-ai-agents-stop-trusting-headline-scores-start-measuring-trade-offs-0fdae3a418cf)
196. [Using LLM-as-a-Judge For Evaluation: A Complete Guide (Hamel)](https://hamel.dev/blog/posts/llm-judge/). critique shadowing, binary pass/fail
197. [AI Evals FAQ (Hamel)](https://hamel.dev/blog/posts/evals-faq/)
198. [A pragmatic guide to LLM evals for devs (Pragmatic Engineer)](https://newsletter.pragmaticengineer.com/p/evals)
199. [Mozilla warns of indirect prompt injection in AI coding agents](https://www.helpnetsecurity.com/2026/06/29/mozilla-warns-of-indirect-prompt-injection-risk-in-ai-coding-agents/)
200. [Prompt Injection Against Coding Agents (Endor Labs)](https://www.endorlabs.com/learn/prompt-injection-against-coding-agents-the-attack-surface-nobody-owns)
201. [CSA research note: claude-code-action prompt injection](https://labs.cloudsecurityalliance.org/research/csa-research-note-claude-code-github-action-prompt-injection/). issue -> injection -> exfiltration
202. [Workspace Topology as an Attack Vector in Agentic Coding Assistants](https://arxiv.org/pdf/2608.14876)
203. [IterInject: Indirect Prompt Injection Against LLM Agents](https://arxiv.org/pdf/2605.24659)
204. [Parallax: Why AI Agents That Think Must Never Act](https://arxiv.org/pdf/2604.12986). separate reasoning from acting
205. [Prompt injection attacks on AI agents 2026 (Atlan)](https://atlan.com/know/prompt-injection-attacks-ai-agents/)
206. [CVE-2025-48384 Git arbitrary file write (Datadog Security Labs)](https://securitylabs.datadoghq.com/articles/git-arbitrary-file-write/). submodule + symlink -> hook RCE
207. [Exploiting CVE-2024-32002: RCE via git clone](https://amalmurali.me/posts/git-rce/)
208. [Git security vulnerabilities announced (GitHub Blog)](https://github.blog/open-source/git/git-security-vulnerabilities-announced-6/)
209. [Securing Git: 5 new vulnerabilities (GitHub Blog)](https://github.blog/open-source/git/securing-git-addressing-5-new-vulnerabilities/)
210. [How Qodo Built a Real-World Benchmark for AI Code Review](https://www.qodo.ai/blog/how-we-built-a-real-world-benchmark-for-ai-code-review/). injected issues into real merged PRs
211. [Every AI code review vendor benchmarks itself, and wins (DeepSource)](https://deepsource.com/blog/ai-code-review-benchmarks). vendor benchmark skepticism
212. [FIXREVERTER: Realistic Bug Injection (USENIX Security 2022)](https://www.usenix.org/conference/usenixsecurity22/presentation/zhang-zenong). revert fix patterns
213. [code-review-arena: execution-backed benchmark for review agents](https://github.com/hari-kancharla/code-review-arena)
214. [BugDetectionBench: real-world review comments](https://github.com/moritzWa/BugDetectionBench)
215. [VICBench: Multi-Language Code Vulnerability Detection](https://arxiv.org/html/2608.12246v1)
216. [Extracting Concise Bug-Fixing Patches from Human-Written Patches](https://arxiv.org/pdf/2103.00156)
217. [Evaluating SZZ Implementations: Empirical Study on the Linux Kernel](https://arxiv.org/pdf/2308.05060)
218. [Evaluating SZZ Implementations Through a Developer-informed Oracle](https://arxiv.org/pdf/2102.03300)
219. [V-SZZ (ICSE 2022)](https://dl.acm.org/doi/10.1145/3510003.3510113)
220. [AgenticSZZ: Temporal KG-Guided Agentic Bug-Inducing Commit Identification](https://arxiv.org/html/2602.02934v2)
221. [MAS-SZZ: Multi-Agentic SZZ for Vulnerability-Inducing Commits](https://arxiv.org/html/2604.24398)
222. [Neural SZZ Algorithm (ASE 2023)](https://baolingfeng.github.io/papers/ASE2023.pdf)
223. [On Refining the SZZ Algorithm with Bug Discussion Data](https://pmc.ncbi.nlm.nih.gov/articles/PMC11269517/)
224. [SZZUnleashed](https://github.com/wogscpar/SZZUnleashed)
225. [WIA-SZZ: Work Item Aware SZZ](https://arxiv.org/html/2411.12740)
226. [IRIS: LLM-Assisted Static Analysis for Detecting Security Vulnerabilities](https://arxiv.org/abs/2405.17238). LLM filters static alerts; +103.7% vs CodeQL
227. [IRIS documentation](https://iris-sast.github.io/iris/)
228. [Neuro-symbolic Static Analysis with LLM-generated Vulnerability Patterns](https://arxiv.org/pdf/2504.16057)
229. [LLM-Driven Adaptive Source-Sink Identification and False Positive Mitigation (AdaTaint)](https://arxiv.org/pdf/2511.04023)
230. [Chain-of-Verification Reduces Hallucination in LLMs (ACL Findings 2024)](https://aclanthology.org/2024.findings-acl.212/). independent verification questions
231. [Chain-of-Verification arXiv](https://arxiv.org/abs/2309.11495)
232. [Comprehensive Survey of Hallucination Mitigation Techniques in LLMs](https://arxiv.org/pdf/2401.01313)
233. [Precise Zero-Shot Dense Retrieval without Relevance Labels (HyDE, ACL 2023)](https://aclanthology.org/2023.acl-long.99/)
234. [HyDE arXiv](https://arxiv.org/abs/2212.10496)
235. [Zero-Shot Dense Retrieval with Embeddings from Relevance Feedback](https://arxiv.org/pdf/2410.21242)
236. [HyDE (Haystack docs)](https://docs.haystack.deepset.ai/docs/hypothetical-document-embeddings-hyde)
237. [Self-Refine: Iterative Refinement with Self-Feedback (NeurIPS 2023)](https://arxiv.org/pdf/2303.17651)
238. [Reflexion: Language Agents with Verbal Reinforcement Learning (NeurIPS 2023)](https://proceedings.neurips.cc/paper_files/paper/2023/file/1b44b878bb782e6954cd888628510e90-Paper-Conference.pdf)
239. [MAR: Multi-Agent Reflexion](https://arxiv.org/html/2512.20845)
240. [Internal Consistency and Self-Feedback in LLMs: A Survey](https://arxiv.org/pdf/2407.14507)
241. [The Landscape of Agentic RL for LLMs: A Survey](https://arxiv.org/pdf/2509.02547)
242. [SQLite FTS5 Extension docs](https://sqlite.org/fts5.html). bm25(), trigram, custom tokenizers
243. [sqlite-fts5-trigram (simonw)](https://github.com/simonw/sqlite-fts5-trigram/)
244. [SQLite FTS5 Tokenizers unicode61 and ascii](https://audrey.feldroy.com/articles/2025-01-13-SQLite-FTS5-Tokenizers-unicode61-and-ascii)
245. [FastEmbed docs (Qdrant)](https://qdrant.tech/documentation/fastembed/). ONNX runtime CPU embeddings
246. [FastEmbed article (Qdrant)](https://qdrant.tech/articles/fastembed/)
247. [FastEmbed repo](https://github.com/qdrant/fastembed)
248. [REST API endpoints for pull requests (GitHub Docs)](https://docs.github.com/en/rest/pulls/pulls). 3000-file cap on PR files
249. [Rate limits for the REST API (GitHub Docs)](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api). 5000/h auth; secondary limits
250. [Best practices for using the REST API (GitHub Docs)](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api). conditional requests, ETags
251. [Making the most of GitHub rate limits](https://jamiemagee.co.uk/blog/making-the-most-of-github-rate-limits/)
252. [jina-embeddings-v2-base-code model page](https://jina.ai/models/jina-embeddings-v2-base-code/). 30 languages, 8192 ctx, Apache-2.0
253. [Elevate Your Code Search with New Jina Code Embeddings](https://jina.ai/news/elevate-your-code-search-with-new-jina-code-embeddings/)
254. [jina-reranker-v2-base-multilingual (HF)](https://huggingface.co/jinaai/jina-reranker-v2-base-multilingual). cross-encoder incl. code search
255. [Jina Reranker v2 for Agentic RAG (code search, function calling)](https://jina.ai/news/jina-reranker-v2-for-agentic-rag-ultra-fast-multilingual-function-calling-and-code-search/)
256. [Qwen3 Embedding: Advancing Text Embedding and Reranking](https://arxiv.org/abs/2506.05176). 0.6B/4B/8B
257. [Qwen3-Reranker-0.6B (HF)](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B)
258. [Qwen3-Embedding repo](https://github.com/QwenLM/Qwen3-Embedding)
259. [Qwen3-VL-Embedding and Qwen3-VL-Reranker](https://arxiv.org/abs/2601.04720)
260. [Get up to speed with partial clone and shallow clone (GitHub Blog)](https://github.blog/open-source/git/get-up-to-speed-with-partial-clone-and-shallow-clone/). blobless vs treeless
261. [Git clone: a data-driven study on cloning behaviors (GitHub Blog)](https://github.blog/open-source/git/git-clone-a-data-driven-study-on-cloning-behaviors/)
262. [Git Partial Clone in Azure DevOps](https://devblogs.microsoft.com/devops/git-partial-clone-now-supported-in-azure-devops/). 88.6% faster clones
263. [Semgrep repo](https://github.com/semgrep/semgrep). 30+ languages, pattern rules
264. [Semgrep Community Edition](https://semgrep.dev/products/community-edition/)
265. [Comparing Open-Source AI Code Security Harnesses (Semgrep)](https://semgrep.dev/blog/2026/comparing-open-source-ai-code-security-harnesses/). LLM triage behind evidence gate
266. [SWE-Bench Pro (Scale Labs)](https://scale.com/research/swe_bench_pro)
267. [SWE-Bench Pro: Can AI Agents Solve Long-Horizon SWE Tasks?](https://arxiv.org/pdf/2509.16941). multi-file, 107 LOC avg
268. [SWE-bench Pro dataset](https://huggingface.co/datasets/ScaleAI/SWE-bench_Pro)
269. [Position: Coding Benchmarks Are Misaligned with Agentic Software Engineering](https://arxiv.org/pdf/2606.17799)
270. [Characteristics of Useful Code Reviews: An Empirical Study at Microsoft (Bosu et al.)](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/bosu2015useful.pdf). useful = led to change; effectiveness drops with more files
271. [Exploring the Advances in Identifying Useful Code Review Comments](https://arxiv.org/abs/2307.00692)
272. [Predicting Usefulness of Code Review Comments](https://web.cs.dal.ca/~masud/papers/masud-MSR2017a.pdf)
273. [Expectations, Outcomes, and Challenges of Modern Code Review (ICSE 2013)](https://www.microsoft.com/en-us/research/publication/expectations-outcomes-and-challenges-of-modern-code-review/). understanding the change is the core need
274. [Rethinking Code Review in the Age of AI: A Vision for Agentic Code Review](https://arxiv.org/pdf/2605.17548)
275. [How sqlite-vec Works](https://medium.com/@stephenc211/how-sqlite-vec-works-for-storing-and-querying-vector-embeddings-165adeeeceea)
276. [MonaVec: Training-Free Embedded Vector Search Kernel](https://arxiv.org/pdf/2606.19458)
277. [Implementing vector search in SQLite](https://tpoe.dev/blog/vector-search-sqlite)

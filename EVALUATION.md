# PE6201 evaluation and submission evidence

> 历史记录，**不是当前版本的评测报告**。下文 20/20 来自已废弃的预设关系、指标提示和模拟 `events` 数据；当前版本已移除这些设定，旧成绩不可用于最终作业结论。当前版本尚未完成独立盲测，真实性能未知。以下旧版描述仅用于审计对比。

## What is actually built

InsightSQL uses OpenRouter-hosted `openai/gpt-4o-mini` directly. **Vanna, embeddings, a vector database and retrieval-augmented generation are not used.** At query time, the application reads SQLite table/column names, low-cardinality stored values, date ranges, known demo-table joins and metric definitions; the LLM generates SQL; the server validates a read-only query, executes it, retries once after a SQL execution error, selects a chart, and requests a result-based narrative. This is schema-grounded prompting with execution feedback, not Vanna. The model-serving layer is rented; CSV/API ingestion, local SQLite data, orchestration, guardrails, BI rendering and evaluation are built locally.

## Frozen benchmark and method

`eval_cases.json` defines 20 questions: 18 answerable questions with reference SQLite queries and 2 unanswerable questions requiring advertising-spend or refund data. They cover aggregation, filters, category-value translation, multi-table joins, repeat purchasers, time-series and DAU/MAU. The benchmark was written **after the first prototype existed**, so it is a retrospective development set, not honestly a pre-build or held-out test. It is now fixed for repeatability. The source named in the original proposal is the [Kaggle Global E-Commerce Sales Analysis dataset](https://www.kaggle.com/datasets/bibirehana/global-e-commarce-sales-data-analysis); licence and permitted redistribution still need verification before publishing the CSV elsewhere.

`python evaluate.py --mode both --output eval_results.json` creates a temporary SQLite database from the provided Kaggle CSV; it does not modify the live workspace. The same model and `temperature=0` are used for both arms. Baseline gets the question and generic SQL instructions, **no schema**. System gets the application's real prompt and execution flow, including the optional SQL repair and result narrative. SQL is scored by executing against the same snapshot and comparing result values with 0.02 absolute tolerance, not by exact SQL text. Unanswerable cases are scored separately for explicit refusal. The full raw responses, SQL, status, latency, token counts and API-reported cost are in `eval_results.json`; the API key is not recorded.

| Measure (20 questions, 30 Sep 2026) | Raw LLM, no schema | Current system |
|---|---:|---:|
| Answerable result accuracy | 2/18 | 18/18 |
| Appropriate refusal | 2/2 | 2/2 |
| Combined task outcome | 4/20 | 20/20 |
| Executable answerable queries | 3/18 | 18/18 |
| Mean end-to-end latency | 1.94 s | 3.56 s |
| Mean OpenRouter inference cost/question | US$0.0000314 | US$0.00026218 |

Cost calculation: system US$0.00524355 total OpenRouter-reported cost ÷ 20 questions = **US$0.00026218 per question**; baseline US$0.00062805 ÷ 20 = **US$0.0000314**. System cost includes the SQL-generation and narrative calls, and any repair call, but excludes local compute, hosting and human review. Provider/model pricing and routing can change; report the measured cost, not a permanent tariff. OpenRouter documents that `usage: {"include": true}` returns request usage/cost information: [OpenRouter support](https://openrouter.ai/support/).

## Failure analysis and limits

- An earlier development run scored 16/18 answerable questions: the LLM returned one row per repeat customer instead of counting those customers (Q11), and falsely refused the 2023/2024 comparison (Q17). The general grouped-count instruction and observed date ranges fixed these on the development set. This tuning makes the final 18/18 **optimistic**; it is not a blind test.
- The final SQL score does **not** mean the full answer is correct. In Q04 the narrative says “47,217.3 million” where the result is 47,217.3, an orders-of-magnitude error. Q10 calls an average order value “healthy” without a benchmark. Q14 infers “strong retention” from DAU/MAU despite no retention cohort calculation. Narrative factuality needs a separate manual rubric and should not be included in the 20/20 claim.
- A preliminary inspection found the selected chart *types* appropriate for all 18 answerable cases (single-number KPI, categorical bars, or time-series lines, including a two-series DAU/MAU line). This is **18/18 chart-type suitability on this set only**, not a browser-rendering or non-misleading-axis pass. Numeric units, labels, clipping and responsive behavior remain to be checked visually.
- The baseline deliberately lacks schema as requested by the teacher. It is weak by design. A fairer attribution experiment should compare (A) raw no-schema, (B) same LLM with table/column names only, (C) plus relationships/values/metric rules, (D) plus execution repair, using the same unseen questions and dataset. Only then can each enhancement's benefit be estimated. No Vanna benefit has been measured.
- The demo `customers`, `products`, `orders` and `order_items` tables are deterministic derivatives of one sales CSV. The demo `events` rows are *simulated from orders*, not measured browsing events; its DAU/MAU illustrate SQL and charting, not real platform engagement. Multi-table JOINs are tested, but independent enterprise databases, unseen CSV schemas and API failures remain out of sample.

## Professional evaluation plan for the remaining functions

Use separate denominators; do not average unrelated functions into one vague “accuracy” number. Keep every test case ID, dataset version, model ID, prompt version, SQL, output, expected result, latency, tokens, cost and failure category.

| Function | Test design | Report |
|---|---|---|
| Import / API pagination | Small fixture CSV/JSON feeds: duplicate headers, Unicode, empty data, page/offset/next pagination, malformed page, 20 MB limit. Compare imported row counts and values to source. | Passed fixtures / total; partial-import rate |
| Text-to-SQL | Held-out questions on a **new** dataset; compare query results and business metric semantics to independently reviewed reference SQL. Include paraphrases and Chinese/English terms. | Execution accuracy X/N; semantic accuracy X/N; 95% interval if N is large enough |
| Abstention / safety | Missing fields, impossible causal questions, prompt injection, unsafe SQL. | Unsupported refusal X/N; false refusal on answerable X/N; unsafe execution count |
| Cross-table joins | Dedicated cases requiring 2–4 tables; verify keys, grain and no double counting. | Join-result accuracy X/N |
| Chart selection and rendering | Label each answer with acceptable chart types, axis/series mapping and misleading-scale rules; screenshot-check desktop and narrow viewport. | Suitable chart X/N; rendering defects X/N |
| Insight grounding | Two independent reviewers, blind to model variant, check every numerical claim, units, comparison, causality and whether it is supported by returned rows. Adjudicate disagreements. | Fully grounded narratives X/N; unsupported-claim rate; inter-rater agreement |
| Product reliability | Repeat under empty workspace, disconnected API, OpenRouter timeout/rate limit, 500-row result, mixed locale. | Completed task X/N; median/p95 latency; cost/query |

Before the final hand-in, reserve a genuinely **new** 20-question holdout set and at least one unfamiliar CSV schema. Freeze prompts and scoring before running it. Report both development and holdout results, include failed examples, and avoid saying that 20/20 is a general accuracy estimate.

## Assignment changes still needed

1. Correct the original problem statement: replace the Vanna/RAG and rented vector-store claim with the actual architecture above. State that Vanna is a *possible future ablation*, not implemented evidence.
2. Include this benchmark, exact denominators, failure analysis and cost arithmetic in the final submission. The teacher's class-5 gap is addressed by the measured inference cost, but the full class rubric was not present in this workspace, so other criteria cannot be certified from the available files.
3. Add a small manual chart and narrative review, especially Q04 and Q14, plus a fresh holdout dataset. Otherwise label these capabilities as demonstrated but not accuracy-validated.
4. Describe dataset provenance/licence, simulated-event limitation, key handling and lack of enterprise database/OAuth integration. Provide a reproducible demo: `.env` locally, `python server.py`, load demo data, ask a JOIN question, inspect SQL/chart, then show an unanswerable question.

# InsightSQL Product Brief

## Product overview

InsightSQL helps e-commerce teams answer everyday business questions without writing SQL. A user asks a question in English or Chinese. The app reads the data available in the workspace, generates a read-only SQLite query, and presents the result as a table, a chart when useful, and a short written summary. The generated SQL remains visible so users can see how the answer was produced.

## Persona

The primary user is an e-commerce owner or operations manager in a small team. They track sales, profit, products, customers, and activity, but do not have an analyst available for every new question. A dashboard covers routine reporting; questions such as “How much profit did Japanese customers generate in 2024?” call for a more flexible way to explore the data. InsightSQL gives this user a direct route from a question to a result they can inspect.

A second user prepares the workspace. They import CSV files or data from an HTTP API, review the available tables, and make sure the right data is present before analysis begins.

## Input

The main input is a natural-language question in English or Chinese. The app also needs data in its local SQLite workspace. Users can upload CSV files, import CSV or JSON records from an HTTP endpoint, or load the bundled e-commerce dataset. An OpenRouter API key connects the app to its hosted language model. Users do not need to provide table names or write SQL.

## Output

For an answerable question, the app returns the SQL it executed, the result rows, a suitable chart, and a few observations drawn from those rows. If the available data cannot support the question, it returns a reason instead of a made-up answer. The UI keeps the query and the underlying values alongside the visual summary.

## High-level product architecture

```text
Natural-language question ────────────────────────────────────────┐
CSV or API data → SQLite workspace → schema and join discovery ──┤
Metric definitions → metric_knowledge.py → relevant rules ───────┤
                                                                  ▼
                                                      server.py query planning
                                                                  │
                                                   OpenRouter language model
                                                                  │
                                              SQLGlot checks → SQLite execution
                                                                  │
                                        SQL + rows + chart + written observations
                                                                  │
                                                       static/index.html UI
```

`static/index.html` handles the browser experience. `server.py` imports data, inspects the current schema, plans queries, checks SQL, and runs it. `metric_knowledge.py` selects business definitions from `knowledge/metrics.json` and passes them into query planning. OpenRouter supplies the language model, SQLGlot parses and checks the generated query, and SQLite executes it against local data.

## Metrics targeted

The primary product goal was to improve query-to-insight accuracy over a raw language model that receives no database schema. The planned comparison used 20 predefined natural-language questions and expected results derived from ground-truth SQL. The product also aimed to return an appropriate chart with each result and to make the cost of hosted model calls measurable.

## Metrics reached

On the 20-question evaluation, InsightSQL returned the correct outcome for 18 questions. The raw model baseline returned the correct outcome for 2. InsightSQL answered 16 of the 18 answerable questions correctly and declined both questions that the database could not answer. Results were scored against executed outputs rather than SQL text, so equivalent queries received the same score.

The InsightSQL run made 78 model calls across 20 questions. OpenRouter reported a total model cost of $0.0104643, or about $0.000523 per question. At the same average rate, 1,000 questions would cost about $0.52 in model calls. Average end-to-end response time was 6.58 seconds. The product displays charts for suitable query results; chart quality was not scored as a separate metric in this evaluation.

The two missed questions had different outcomes. One quarterly report returned an incorrect result after the model used a SQLite date format that does not support quarters. In the other case, the data could answer the question, but the system declined it. These cases are included in the 18/20 result.

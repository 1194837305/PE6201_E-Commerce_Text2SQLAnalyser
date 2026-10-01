# Frozen Text-to-SQL evaluation

This directory contains the reproducible PE6201 evaluation suite. Its primary metric is execution-result accuracy, reported as a count such as `17/20`, rather than SQL-string similarity.

## Evaluation contract

- 20 frozen questions: 18 answerable and 2 that require a correct refusal.
- The 18 answerable cases have manually reviewable SQL under `gold_sql/`.
- `expected_results.json` contains the results produced by executing those SQL files on the frozen dataset.
- `dataset_manifest.json` records the source CSV hash and deterministic event-generation seed.
- SQL aliases may differ, but the returned values, row count, column count, and required ordering must match.
- Numeric comparison uses the per-case absolute tolerance in `cases.jsonl`.
- A failed query is not a correct refusal. A refusal is correct only for E19 and E20.

The questions do not copy the examples in the application README. The two refusal cases also avoid the absent-field examples already named in the production prompt, reducing evaluation leakage.

## Systems compared

`baseline` uses the same configured model, but receives only the natural-language question and a generic instruction to return SQLite. It receives no schema, values, relationships, validator, execution repair, chart logic, or project-specific examples.

`insightsql` follows the production pipeline: relationship discovery, SQL planning, SQLGlot validation, SQLite execution and the existing one-repair path, followed by chart and insight generation. Including the downstream calls makes its cost measurement represent one complete user query.

## Offline validation

From the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python server.py --check
.venv/bin/python evals/prepare_ground_truth.py
```

`prepare_ground_truth.py` makes no model calls. It validates all 18 gold SQL files, recreates the expected results, and updates the dataset manifest. Do not regenerate these files after seeing model results unless the dataset or an objectively incorrect gold query has changed; document any such correction.

## Paid formal run

The runner refuses to make API calls unless `--yes` is present:

```bash
.venv/bin/python evals/run_eval.py --system all --yes
```

Useful debugging commands, which are not headline evaluations:

```bash
.venv/bin/python evals/run_eval.py --system baseline --case E01 --yes
.venv/bin/python evals/run_eval.py --system insightsql --case E01 --yes
```

The full run writes auditable JSONL records, system summaries, and `results/summary.md`. Each record includes generated SQL or refusal, result rows, failure type, model-call count, tokens, latency, and provider-reported cost when OpenRouter supplies it.

## Cost interpretation

The code prefers `usage.cost` returned by OpenRouter because hosted-model pricing can change. When the provider does not return cost, the report says `unavailable`; it does not invent a price. The summary also projects cost for 100 and 1,000 queries from the observed average.

The first InsightSQL case includes relationship-discovery cost. Later cases reuse the application cache, matching a normal session rather than charging schema discovery to every question.

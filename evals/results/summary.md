# InsightSQL frozen evaluation

- Run time (UTC): 2026-10-01T11:30:54.827321+00:00
- Model: `openai/gpt-4o-mini`
- Dataset: `global_ecommerce_sales.csv` plus deterministic normalized/event tables
- Test set: 20 cases (18 answerable, 2 unanswerable)

## Headline results

| System | Correct | Answerable | Correct abstentions | Cost/query (USD) | Calls |
|---|---:|---:|---:|---:|---:|
| baseline | 2/20 | 2/18 | 0/2 | 0.00003922 | 20 |
| insightsql | 18/20 | 16/18 | 2/2 | 0.00052322 | 78 |

## Case-level audit

| Case | System | Correct | Status | Failure | Calls | Cost USD |
|---|---|---:|---|---|---:|---:|
| E01 | baseline | no | error | invalid_sql | 1 | 0.00002790 |
| E02 | baseline | no | refused | false_refusal | 1 | 0.00003030 |
| E03 | baseline | yes | success |  | 1 | 0.00003960 |
| E04 | baseline | no | error | invalid_sql | 1 | 0.00002625 |
| E05 | baseline | no | error | invalid_sql | 1 | 0.00003720 |
| E06 | baseline | no | error | invalid_sql | 1 | 0.00003675 |
| E07 | baseline | no | error | invalid_sql | 1 | 0.00003660 |
| E08 | baseline | no | error | invalid_sql | 1 | 0.00004635 |
| E09 | baseline | no | error | invalid_sql | 1 | 0.00005235 |
| E10 | baseline | no | error | invalid_sql | 1 | 0.00003855 |
| E11 | baseline | no | error | invalid_sql | 1 | 0.00005130 |
| E12 | baseline | no | error | invalid_sql | 1 | 0.00003840 |
| E13 | baseline | no | refused | false_refusal | 1 | 0.00003270 |
| E14 | baseline | no | error | invalid_sql | 1 | 0.00005250 |
| E15 | baseline | yes | success |  | 1 | 0.00003615 |
| E16 | baseline | no | error | invalid_sql | 1 | 0.00003450 |
| E17 | baseline | no | refused | false_refusal | 1 | 0.00003075 |
| E18 | baseline | no | error | invalid_sql | 1 | 0.00004665 |
| E19 | baseline | no | error | invalid_sql | 1 | 0.00004605 |
| E20 | baseline | no | error | invalid_sql | 1 | 0.00004350 |
| E01 | insightsql | yes | success |  | 4 | 0.00105330 |
| E02 | insightsql | yes | success |  | 3 | 0.00048030 |
| E03 | insightsql | yes | success |  | 4 | 0.00044325 |
| E04 | insightsql | yes | success |  | 3 | 0.00037260 |
| E05 | insightsql | yes | success |  | 4 | 0.00046710 |
| E06 | insightsql | yes | success |  | 4 | 0.00044685 |
| E07 | insightsql | yes | success |  | 4 | 0.00044355 |
| E08 | insightsql | yes | success |  | 4 | 0.00047385 |
| E09 | insightsql | no | success | row_count_mismatch | 4 | 0.00049635 |
| E10 | insightsql | yes | success |  | 4 | 0.00046185 |
| E11 | insightsql | yes | success |  | 5 | 0.00058200 |
| E12 | insightsql | no | refused | false_refusal | 3 | 0.00034635 |
| E13 | insightsql | yes | success |  | 3 | 0.00042045 |
| E14 | insightsql | yes | success |  | 4 | 0.00048000 |
| E15 | insightsql | yes | success |  | 4 | 0.00041475 |
| E16 | insightsql | yes | success |  | 4 | 0.00044250 |
| E17 | insightsql | yes | success |  | 7 | 0.00106770 |
| E18 | insightsql | yes | success |  | 4 | 0.00045510 |
| E19 | insightsql | yes | refused |  | 3 | 0.00065760 |
| E20 | insightsql | yes | refused |  | 3 | 0.00045885 |

## Interpretation rules

The headline metric is execution-result accuracy, not SQL string equality. A refusal is correct only for the two frozen unanswerable cases. Provider-reported API cost is used when available; missing cost is reported as unavailable rather than estimated from an unverified price.

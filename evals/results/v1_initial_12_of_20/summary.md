# InsightSQL frozen evaluation

- Run time (UTC): 2026-09-30T11:26:58.055463+00:00
- Model: `openai/gpt-4o-mini`
- Dataset: `global_ecommerce_sales.csv` plus deterministic normalized/event tables
- Test set: 20 cases (18 answerable, 2 unanswerable)

## Headline results

| System | Correct | Answerable | Correct abstentions | Cost/query (USD) | Calls |
|---|---:|---:|---:|---:|---:|
| baseline | 2/20 | 2/18 | 0/2 | 0.00003877 | 20 |
| insightsql | 12/20 | 10/18 | 2/2 | 0.00039212 | 40 |

## Case-level audit

| Case | System | Correct | Status | Failure | Calls | Cost USD |
|---|---|---:|---|---|---:|---:|
| E01 | baseline | no | error | invalid_sql | 1 | 0.00002730 |
| E02 | baseline | no | refused | false_refusal | 1 | 0.00002910 |
| E03 | baseline | yes | success |  | 1 | 0.00003960 |
| E04 | baseline | no | error | invalid_sql | 1 | 0.00002625 |
| E05 | baseline | no | error | invalid_sql | 1 | 0.00003720 |
| E06 | baseline | no | error | invalid_sql | 1 | 0.00003435 |
| E07 | baseline | no | error | invalid_sql | 1 | 0.00003660 |
| E08 | baseline | no | error | invalid_sql | 1 | 0.00004635 |
| E09 | baseline | no | error | invalid_sql | 1 | 0.00005235 |
| E10 | baseline | no | error | invalid_sql | 1 | 0.00003855 |
| E11 | baseline | no | error | invalid_sql | 1 | 0.00005130 |
| E12 | baseline | no | error | invalid_sql | 1 | 0.00003840 |
| E13 | baseline | no | refused | false_refusal | 1 | 0.00002910 |
| E14 | baseline | no | error | invalid_sql | 1 | 0.00005250 |
| E15 | baseline | yes | success |  | 1 | 0.00003555 |
| E16 | baseline | no | error | invalid_sql | 1 | 0.00003450 |
| E17 | baseline | no | refused | false_refusal | 1 | 0.00003075 |
| E18 | baseline | no | error | invalid_sql | 1 | 0.00004665 |
| E19 | baseline | no | error | invalid_sql | 1 | 0.00004605 |
| E20 | baseline | no | error | invalid_sql | 1 | 0.00004290 |
| E01 | insightsql | no | success | value_mismatch_row_1_column_1 | 2 | 0.00106245 |
| E02 | insightsql | yes | success |  | 1 | 0.00026115 |
| E03 | insightsql | yes | success |  | 2 | 0.00028860 |
| E04 | insightsql | yes | success |  | 1 | 0.00024390 |
| E05 | insightsql | no | success | value_mismatch_row_2_column_2 | 3 | 0.00058245 |
| E06 | insightsql | no | success | value_mismatch_row_1_column_1 | 2 | 0.00029085 |
| E07 | insightsql | no | success | value_mismatch_row_1_column_2 | 2 | 0.00030045 |
| E08 | insightsql | yes | success |  | 2 | 0.00030675 |
| E09 | insightsql | no | success | row_count_mismatch | 2 | 0.00030735 |
| E10 | insightsql | yes | success |  | 2 | 0.00027585 |
| E11 | insightsql | yes | success |  | 3 | 0.00038745 |
| E12 | insightsql | no | success | row_count_mismatch | 2 | 0.00032595 |
| E13 | insightsql | no | error | pipeline_error | 2 | 0.00052440 |
| E14 | insightsql | yes | success |  | 2 | 0.00031680 |
| E15 | insightsql | yes | success |  | 2 | 0.00025980 |
| E16 | insightsql | yes | success |  | 2 | 0.00029325 |
| E17 | insightsql | no | refused | false_refusal | 3 | 0.00088530 |
| E18 | insightsql | yes | success |  | 3 | 0.00051570 |
| E19 | insightsql | yes | refused |  | 1 | 0.00020790 |
| E20 | insightsql | yes | refused |  | 1 | 0.00020595 |

## Interpretation rules

The headline metric is execution-result accuracy, not SQL string equality. A refusal is correct only for the two frozen unanswerable cases. Provider-reported API cost is used when available; missing cost is reported as unavailable rather than estimated from an unverified price.

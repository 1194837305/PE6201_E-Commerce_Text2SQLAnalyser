# Metric knowledge

The JSON cards are versioned project contracts. External links provide background;
project-specific calendar, event and averaging choices are explicitly our choices,
not universal definitions from those sources.

The multilingual model selects allowed IDs from the small catalog; only selected
cards enter SQL planning and review. This is semantic document selection, not
embedding/vector search. It costs one additional model call per planning attempt,
captured by the existing usage collector. Retrieval does not prove schema
compatibility or SQL correctness. Unknown IDs are discarded.

No evaluation questions, expected rows, or gold SQL are loaded by this module.
Complex multi-metric SQL can be decomposed into independent queries with common
dimension aliases. SQLite checks each query before their results are combined.
This is a bounded additional model call, not a guarantee of semantic correctness.
Execution repairs now receive the exact failed SQL and schema directly.
Reviewer output is compiled before it can replace the original candidate.
Average DAU includes zero-activity calendar days. Historical gold SQL averages
observed days only; verify equivalence for the frozen dataset and treat datasets
with missing days as separate regression cases.

Run the separate multilingual diagnostic:

```sh
.venv/bin/python evals/check_metric_retrieval.py --yes
```

It reports inclusion of the expected metric, not top-1 accuracy or end-to-end
accuracy. E13/E17 and the original suite have already informed development and
are now regression cases; new generalization claims require unseen questions.

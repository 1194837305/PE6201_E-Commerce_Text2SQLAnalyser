from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server

from common import EVAL_ROOT, EXPECTED_PATH, fresh_demo_database, load_cases, verify_dataset, write_json
from comparator import score_case
from metrics import summarize


def save_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def markdown_summary(model: str, summaries: dict[str, dict], all_results: dict[str, list[dict]]) -> str:
    lines = [
        "# InsightSQL frozen evaluation",
        "",
        f"- Run time (UTC): {datetime.now(timezone.utc).isoformat()}",
        f"- Model: `{model}`",
        "- Dataset: `global_ecommerce_sales.csv` plus deterministic normalized/event tables",
        "- Test set: 20 cases (18 answerable, 2 unanswerable)",
        "",
        "## Headline results",
        "",
        "| System | Correct | Answerable | Correct abstentions | Cost/query (USD) | Calls |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for system, summary in summaries.items():
        cost = "unavailable" if summary["average_reported_cost_usd"] is None else f"{summary['average_reported_cost_usd']:.8f}"
        lines.append(
            f"| {system} | {summary['correct']}/{summary['total']} | "
            f"{summary['answerable_correct']}/{summary['answerable_total']} | "
            f"{summary['correct_abstentions']}/{summary['unanswerable_total']} | {cost} | "
            f"{summary['total_model_calls']} |"
        )
    lines.extend(["", "## Case-level audit", "", "| Case | System | Correct | Status | Failure | Calls | Cost USD |", "|---|---|---:|---|---|---:|---:|"])
    for system, results in all_results.items():
        for item in results:
            cost = "" if item.get("reported_cost_usd") is None else f"{item['reported_cost_usd']:.8f}"
            lines.append(
                f"| {item['case_id']} | {system} | {'yes' if item.get('correct') else 'no'} | "
                f"{item.get('execution_status', '')} | {item.get('failure_type') or ''} | "
                f"{item.get('model_calls', 0)} | {cost} |"
            )
    lines.extend([
        "",
        "## Interpretation rules",
        "",
        "The headline metric is execution-result accuracy, not SQL string equality. A refusal is correct only for the two frozen unanswerable cases. Provider-reported API cost is used when available; missing cost is reported as unavailable rather than estimated from an unverified price.",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the frozen InsightSQL evaluation suite")
    parser.add_argument("--system", choices=["baseline", "insightsql", "all"], default="all")
    parser.add_argument("--case", help="Run one case id, for debugging only; not a headline score")
    parser.add_argument("--output-dir", type=Path, help="Separate directory for this revision's audit results")
    parser.add_argument("--yes", action="store_true", help="Confirm that paid OpenRouter calls may be made")
    args = parser.parse_args()
    if not args.yes:
        parser.error("This command makes paid OpenRouter calls. Re-run with --yes after confirming the model and key.")

    verify_dataset()
    cases = load_cases()
    if args.case:
        cases = [case for case in cases if case["id"] == args.case]
        if not cases:
            parser.error(f"Unknown case id: {args.case}")
    expected = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))
    server.env()
    if not os.getenv("OPENROUTER_API_KEY"):
        parser.error("OPENROUTER_API_KEY is missing from .env")
    model = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
    systems = ["baseline", "insightsql"] if args.system == "all" else [args.system]
    results_dir = args.output_dir or EVAL_ROOT / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    all_results: dict[str, list[dict]] = {}
    summaries: dict[str, dict] = {}

    with fresh_demo_database():
        for system in systems:
            if system == "baseline":
                import baseline as adapter
            else:
                import insightsql_adapter as adapter
                server.REL_CACHE.clear()
            scored: list[dict] = []
            for index, case in enumerate(cases, 1):
                print(f"[{system} {index}/{len(cases)}] {case['id']}", flush=True)
                run = adapter.run_case(case)
                scored.append(score_case(case, run, expected.get(case["id"])))
            all_results[system] = scored
            summaries[system] = summarize(cases, scored)
            save_jsonl(results_dir / f"{system}_results.jsonl", scored)
            write_json(results_dir / f"{system}_summary.json", summaries[system])

    (results_dir / "summary.md").write_text(markdown_summary(model, summaries, all_results), encoding="utf-8")
    print("\nHeadline results")
    for system, summary in summaries.items():
        print(f"{system}: {summary['correct']}/{summary['total']}")
    print(f"Detailed results: {results_dir}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("Evaluation interrupted; partial in-memory results were not reported as final.")

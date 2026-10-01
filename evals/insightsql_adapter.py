from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server

from metrics import aggregate_usage


def run_case(case: dict) -> dict:
    usage_records: list[dict] = []
    usage_token = server.USAGE_SINK.set(usage_records)
    started = time.perf_counter()
    repaired = False
    result = {
        "case_id": case["id"],
        "system": "insightsql",
        "question": case["question"],
        "execution_status": "not_run",
    }
    try:
        plan = server.plan(case["question"])
        result["plan"] = plan
        if plan.get("cannot_answer"):
            result.update(
                cannot_answer=True,
                reason=plan.get("reason", ""),
                execution_status="refused",
            )
        else:
            for attempt in range(3):
                try:
                    columns, rows = server.run(plan["sql"])
                    break
                except server.AIError as error:
                    if attempt == 2:
                        raise
                    repaired = True
                    plan = server.plan(case["question"], server.execution_repair(plan.get("sql", ""), error))
                    result["plan"] = plan
                    if plan.get("cannot_answer"):
                        result.update(
                            cannot_answer=True,
                            reason=plan.get("reason", ""),
                            execution_status="refused",
                        )
                        break
            if not result.get("cannot_answer"):
                chart = server.choose_chart(case["question"], columns, rows, plan["sql"], plan["title"])
                insights = ["Metric definition: " + item for item in plan.get("assumptions", [])]
                insights.extend(server.explain(case["question"], rows))
                result.update(
                    cannot_answer=False,
                    generated_sql=plan["sql"],
                    execution_status="success",
                    columns=columns,
                    rows=rows,
                    chart_spec=chart,
                    insights=insights,
                )
    except Exception as error:
        result.update(execution_status="error", failure_type="pipeline_error", error=str(error)[:500])
    finally:
        server.USAGE_SINK.reset(usage_token)
        result.update(aggregate_usage(usage_records))
        result["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        result["repair_used"] = repaired
    return result

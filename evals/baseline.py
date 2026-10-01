from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server
from sqlglot import exp, parse

from metrics import aggregate_usage


BASELINE_PROMPT = """You are a raw language model baseline for text-to-SQL.
Convert the user's e-commerce analytics question into one SQLite read-only query.
You receive no database schema, examples, field values, or join information.
Do not ask a follow-up question. Return strict JSON only:
{\"sql\":\"SELECT ...\"}
If you believe the data required by the question cannot exist in the available database, return:
{\"cannot_answer\":true,\"reason\":\"brief reason\"}

QUESTION: {question}"""


def _parse_response(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("baseline_model_did_not_return_json")
    value = json.loads(match.group())
    if value.get("cannot_answer"):
        return {"cannot_answer": True, "reason": str(value.get("reason", ""))[:300]}
    sql = str(value.get("sql", "")).strip().strip("`").rstrip(";")
    statements = parse(sql, read="sqlite")
    if len(statements) != 1 or not isinstance(statements[0], exp.Query):
        raise ValueError("baseline_output_is_not_one_read_only_query")
    if any(isinstance(node, (exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop, exp.Command)) for node in statements[0].walk()):
        raise ValueError("baseline_output_is_not_read_only")
    return {"cannot_answer": False, "sql": sql}


def run_case(case: dict) -> dict:
    usage_records: list[dict] = []
    usage_token = server.USAGE_SINK.set(usage_records)
    started = time.perf_counter()
    result = {
        "case_id": case["id"],
        "system": "baseline",
        "question": case["question"],
        "execution_status": "not_run",
    }
    try:
        parsed = _parse_response(server.call(BASELINE_PROMPT.replace("{question}", case["question"]), 900))
        result.update(parsed)
        if parsed.get("cannot_answer"):
            result["execution_status"] = "refused"
        else:
            columns, rows = server.run(parsed["sql"])
            result.update(execution_status="success", columns=columns, rows=rows)
    except Exception as error:
        result.update(execution_status="error", failure_type="invalid_sql", error=str(error)[:500])
    finally:
        server.USAGE_SINK.reset(usage_token)
        result.update(aggregate_usage(usage_records))
        result["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return result

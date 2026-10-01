from __future__ import annotations

from collections import Counter


def aggregate_usage(records: list[dict]) -> dict:
    prompt_tokens = completion_tokens = total_tokens = 0
    costs: list[float] = []
    for usage in records:
        if not isinstance(usage, dict):
            continue
        prompt_tokens += int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        completion_tokens += int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        total_tokens += int(usage.get("total_tokens") or 0)
        raw_cost = usage.get("cost")
        if raw_cost is None and isinstance(usage.get("cost_details"), dict):
            raw_cost = usage["cost_details"].get("upstream_inference_cost")
        try:
            if raw_cost is not None:
                costs.append(float(raw_cost))
        except (TypeError, ValueError):
            pass
    if not total_tokens:
        total_tokens = prompt_tokens + completion_tokens
    return {
        "model_calls": len(records),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "reported_cost_usd": round(sum(costs), 8) if costs else None,
        "usage_records": records,
    }


def summarize(cases: list[dict], results: list[dict]) -> dict:
    by_id = {case["id"]: case for case in cases}
    total = len(results)
    correct = sum(bool(item.get("correct")) for item in results)
    answerable = [item for item in results if by_id[item["case_id"]]["answerable"]]
    unanswerable = [item for item in results if not by_id[item["case_id"]]["answerable"]]
    successful_sql = [item for item in answerable if item.get("execution_status") == "success"]
    costs = [item["reported_cost_usd"] for item in results if item.get("reported_cost_usd") is not None]
    categories: dict[str, dict] = {}
    for category in sorted({by_id[item["case_id"]]["category"] for item in results}):
        subset = [item for item in results if by_id[item["case_id"]]["category"] == category]
        categories[category] = {"correct": sum(bool(x.get("correct")) for x in subset), "total": len(subset)}
    languages: dict[str, dict] = {}
    for language in sorted({by_id[item["case_id"]]["language"] for item in results}):
        subset = [item for item in results if by_id[item["case_id"]]["language"] == language]
        languages[language] = {"correct": sum(bool(x.get("correct")) for x in subset), "total": len(subset)}
    return {
        "correct": correct,
        "total": total,
        "answerable_correct": sum(bool(item.get("correct")) for item in answerable),
        "answerable_total": len(answerable),
        "correct_abstentions": sum(bool(item.get("correct")) for item in unanswerable),
        "unanswerable_total": len(unanswerable),
        "false_refusals": sum(item.get("failure_type") == "false_refusal" for item in results),
        "unsafe_answers": sum(item.get("failure_type") == "unsafe_answer" for item in results),
        "sql_execution_successes": len(successful_sql),
        "sql_execution_attempts": len(answerable),
        "failure_types": dict(Counter(item.get("failure_type") for item in results if item.get("failure_type"))),
        "categories": categories,
        "languages": languages,
        "total_model_calls": sum(int(item.get("model_calls") or 0) for item in results),
        "total_prompt_tokens": sum(int(item.get("prompt_tokens") or 0) for item in results),
        "total_completion_tokens": sum(int(item.get("completion_tokens") or 0) for item in results),
        "total_tokens": sum(int(item.get("total_tokens") or 0) for item in results),
        "total_reported_cost_usd": round(sum(costs), 8) if costs else None,
        "average_reported_cost_usd": round(sum(costs) / len(costs), 8) if costs else None,
        "projected_cost_100_queries_usd": round(sum(costs) / len(costs) * 100, 6) if costs else None,
        "projected_cost_1000_queries_usd": round(sum(costs) / len(costs) * 1000, 6) if costs else None,
        "average_latency_ms": round(sum(float(item.get("latency_ms") or 0) for item in results) / total, 1) if total else 0,
    }

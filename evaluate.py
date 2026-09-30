"""Frozen 20-question benchmark. Run: python evaluate.py --mode both --output eval_results.json"""
import argparse
import datetime as dt
import json
import math
import os
import sqlite3
import tempfile
import time
from pathlib import Path

import server

ROOT = Path(__file__).parent


def same_result(expected, actual):
    """Compare values, not SQL spelling or column aliases; row order is irrelevant."""
    if len(expected) != len(actual):
        return False
    def normalized(rows):
        return sorted([list(row.values()) for row in rows], key=lambda row: json.dumps(row, ensure_ascii=False, default=str))
    for left, right in zip(normalized(expected), normalized(actual)):
        if len(left) != len(right):
            return False
        for a, b in zip(left, right):
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                if not math.isclose(a, b, rel_tol=1e-6, abs_tol=0.02):
                    return False
            elif str(a) != str(b):
                return False
    return True


def totals(usages):
    return {
        'prompt_tokens': sum(int(x.get('prompt_tokens') or 0) for x in usages),
        'completion_tokens': sum(int(x.get('completion_tokens') or 0) for x in usages),
        'cost_usd': round(sum(float(x.get('cost') or 0) for x in usages), 8) if usages and all(x.get('cost') is not None for x in usages) else None,
        'model_calls': len(usages),
    }


def attempt(case, mode):
    usage = []
    token = server.USAGE_SINK.set(usage)
    started = time.monotonic()
    result = {'id': case['id'], 'mode': mode, 'question': case['question']}
    try:
        if mode == 'baseline':
            prompt = ('Convert this business question into one SQLite read-only SELECT. '
                      'No database schema or examples are available. Do not ask follow-up questions. '
                      'If it cannot be answered, return {"cannot_answer":true,"reason":"..."}. '
                      'Otherwise return strict JSON {"sql":"..."}. Question: ' + case['question'])
            plan = server.obj(server.call(prompt))
        else:
            plan = server.plan(case['question'])
        result['refused'] = bool(plan.get('cannot_answer'))
        result['reason'] = plan.get('reason')
        result['sql'] = plan.get('sql')
        if not result['refused']:
            sql = server.validate(plan.get('sql', ''), set(server.context()[0]))
            result['sql'] = sql
            try:
                columns, rows = server.run(sql)
            except server.AIError as exc:
                if mode != 'system':
                    raise
                plan = server.plan(case['question'], f'Previous SQL failed: {exc}. Correct it.')
                if plan.get('cannot_answer'):
                    result['refused'] = True
                    result['reason'] = plan.get('reason')
                else:
                    sql = plan['sql']
                    columns, rows = server.run(sql)
                    result['sql'] = sql
            if not result['refused']:
                result['executed'] = True
                result['row_count'] = len(rows)
                if mode == 'system':
                    result['chart_type'] = server.chart(columns, rows, plan.get('chart', 'auto'), plan.get('title', ''))['type']
                    try:
                        result['insights'] = server.explain(case['question'], rows)
                    except server.AIError as exc:
                        result['insight_error'] = str(exc)
    except (server.AIError, sqlite3.Error, ValueError) as exc:
        result['error'] = str(exc)
    result['correct'] = result['refused'] if case.get('cannot_answer') else False
    if not case.get('cannot_answer') and result.get('executed'):
        try:
            _, expected = server.run(case['sql'])
            _, actual = server.run(server.validate(result['sql'], set(server.context()[0])))
            result['correct'] = same_result(expected, actual)
        except (server.AIError, sqlite3.Error):
            pass
    result['latency_s'] = round(time.monotonic() - started, 2)
    result['usage'] = totals(usage)
    server.USAGE_SINK.reset(token)
    return result


def summarize(results, mode):
    subset = [x for x in results if x['mode'] == mode]
    answerable = subset[:18]
    unsupported = subset[18:]
    return {
        'answerable_correct': f"{sum(x['correct'] for x in answerable)}/{len(answerable)}",
        'unsupported_refused': f"{sum(x['correct'] for x in unsupported)}/{len(unsupported)}",
        'total_correct': f"{sum(x['correct'] for x in subset)}/{len(subset)}",
        'executed': f"{sum(x.get('executed', False) for x in answerable)}/{len(answerable)}",
        'avg_latency_s': round(sum(x['latency_s'] for x in subset) / len(subset), 2) if subset else None,
        'avg_cost_usd': round(sum(x['usage']['cost_usd'] for x in subset) / len(subset), 8) if subset and all(x['usage']['cost_usd'] is not None for x in subset) else None,
        'total_prompt_tokens': sum(x['usage']['prompt_tokens'] for x in subset),
        'total_completion_tokens': sum(x['usage']['completion_tokens'] for x in subset),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['baseline', 'system', 'both'], default='both')
    parser.add_argument('--limit', type=int, default=20, help='Smoke-test first N cases; full benchmark uses 20')
    parser.add_argument('--output', default='eval_results.json')
    args = parser.parse_args()
    cases = json.loads((ROOT / 'eval_cases.json').read_text(encoding='utf-8'))
    assert len(cases) == 20 and sum(bool(x.get('cannot_answer')) for x in cases) == 2
    server.env()
    if not os.getenv('OPENROUTER_API_KEY'):
        parser.error('Set OPENROUTER_API_KEY in .env before running live evaluation')
    original_db = server.DB
    with tempfile.TemporaryDirectory(prefix='pe6201_eval_') as temp:
        server.DB = Path(temp) / 'eval.sqlite3'
        try:
            server.load_demo()
            for case in cases:
                if 'sql' in case:
                    server.run(server.validate(case['sql'], set(server.context()[0])))
            results = []
            for case in cases[:max(1, min(args.limit, 20))]:
                for mode in (['baseline', 'system'] if args.mode == 'both' else [args.mode]):
                    item = attempt(case, mode)
                    results.append(item)
                    print(f"{case['id']} {mode}: {'PASS' if item['correct'] else 'FAIL'} ({item['latency_s']}s)", flush=True)
            summary = {mode: summarize(results, mode) for mode in (['baseline', 'system'] if args.mode == 'both' else [args.mode])}
            report = {'run_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'model': os.getenv('OPENROUTER_MODEL', 'openai/gpt-4o-mini'), 'dataset': server.SOURCE.name, 'case_count': len(cases[:args.limit]), 'summary': summary, 'results': results}
            (ROOT / args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        finally:
            server.DB = original_db


if __name__ == '__main__':
    main()

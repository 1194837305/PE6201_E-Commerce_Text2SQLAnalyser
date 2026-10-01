from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _cell_equal(actual, expected, tolerance: float) -> bool:
    if actual is None or expected is None:
        return actual is expected
    left, right = _number(actual), _number(expected)
    if left is not None and right is not None:
        return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=tolerance)
    return str(actual).strip() == str(expected).strip()


def _matrix(columns: list[str], rows: list[dict]) -> list[list]:
    return [[row.get(column) for column in columns] for row in rows]


def compare_results(
    actual_columns: list[str],
    actual_rows: list[dict],
    expected_columns: list[str],
    expected_rows: list[dict],
    rules: dict,
) -> tuple[bool, str | None]:
    if len(actual_columns) != len(expected_columns):
        return False, "column_count_mismatch"
    if len(actual_rows) != len(expected_rows):
        return False, "row_count_mismatch"

    actual = _matrix(actual_columns, actual_rows)
    expected = _matrix(expected_columns, expected_rows)
    if not rules.get("row_order_matters", False):
        key = lambda row: tuple("<NULL>" if value is None else str(value) for value in row)
        actual, expected = sorted(actual, key=key), sorted(expected, key=key)

    tolerance = float(rules.get("numeric_tolerance", 0))
    for row_index, (left, right) in enumerate(zip(actual, expected)):
        for column_index, (actual_value, expected_value) in enumerate(zip(left, right)):
            if not _cell_equal(actual_value, expected_value, tolerance):
                return False, f"value_mismatch_row_{row_index + 1}_column_{column_index + 1}"
    return True, None


def score_case(case: dict, run: dict, expected: dict | None) -> dict:
    if run.get("execution_status") == "error":
        correct = False
        failure = run.get("failure_type") or "pipeline_error"
    elif not case["answerable"]:
        correct = bool(run.get("cannot_answer"))
        failure = None if correct else "unsafe_answer"
    elif run.get("cannot_answer"):
        correct, failure = False, "false_refusal"
    elif run.get("execution_status") != "success":
        correct = False
        failure = run.get("failure_type") or "execution_error"
    else:
        correct, failure = compare_results(
            run.get("columns", []),
            run.get("rows", []),
            expected["columns"],
            expected["rows"],
            case.get("comparison", {}),
        )
        if not correct and not failure:
            failure = "incorrect_result"
    return {**run, "correct": correct, "failure_type": failure}

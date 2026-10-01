from __future__ import annotations

import csv
import json
from datetime import datetime, timezone

from common import (
    EVAL_ROOT,
    EXPECTED_PATH,
    MANIFEST_PATH,
    SOURCE_PATH,
    execute_sql,
    fresh_demo_database,
    load_cases,
    read_gold_sql,
    sha256,
    write_json,
)


def main() -> None:
    cases = load_cases()
    if len(cases) != 20 or sum(bool(case["answerable"]) for case in cases) != 18:
        raise RuntimeError("The frozen suite must contain exactly 18 answerable and 2 unanswerable cases")
    with SOURCE_PATH.open(encoding="utf-8-sig", newline="") as stream:
        source_rows = sum(1 for _ in csv.DictReader(stream))

    expected: dict[str, dict] = {}
    with fresh_demo_database() as db_path:
        for case in cases:
            if not case["answerable"]:
                continue
            sql = read_gold_sql(case)
            columns, rows = execute_sql(db_path, sql)
            expected[case["id"]] = {"columns": columns, "rows": rows}
            print(f"validated {case['id']}: {len(rows)} row(s)")

    manifest = {
        "dataset": SOURCE_PATH.name,
        "sha256": sha256(SOURCE_PATH),
        "source_rows": source_rows,
        "generated_tables": ["sales", "customers", "products", "orders", "order_items", "user_events"],
        "event_generator_seed": 6201,
        "answerable_cases": 18,
        "unanswerable_cases": 2,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "note": "Regenerate only after manually reviewing every case and gold SQL file.",
    }
    write_json(EXPECTED_PATH, expected)
    write_json(MANIFEST_PATH, manifest)
    print(f"wrote {EXPECTED_PATH.relative_to(EVAL_ROOT.parent)}")
    print(f"wrote {MANIFEST_PATH.relative_to(EVAL_ROOT.parent)}")


if __name__ == "__main__":
    main()

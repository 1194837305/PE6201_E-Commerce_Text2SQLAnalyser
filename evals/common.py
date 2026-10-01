from __future__ import annotations

import contextlib
import hashlib
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
EVAL_ROOT = Path(__file__).resolve().parent
CASES_PATH = EVAL_ROOT / "cases.jsonl"
EXPECTED_PATH = EVAL_ROOT / "expected_results.json"
MANIFEST_PATH = EVAL_ROOT / "dataset_manifest.json"
SOURCE_PATH = ROOT / "global_ecommerce_sales.csv"


def load_cases() -> list[dict]:
    return [json.loads(line) for line in CASES_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_gold_sql(case: dict) -> str:
    relative = case.get("gold_sql_file")
    if not relative:
        raise ValueError(f"{case['id']} has no gold SQL")
    return (EVAL_ROOT / relative).read_text(encoding="utf-8").strip()


def execute_sql(db_path: Path, sql: str) -> tuple[list[str], list[dict]]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        cursor = connection.execute(sql)
        columns = [item[0] for item in cursor.description or []]
        return columns, [dict(row) for row in cursor.fetchall()]
    finally:
        connection.close()


@contextlib.contextmanager
def fresh_demo_database():
    import server

    original_db = server.DB
    with tempfile.TemporaryDirectory(prefix="insightsql_eval_") as directory:
        db_path = Path(directory) / "evaluation.sqlite3"
        server.DB = db_path
        server.REL_CACHE.clear()
        try:
            server.load_demo()
            yield db_path
        finally:
            server.REL_CACHE.clear()
            server.DB = original_db


def verify_dataset() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    actual = sha256(SOURCE_PATH)
    if actual != manifest["sha256"]:
        raise RuntimeError(
            "Dataset hash differs from the frozen evaluation manifest. "
            "Regenerate and manually review the ground truth before evaluating."
        )


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

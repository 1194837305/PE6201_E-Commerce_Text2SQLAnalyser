"""Paid, separate retrieval diagnostic; never overwrites SQL evaluation results."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
from metric_knowledge import retrieve

CASES = [
    ("每个月有多少不同的人使用了平台？", "mau"),
    ("How many unique people interacted with the product in each calendar month?", "mau"),
    ("¿Cuántos usuarios únicos estuvieron activos cada mes?", "mau"),
    ("月ごとのアクティブユーザー数を知りたい", "mau"),
    ("每个月平均每天有多少独立活跃用户？", "average_dau"),
    ("What is the mean number of daily unique visitors within each month?", "average_dau"),
]
if __name__ == "__main__":
    if "--yes" not in sys.argv:
        raise SystemExit("Paid diagnostic: add --yes to authorize six model calls.")
    passed = 0
    for question, expected in CASES:
        ids = [c["id"] for c in retrieve(question, server.call, server.obj)]
        ok = expected in ids
        passed += ok
        print(json.dumps({"question": question, "expected": expected, "retrieved": ids, "pass": ok}, ensure_ascii=False))
    print(f"Retrieval inclusion: {passed}/{len(CASES)} (not SQL accuracy)")

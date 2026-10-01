"""Offline checks for arithmetic and repair diagnostics; no API calls."""
import sqlite3
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class AcceptanceRegressionTests(unittest.TestCase):
    def test_ratios_preserve_fractional_results(self):
        c = sqlite3.connect(":memory:")
        c.execute("CREATE TABLE observations(n INTEGER)")
        c.executemany("INSERT INTO observations VALUES (?)", [(10,), (11,), (19,)])
        sql = server.validate("SELECT SUM(n)/COUNT(*) AS mean FROM observations", {"observations"})
        self.assertAlmostEqual(c.execute(sql).fetchone()[0], 40 / 3)
        c.close()

    def test_explicit_integer_cast_preserved(self):
        c = sqlite3.connect(":memory:")
        c.execute("CREATE TABLE observations(n INTEGER)")
        c.execute("INSERT INTO observations VALUES (5)")
        sql = server.validate("SELECT CAST(n/2 AS INTEGER) FROM observations", {"observations"})
        self.assertEqual(c.execute(sql).fetchone()[0], 2)
        c.close()

    def test_repair_contains_failed_query(self):
        sql = "SELECT missing FROM (SELECT present FROM samples)"
        message = server.execution_repair(sql, "no such column: missing")
        self.assertIn(sql, message)
        self.assertIn("projected", message)

    def test_date_interval_is_not_silently_changed(self):
        sql = server.validate("SELECT * FROM samples WHERE order_date BETWEEN '2024-01-01' AND '2024-02-01'", {"samples"})
        self.assertIn("BETWEEN", sql)


if __name__ == "__main__":
    unittest.main()

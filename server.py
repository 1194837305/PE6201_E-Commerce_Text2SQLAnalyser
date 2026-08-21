from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CSV_PATH = ROOT / "global_ecommerce_sales.csv"
DB_PATH = ROOT / "analytics.sqlite3"
STATIC = ROOT / "static"
TABLE = "sales"
FIELDS = {
    "Order_ID": "TEXT", "Order_Date": "TEXT", "Customer_Name": "TEXT",
    "Customer_Segment": "TEXT", "Country": "TEXT", "Region": "TEXT",
    "Product_Category": "TEXT", "Product_Name": "TEXT", "Quantity": "REAL",
    "Unit_Price": "REAL", "Discount_Percent": "REAL", "Total_Sales": "REAL",
    "Shipping_Cost": "REAL", "Profit": "REAL", "Payment_Method": "TEXT",
}
SCHEMA = ", ".join(f"{name} {kind}" for name, kind in FIELDS.items())
AI_STATE: dict[str, str] = {"state": "not-tested", "message": "AI 尚未测试"}


class AIError(RuntimeError):
    pass


def load_env() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if raw and not raw.startswith("#") and "=" in raw:
            name, value = raw.split("=", 1)
            os.environ[name.strip()] = value.strip().strip('"\'')


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(f"CREATE TABLE IF NOT EXISTS {TABLE} ({', '.join(f'{n} {t}' for n, t in FIELDS.items())})")
    con.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    if con.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0] == 0:
        import_csv(con, CSV_PATH.read_text(encoding="utf-8-sig"), CSV_PATH.name)
    return con


def import_csv(con: sqlite3.Connection, text: str, filename: str) -> int:
    rows = list(csv.DictReader(text.splitlines()))
    needed = {"Order_Date", "Total_Sales", "Profit"}
    if not rows:
        raise ValueError("CSV 没有数据行")
    if missing := sorted(needed - set(rows[0])):
        raise ValueError("CSV 缺少必需字段：" + ", ".join(missing))
    con.execute(f"DELETE FROM {TABLE}")
    names = list(FIELDS)
    values = []
    for row in rows:
        values.append([float(row[name]) if FIELDS[name] == "REAL" and row.get(name) else row.get(name, "") for name in names])
    con.executemany(f"INSERT INTO {TABLE} ({','.join(names)}) VALUES ({','.join('?' for _ in names)})", values)
    con.execute("INSERT OR REPLACE INTO meta VALUES ('dataset', ?)", (filename,))
    con.commit()
    return len(values)


def model_request(messages: list[dict[str, str]], max_tokens: int = 700) -> str:
    load_env()
    key = os.getenv("OPENROUTER_API_KEY", "")
    if not key:
        raise AIError("未检测到 OPENROUTER_API_KEY：请在 .env 中配置后重启服务")
    body = json.dumps({
        "model": os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
        "messages": messages,
        "temperature": 0,
        "max_tokens": max_tokens,
    }).encode()
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions", data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "X-Title": "InsightSQL BI"},
    )
    try:
        with urllib.request.urlopen(request, timeout=35) as response:
            data = json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        raise AIError(f"OpenRouter 返回 HTTP {error.code}") from error
    except urllib.error.URLError as error:
        raise AIError(f"无法连接 OpenRouter：{type(error.reason).__name__}") from error
    except OSError as error:
        raise AIError(f"无法连接 OpenRouter：{type(error).__name__}") from error
    try:
        return str(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as error:
        raise AIError("OpenRouter 返回格式异常") from error


def json_from_model(content: str) -> dict[str, Any]:
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.I)
    match = re.search(r"\{.*\}", content, re.S)
    if not match:
        raise AIError("模型没有返回要求的 JSON 结构")
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as error:
        raise AIError("模型返回的 JSON 无法解析") from error


def validate_sql(sql: str) -> str:
    sql = sql.strip().strip("`").rstrip(";").strip()
    if not re.match(r"^(SELECT|WITH)\b", sql, re.I):
        raise AIError("AI 返回的不是只读查询")
    if ";" in sql or not re.search(r"\b(?:FROM|JOIN)\s+sales\b", sql, re.I):
        raise AIError("AI 查询未限定在 sales 数据表")
    if re.search(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|ATTACH|DETACH|PRAGMA|VACUUM)\b", sql, re.I):
        raise AIError("AI 查询包含不允许的数据库操作")
    if re.search(r"\bsqlite_master\b", sql, re.I):
        raise AIError("AI 查询访问了不允许的系统表")
    return sql


def build_plan(question: str) -> dict[str, Any]:
    prompt = f"""你是资深电商 BI 分析师和 SQLite 专家。只分析 sales 表。
表结构：sales({SCHEMA})。
业务含义：Total_Sales 是订单销售额，Profit 是订单利润，Quantity 是购买数量，Order_Date 格式 YYYY-MM-DD。
返回严格 JSON，不要 Markdown：{{"sql":"单条 SQLite SELECT 或 WITH 查询","chart":"bar|line|table","title":"不超过16字、与用户问题同语言的标题","assumptions":["最多2条"]}}。
规则：只用 sales 和上述字段；不可写入数据；分组分析必须包含清晰维度和聚合值；时间趋势用 strftime；最多返回 30 个类别。
示例问题：2023年各地区销售额 -> SELECT Region AS dimension, ROUND(SUM(Total_Sales),2) AS value FROM sales WHERE strftime('%Y',Order_Date)='2023' GROUP BY Region ORDER BY value DESC
用户问题：{question}"""
    plan = json_from_model(model_request([{"role": "user", "content": prompt}]))
    if not isinstance(plan.get("sql"), str):
        raise AIError("AI 计划缺少 SQL")
    plan["sql"] = validate_sql(plan["sql"])
    plan["chart"] = plan.get("chart") if plan.get("chart") in {"bar", "line", "table"} else "table"
    plan["title"] = str(plan.get("title") or "AI 分析结果")[:40]
    plan["assumptions"] = [str(x) for x in plan.get("assumptions", [])][:2]
    return plan


def run_sql(sql: str) -> tuple[list[str], list[dict[str, Any]]]:
    con = connect()
    try:
        con.execute("EXPLAIN QUERY PLAN " + sql).fetchall()
        rows = con.execute(f"SELECT * FROM ({sql}) LIMIT 500").fetchall()
        return list(rows[0].keys()) if rows else [], [dict(row) for row in rows]
    except sqlite3.Error as error:
        raise AIError(f"SQL 执行失败：{error}") from error
    finally:
        con.close()


def explain(question: str, rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["该查询没有返回数据。", "建议放宽时间或筛选条件后重试。"]
    prompt = f"""你是电商业务分析师。基于以下真实查询结果，回答问题“{question}”。
结果：{json.dumps(rows[:30], ensure_ascii=False)}
只返回严格 JSON：{{"insights":["2到3条简短、带具体数字、与用户问题同语言的洞察"],"next_question":"一个值得继续追问且与用户问题同语言的问题"}}。不要编造结果中没有的因果关系。"""
    result = json_from_model(model_request([{"role": "user", "content": prompt}], 400))
    insights = [str(x) for x in result.get("insights", []) if str(x).strip()][:3]
    if not insights:
        insights = ["已完成真实数据查询，请查看结果表格。"]
    return insights + (["下一步：" + str(result["next_question"])] if result.get("next_question") else [])


def dashboard() -> dict[str, Any]:
    con = connect()
    try:
        one = lambda sql: con.execute(sql).fetchone()[0]
        query = lambda sql: [dict(row) for row in con.execute(sql).fetchall()]
        dataset = con.execute("SELECT value FROM meta WHERE key='dataset'").fetchone()
        return {
            "dataset": dataset[0] if dataset else CSV_PATH.name,
            "rows": one("SELECT COUNT(*) FROM sales"),
            "sales": round(one("SELECT SUM(Total_Sales) FROM sales"), 2),
            "profit": round(one("SELECT SUM(Profit) FROM sales"), 2),
            "orders": one("SELECT COUNT(DISTINCT Order_ID) FROM sales"),
            "customers": one("SELECT COUNT(DISTINCT Customer_Name) FROM sales"),
            "month": query("SELECT substr(Order_Date,1,7) AS label, ROUND(SUM(Total_Sales),2) AS value FROM sales GROUP BY 1 ORDER BY 1"),
            "category": query("SELECT Product_Category AS label, ROUND(SUM(Total_Sales),2) AS value FROM sales GROUP BY 1 ORDER BY 2 DESC"),
            "region": query("SELECT Region AS label, ROUND(SUM(Profit),2) AS value FROM sales GROUP BY 1 ORDER BY 2 DESC"),
            "ai": {"configured": bool(os.getenv("OPENROUTER_API_KEY")), **AI_STATE},
        }
    finally:
        con.close()


def ai_health() -> dict[str, str]:
    try:
        reply = model_request([{"role": "user", "content": "Reply exactly: OK"}], 5).strip()
        AI_STATE.update(state="ready", message="OpenRouter 已连接" if reply else "OpenRouter 返回为空")
    except AIError as error:
        AI_STATE.update(state="error", message=str(error))
    return AI_STATE


class Handler(BaseHTTPRequestHandler):
    def json(self, payload: Any, status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or "{}")

    def do_GET(self) -> None:
        if self.path == "/api/dashboard":
            self.json(dashboard()); return
        if self.path == "/api/ai/health":
            self.json(ai_health()); return
        path = STATIC / ("index.html" if self.path in {"/", "/index.html"} else self.path.lstrip("/"))
        if not path.is_file() or STATIC not in path.resolve().parents and path.resolve() != STATIC:
            self.send_error(404); return
        raw = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8" if path.suffix == ".html" else "application/octet-stream")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers(); self.wfile.write(raw)

    def do_POST(self) -> None:
        try:
            data = self.body()
            if self.path == "/api/ask":
                question = str(data.get("question", "")).strip()
                if not question:
                    raise AIError("请输入分析问题")
                plan = build_plan(question)
                columns, rows = run_sql(plan["sql"])
                self.json({"question": question, "plan": plan, "columns": columns, "rows": rows, "insights": explain(question, rows), "ai": AI_STATE}); return
            if self.path == "/api/upload":
                filename = str(data.get("filename", "uploaded.csv"))
                csv_text = str(data.get("csv", ""))
                con = connect()
                try:
                    count = import_csv(con, csv_text, filename)
                finally:
                    con.close()
                self.json({"ok": True, "rows": count, "filename": filename}); return
            self.json({"error": "Not found"}, 404)
        except (AIError, ValueError, json.JSONDecodeError) as error:
            self.json({"error": str(error)}, 400)

    def log_message(self, *_: Any) -> None:
        pass


def check() -> None:
    con = connect()
    assert con.execute("SELECT COUNT(*) FROM sales").fetchone()[0] > 0
    con.close()
    sql = validate_sql("SELECT Region AS dimension, SUM(Total_Sales) AS value FROM sales GROUP BY Region")
    cols, rows = run_sql(sql)
    assert cols == ["dimension", "value"] and len(rows) == 5
    print("self-check passed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.check:
        check(); return
    connect().close()
    print(f"InsightSQL BI running on http://localhost:{args.port}")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()

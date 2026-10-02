# InsightSQL

InsightSQL is a local e-commerce analytics app that turns English or Chinese questions into read-only SQLite queries. It shows the generated SQL, the returned rows, a chart when the result supports one, and short observations grounded in those rows. If the loaded data cannot answer a question, the app can explain what is missing.

The app uses an OpenRouter-hosted language model for language understanding and SQL planning. SQLite stores and queries the data, while SQLGlot checks generated SQL before execution. No model training, fine-tuning, vector database, or Vanna service is required.

## What the app does

- Starts with an empty workspace. Import one or more CSV files, import CSV or JSON data from an HTTP(S) API, or load the bundled demo dataset.
- Reads the current schema, observed values, declared foreign keys, and evidence for possible joins instead of relying on a fixed set of demo tables.
- Selects relevant metric definitions from `knowledge/metrics.json` for terms such as sales, orders, MAU, and average DAU.
- Generates read-only SQLite SQL, checks supported joins, executes the query, and makes a limited repair attempt if execution fails.
- Returns a data table and a constrained chart type: bar, grouped bar, line, KPI, or table. Numerical observations are calculated from returned rows.

The demo workspace contains the source `sales` table, four normalized commerce tables, and a **simulated** `user_events` table. Activity metrics computed from those events are demonstrations, not measurements of real user activity. The dashboard's preset sales KPIs require the demo-style `sales` columns; natural-language querying can also use other imported tables.

## Project structure

```text
InsightSQL/
├── server.py                    Local HTTP server, imports, schema analysis, SQL pipeline
├── app.py                       Alternative entry point for the same server
├── static/index.html            Browser UI, result tables, and canvas charts
├── metric_knowledge.py          Selects relevant metric definitions
├── knowledge/metrics.json       Metric definitions, aliases, and calculation rules
├── global_ecommerce_sales.csv   Bundled source data for the demo workspace
├── seed_multitable.py           Optional export of generated demo tables
├── evals/                       Separate reproducible evaluation tools and records
├── requirements.txt             Python dependencies
└── .env.example                 Local API configuration template
```

A question follows this path:

```text
Browser question
  → POST /api/ask in server.py
  → inspect SQLite schema and supported relationships
  → select metric definitions in metric_knowledge.py
  → ask the hosted model to plan SQL
  → validate with SQLGlot and execute in SQLite
  → return SQL, rows, chart specification, and observations
  → render the response in static/index.html
```

## Run locally

You need Python 3.10 or newer, a browser, network access to OpenRouter, and an OpenRouter API key for AI questions. SQLite is included with Python. Install dependencies from `requirements.txt`; no separate database server is needed.

Clone the repository and enter its directory:

```bash
git clone https://github.com/1194837305/PE6201_E-Commerce_Text2SQLAnalyser.git
cd PE6201_E-Commerce_Text2SQLAnalyser
```

### macOS or Linux

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

On macOS, run `open -e .env` to edit the file in TextEdit. On Linux, open `.env` in your preferred text editor. Replace the example key with your own key and keep the model setting, or choose another OpenRouter model you can access:

```text
OPENROUTER_API_KEY=your-real-key
OPENROUTER_MODEL=openai/gpt-4o-mini
```

Save the file, then start the server:

```bash
.venv/bin/python server.py --check
.venv/bin/python server.py --port 8000
```

Leave that terminal running and open <http://127.0.0.1:8000> in your browser. To stop the server, press `Ctrl+C`. If port 8000 is already occupied, use another port, such as `--port 8080`, and open the matching URL.

### Windows PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

Replace the example key in `.env`, save the file, and run:

```powershell
.\.venv\Scripts\python.exe server.py --check
.\.venv\Scripts\python.exe server.py --port 8000
```

Open <http://127.0.0.1:8000>. `start.ps1` is also available on Windows; the commands above show each setup step explicitly.

The server binds to `127.0.0.1`, so it is intended for use on the same computer. This repository does not include a public hosting configuration. Do not commit `.env` or share your API key; `.env` is excluded by `.gitignore`.

## First use

1. Click **Load demo dataset** to create six tables, or import your own CSV or API data. The workspace is empty until you do this.
2. Click **Test AI connection** to confirm that the key and model work.
3. Ask a question, for example, `What were the sales and profit generated by Japanese customers in 2024?`
4. Inspect the generated SQL, result rows, chart, and observations. If a question requires data that is not present, the app may return a reason instead of SQL.

The **Clear Workspace** action removes the business tables in the local SQLite workspace. Loading the demo again requires an empty workspace. Imported data is stored in `analytics.sqlite3` beside `server.py`; that local database file is ignored by Git.

## Notes on data and model behavior

Metric definitions guide the model; they do not guarantee that every generated query is correct. Review SQL and results before using them in decisions. Queries are limited to read-only SQL, and the server caps returned rows. External API imports require an HTTP(S) endpoint and support optional bearer authentication and pagination. Credentials entered for an import are not saved in the app's database.

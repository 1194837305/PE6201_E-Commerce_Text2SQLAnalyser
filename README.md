# InsightSQL · 电商 BI 与 AI 数据分析

## 启动

```powershell
python server.py --check
./start.ps1
```

访问 http://localhost:8000 。

## 配置 AI

复制 `.env.example` 为 `.env`，并设置：

```text
OPENROUTER_API_KEY=你的Key
OPENROUTER_MODEL=openai/gpt-4o-mini
```

页面左侧点击“测试 AI 连接”。显示“OpenRouter 已连接”后，AI 提问会依次生成安全 SQL、执行 SQLite 查询、基于真实结果生成业务洞察。

## 功能

- 导入兼容的电商 CSV，自动刷新数据看板。
- 经营 KPI、月度销售趋势、品类销售贡献。
- 自然语言到 SQLite SQL；仅允许查询 `sales` 表的只读 SQL。
- 查询结果表格、SQL 复核和基于结果的 AI 洞察。

首个数据集要求至少有 `Order_Date`、`Total_Sales`、`Profit` 字段；随项目提供的 CSV 可直接使用。

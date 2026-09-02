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

- 导入任意 CSV；每个文件成为一张独立可查询表，不会覆盖已有数据。
- 经营 KPI、月度销售趋势、品类销售贡献。
- 自然语言到安全 SQLite SQL，支持跨表 JOIN 与 CTE。
- AI 每次动态读取当前表结构、关联关系和低基数字段的真实值，进行多语言与模糊语义匹配（例如“日本”匹配数据库中的 `Japan`），无需手工维护映射表。
- 查询结果自动选择 KPI、柱状图、分组柱状图、折线图或表格，并保留 SQL 与原始结果供复核。

## 内置多表模型

首次启动会从原始 `sales` 宽表确定性生成 `customers`、`products`、`orders`、`order_items` 与 `events`，并建立客户—订单—明细—产品以及客户—行为事件的分析关系。运行 `python seed_multitable.py` 可将五张测试表导出到 `data/simulated/`。

可直接测试：

- `日本客户在 2024 年的销售额和利润是多少？`
- `Which customer segments bought the most Technology products?`
- `Compare monthly DAU and MAU in 2024.`

首个数据集要求至少有 `Order_Date`、`Total_Sales`、`Profit` 字段；随项目提供的 CSV 可直接使用。

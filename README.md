# InsightSQL · 电商 BI 与 AI 数据分析

## 启动

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe server.py --check
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

- 工作区默认从 0 张表开始；两个 CSV 入口均可一次选择多张文件，每个文件成为一张独立可查询表。同名表自动追加 `_2`、`_3`，不覆盖已有数据。
- 可通过 HTTP(S) API 导入 CSV 或 JSON 数组；支持可选 Bearer Token、嵌套 JSON 路径、页码/偏移量/下一页链接分页和显式可信内网访问，凭据不会保存。
- “加载演示数据”按需创建 6 张电商测试表（原始销售宽表、4 张拆分表及独立仿真的 `user_events`）；“清空工作区”删除全部数据库业务表并保持空白状态。演示 DAU/MAU 基于明确标记为仿真的行为事件，不代表真实平台活跃。
- 经营 KPI、月度销售趋势、品类销售贡献。
- 自然语言到只读 SQLite SQL：先根据当前表结构、键值重合度与唯一性提出关系候选，模型筛选并描述字段，再规划 SQL；SQLGlot 校验跨表 JOIN 是否使用受证据支持的键。复杂跨表 CTE 暂时拒绝而非冒险执行。
- 动态读取当前表字段和低基数真实值，进行多语言与模糊语义匹配；没有演示表关系、固定 DAU/MAU 公式或特定测试题提示。
- 结果出来后再由模型选择图表类型、横轴和数值序列，服务端校验字段，前端真正渲染柱状、分组柱状或折线；保留 SQL 与原始结果供复核。
- 文字解读中的数值、最高/最低与时间起止由程序从查询结果计算；模型只选择要展示的事实，避免生成未经核验的排名或因果判断。
- 缺少必需数据的提问（如广告花费、退款）明确拒答，不伪造 SQL。
- 月度看板支持最近 6/12/24 个月或全部数据筛选；长时间序列和查询图表支持横向滚动。

## 20 题对照评测

`eval_cases.json` 和 `eval_results.json` 是旧版的**开发集历史记录**，不是新版盲测成绩；其中含已移除的模拟事件题，不能继续报告 20/20。应在独立未见数据上重新设计并运行对照评测。旧数据仅用于解释原版问题，详见 [EVALUATION.md](EVALUATION.md)。

当前没有集成 Vanna、向量库或检索式 RAG。新版使用 OpenRouter 的结构分析、SQL 规划、图表选择节点，外加 SQLGlot 解析校验和执行反馈；是否提高准确率仍待盲测，不应把旧版成绩归因于新版或 Vanna。

实测结果、失败案例、成本计算及作业待补项见 [EVALUATION.md](EVALUATION.md)。

## 内置多表模型

点击“加载演示数据”后，系统从原始 `sales` 宽表确定性生成 `customers`、`products`、`orders`、`order_items`，并独立仿真 `user_events(event_id,user_id,event_time,event_type)`。事件不从订单行为反推；其 `user_id` 与 `customers.customer_id` 使用相同模拟身份，但字段名不同，供关系发现机制测试。这些不是独立采集的数据源；实际查询时关系由当前数据证据和模型分析得到，而非预设给模型。`seed_multitable.py` 可导出五张表。

可直接测试：

- `日本客户在 2024 年的销售额和利润是多少？`
- `Which customer segments bought the most Technology products?`
- `Compare monthly DAU and MAU in 2024.`（演示结果基于仿真事件；真实数据集没有事件表时应拒答）

导入其他 CSV 不要求这些字段；只有演示电商 KPI 看板依赖销售表的特定字段。未知数据仍可用于自然语言查询与结果图表。

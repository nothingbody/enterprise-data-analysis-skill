---
name: data-analysis-agent
description: A general-purpose enterprise data-analysis agent. Point it at local files (CSV/TSV/Parquet/JSON/XLSX) and/or SQL databases (SQLite/PostgreSQL/MySQL); it writes and runs pandas + DuckDB SQL in a tool-use loop to answer business questions, with cross-source joins, and reports conclusion-first Chinese analysis. Use for ad-hoc BI, multi-table/multi-source analysis, and exploratory data work.
---

# Data Analysis Agent

A two-layer system:

- **Skill core** (`data_agent.datasource` + `data_agent.sandbox`) — provider-agnostic and scriptable. `DataRegistry` funnels files and databases into one DuckDB connection so everything is uniformly queryable (cross-source joins included) and introspects the schema. `Sandbox` runs SQL and Python with state that persists across calls.
- **Agent shell** (`data_agent.agent.DataAnalysisAgent`) — drives Claude in a tool-use loop: Claude inspects the schema, writes SQL/Python, runs it, observes results, iterates, then reports.

## Run

Set credentials once: `ANTHROPIC_API_KEY` (or `ANTHROPIC_AUTH_TOKEN`).

Every run writes a standard data-analysis report in **both HTML and Word
(.docx)**, following a big-company structure (结论先行 / 金字塔原理: 执行摘要 →
背景与目标 → 框架与口径 → 整体大盘 → 多维下钻与归因 → 关键洞察 → 结论与行动建议 →
数据质量与局限) plus the evidence tables and charts the agent produced. Default
output dir: `analysis-output/`; override with `--output` (a `.html`/`.docx` file
path uses that stem for both; a directory writes `report-NN.{html,docx}`).

```powershell
# One-shot (writes report.html + report.docx)
python -m data_agent.cli --input .\sample-data\sales.csv `
  --question "按区域分析本季度收入、成本、订单量的趋势和排名" --output .\report.html

# Multi-source (file + database), cross-source join
python -m data_agent.cli --input .\orders.csv --db sqlite:///.\crm.db `
  --question "把订单关联 CRM 客户表，按客户等级看复购率和客单价"

# Interactive multi-turn session (omit --question)
python -m data_agent.cli --input .\sample-data\sales.csv
```

Options: `--input/-i` (repeatable file), `--db` (repeatable database URI), `--question/-q`, `--output/-o` (HTML file or directory; default `analysis-output/`), `--no-report` (skip the HTML), `--model/-m` (default `claude-opus-4-8`; set `claude-fable-5` for the most capable model), `--quiet` (hide the live thinking / tool trace).

Environment overrides: `DATA_AGENT_MODEL`, `DATA_AGENT_EFFORT` (low|medium|high|xhigh|max), `DATA_AGENT_MAX_ITERS`, `DATA_AGENT_PREVIEW_ROWS`.

## Use as a library

```python
from data_agent import DataRegistry, DataAnalysisAgent

reg = DataRegistry()
reg.register_path("sample-data/sales.csv")
reg.attach_database("sqlite:///crm.db")          # optional
agent = DataAnalysisAgent(reg)                    # needs ANTHROPIC_API_KEY
agent.ask("按区域分析本季度收入、成本、订单量的趋势和排名")
agent.ask("刚才收入最高的区域，毛利率怎么样？")     # follow-ups keep context
```

The skill core can also be used on its own, without any LLM:

```python
from data_agent import DataRegistry, Sandbox

reg = DataRegistry(); reg.register_path("sample-data/sales.csv")
print(reg.schema_summary())
print(Sandbox(reg).run_sql("SELECT region, sum(revenue) FROM sales GROUP BY 1")["result"])
```

## Dependencies

`anthropic`, `duckdb`, `pandas`, `openpyxl` (Excel). PostgreSQL/MySQL attachment pulls the matching DuckDB extension at runtime.

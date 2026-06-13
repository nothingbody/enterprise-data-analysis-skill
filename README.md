# Data Analysis Agent

A general-purpose, enterprise-grade data-analysis agent. You point it at data —
local files and/or SQL databases — and it answers business questions by **writing
and running pandas + SQL in a loop**, doing cross-source joins, verifying its own
numbers, and reporting a conclusion-first analysis.

## What it is

Two layers:

| Layer | Module | Role |
|---|---|---|
| **Skill core** | `data_agent/datasource.py`, `data_agent/sandbox.py`, `data_agent/report.py` | Provider-agnostic, scriptable. Registers files + databases into one DuckDB connection (uniformly queryable, cross-source joins), introspects the schema, runs SQL/Python with state that persists across calls, and collects report artifacts. No LLM. |
| **Agent shell** | `data_agent/agent.py` | Drives Claude in a tool-use loop on top of the core: inspect schema → write SQL/Python → run → observe → iterate → report. |

Every run writes a **standard data-analysis report in both HTML and Word (.docx)**
(`analysis-output/` by default). The report follows a big-company structure
(pyramid principle / 结论先行): 执行摘要 → 背景与目标 → 分析框架与口径 → 整体大盘
概览 → 多维下钻与归因 → 关键洞察 → 结论与行动建议 → 数据质量与局限, plus the
evidence tables and charts the agent produced (charts embedded as PNG).

The agent gets two tools — `run_sql` (DuckDB over every source) and `run_python`
(persistent pandas namespace) — and decides for itself how to use them.

## Data sources

- **Files**: CSV, TSV, Parquet, JSON/NDJSON, Excel (XLSX/XLS, every sheet).
- **Databases**: SQLite, PostgreSQL, MySQL (attached via DuckDB; queryable and
  join-able alongside the files).

## Quick start

```powershell
pip install -r requirements.txt
$env:ANTHROPIC_API_KEY = "sk-ant-..."

python -m data_agent.cli --input .\sample-data\sales.csv `
  --question "按区域分析本季度收入、成本、订单量的趋势和排名" `
  --output .\report.html
```

This prints the analysis live and writes `report.html` + `report.docx`. Omit
`--output` to use the default `analysis-output/` directory, or pass `--no-report`
to skip the files. Omit `--question` for an interactive multi-turn session (one
report per question). See [SKILL.md](SKILL.md) for the full option list, library
usage, and multi-source examples.

## Model

Defaults to `claude-opus-4-8`. For Anthropic's most capable model set
`--model claude-fable-5` (or `DATA_AGENT_MODEL=claude-fable-5`). Thinking depth is
controlled by `DATA_AGENT_EFFORT` (low | medium | high | xhigh | max).

## Sample data

[`sample-data/sales.csv`](sample-data/sales.csv) — a small Chinese sales dataset
(date, region, channel, product, customer segment, orders, revenue, cost) for
trying the agent out.

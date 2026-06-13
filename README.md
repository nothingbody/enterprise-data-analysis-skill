# Data Analysis Agent

> A general-purpose, enterprise-grade data-analysis agent — point it at your data, ask in plain language, get a board-ready report.

[![CI](https://github.com/nothingbody/enterprise-data-analysis-skill/actions/workflows/ci.yml/badge.svg)](https://github.com/nothingbody/enterprise-data-analysis-skill/actions/workflows/ci.yml)
![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)
![Built with Claude](https://img.shields.io/badge/built%20with-Claude-d97757.svg)
![Reports](https://img.shields.io/badge/output-HTML%20%2B%20Word-success.svg)

You point it at data — local files and/or SQL databases — and it answers business
questions by **writing and running pandas + DuckDB SQL in a tool-use loop**, doing
cross-source joins, verifying its own numbers, and producing a conclusion-first
analysis report in **both HTML and Word**.

## ✨ Features

- 🔀 **Multi-source, one engine** — CSV / TSV / Parquet / JSON / Excel files and
  SQLite / PostgreSQL / MySQL databases are all registered into a single DuckDB
  connection, so you can **join across sources** in one query.
- 🧠 **LLM writes & runs the code** — the model inspects the schema, writes SQL and
  pandas, runs it, reads the result, and iterates. It is not a fixed set of canned
  charts; it reasons toward the answer.
- 📑 **Standard report in HTML + Word (.docx)** — every run emits a big-company-
  structured report (金字塔 / 结论先行): 执行摘要 → 背景与目标 → 框架与口径 → 整体
  大盘 → 多维下钻与归因 → 关键洞察 → 结论与行动建议 → 数据质量与局限, with the real
  evidence tables and charts the agent produced.
- ✅ **Built-in self-audit pass** — after the first draft, a second verification
  round re-checks every claim against the tool results, forces quantified
  attribution (量×价×结构), gates small-sample conclusions, and tests the most
  likely alternative explanation before concluding.
- 🔌 **Provider-flexible** — defaults to Claude; runs against any
  Anthropic-Messages-compatible endpoint via `ANTHROPIC_BASE_URL` (verified on
  **DeepSeek**).
- 🧩 **Two clean layers** — a scriptable, LLM-free **Skill core** plus an **Agent
  shell** (see below).

## Architecture

| Layer | Module | Role |
|---|---|---|
| **Skill core** | `data_agent/datasource.py`, `sandbox.py`, `report.py`, `docx_writer.py` | Provider-agnostic, scriptable, no LLM. Registers files + databases into one DuckDB connection, introspects the schema, runs SQL/Python with state that persists across calls, and renders the HTML/Word report. |
| **Agent shell** | `data_agent/agent.py`, `prompts.py`, `tools.py`, `cli.py` | Drives Claude in a tool-use loop on top of the core: inspect schema → write SQL/Python → run → observe → iterate → audit → report. |

The agent gets two tools — `run_sql` (DuckDB over every source) and `run_python`
(a persistent pandas namespace) — and decides for itself how to use them.

## Quick start

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY="sk-ant-..."          # PowerShell: $env:ANTHROPIC_API_KEY="sk-ant-..."

python -m data_agent.cli --input sample-data/sales.csv \
  --question "按区域分析本季度收入、成本、订单量的趋势和排名" \
  --output report.html
```

This prints the analysis live and writes `report.html` + `report.docx`. Omit
`--output` to use the default `analysis-output/` directory, or pass `--no-report`
to skip the files. Omit `--question` for an interactive multi-turn session (one
report per question). See [SKILL.md](SKILL.md) for the full option list, library
usage, and multi-source examples.

### Run against DeepSeek (or any Anthropic-compatible endpoint)

```bash
export ANTHROPIC_API_KEY="<deepseek-key>"
export ANTHROPIC_BASE_URL="https://api.deepseek.com/anthropic"
python -m data_agent.cli --input sample-data/sales.csv --model deepseek-chat \
  --question "..." --output report.html
```

## Data sources

- **Files**: CSV, TSV, Parquet, JSON / NDJSON, Excel (XLSX / XLS, every sheet).
- **Databases**: SQLite, PostgreSQL, MySQL (attached via DuckDB; queryable and
  join-able alongside the files).

## Model

Defaults to `claude-opus-4-8`. For Anthropic's most capable model use
`--model claude-fable-5` (or `DATA_AGENT_MODEL=claude-fable-5`). Thinking depth is
controlled by `DATA_AGENT_EFFORT` (low | medium | high | xhigh | max). The
self-audit pass is on by default; disable it with `--no-audit`.

## Sample data

[`sample-data/sales.csv`](sample-data/sales.csv) — a small Chinese sales dataset
(date, region, channel, product, customer segment, orders, revenue, cost) to try
the agent on.

## License

[MIT](LICENSE)

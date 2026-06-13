"""Command-line entrypoint: one-shot analysis or an interactive chat session.

Examples
--------
One-shot:
    python -m data_agent.cli --input sample-data/sales.csv \
        --question "按区域分析本季度收入、成本、订单量的趋势和排名"

Multi-source with a database and cross-source joins:
    python -m data_agent.cli --input orders.csv --db sqlite:///crm.db \
        --question "把订单和 CRM 客户表关联，按客户等级看复购率"

Interactive (omit --question):
    python -m data_agent.cli --input sample-data/sales.csv
"""

from __future__ import annotations

import argparse
import os
import sys

from .agent import DataAnalysisAgent
from .config import DEFAULT_MODEL
from .datasource import DataRegistry


def _build_registry(inputs: list[str], dbs: list[str]) -> DataRegistry:
    registry = DataRegistry()
    for path in inputs:
        created = registry.register_path(path)
        print(f"  registered file {path} -> {', '.join(created)}", file=sys.stderr)
    for uri in dbs:
        alias = registry.attach_database(uri)
        print(f"  attached database {uri} -> {alias}", file=sys.stderr)
    return registry


def _interactive(agent: DataAnalysisAgent) -> None:
    print(
        "进入交互模式。输入业务问题开始分析，输入 exit / quit 退出。\n",
        file=sys.stderr,
    )
    while True:
        try:
            question = input("\n\033[1m问题>\033[0m ").strip()
        except (EOFError, KeyboardInterrupt):
            print(file=sys.stderr)
            break
        if not question:
            continue
        if question.lower() in {"exit", "quit", ":q"}:
            break
        agent.ask(question)


def _force_utf8() -> None:
    # Windows consoles default to a legacy code page (cp936/GBK); reconfigure so
    # streaming Chinese output neither mojibakes nor raises UnicodeEncodeError.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    parser = argparse.ArgumentParser(
        prog="data-agent",
        description="A data-analysis agent: Claude writes and runs pandas/SQL "
        "against your files and databases to answer business questions.",
    )
    parser.add_argument(
        "--input", "-i", action="append", default=[], metavar="PATH",
        help="Data file to load (CSV/TSV/Parquet/JSON/XLSX). Repeatable.",
    )
    parser.add_argument(
        "--db", action="append", default=[], metavar="URI",
        help="Database to attach (sqlite:///x.db, postgres://..., mysql://...). "
        "Repeatable.",
    )
    parser.add_argument(
        "--question", "-q", default=None,
        help="One-shot question. If omitted, starts an interactive session.",
    )
    parser.add_argument(
        "--model", "-m", default=DEFAULT_MODEL,
        help=f"Claude model id (default: {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--output", "-o", default="analysis-output", metavar="PATH",
        help="Where to write the report: a base path/file or a directory "
        "(default: analysis-output/). Both .html and .docx are written. "
        "Use --no-report to disable.",
    )
    parser.add_argument(
        "--no-report", action="store_true",
        help="Do not write report files (print the analysis only).",
    )
    parser.add_argument(
        "--no-audit", action="store_true",
        help="Skip the self-audit / verification pass (faster, but less rigorous).",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress the live thinking / tool-call trace on stderr.",
    )
    args = parser.parse_args(argv)

    if not args.input and not args.db:
        parser.error("provide at least one --input file or --db database")

    if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get(
        "ANTHROPIC_AUTH_TOKEN"
    ):
        print(
            "error: set ANTHROPIC_API_KEY (or ANTHROPIC_AUTH_TOKEN) first.",
            file=sys.stderr,
        )
        return 2

    print("Loading data sources...", file=sys.stderr)
    try:
        registry = _build_registry(args.input, args.db)
    except Exception as exc:  # noqa: BLE001 - surface a clean message to the CLI user
        print(f"error: {exc}", file=sys.stderr)
        return 1

    agent = DataAnalysisAgent(
        registry,
        model=args.model,
        output=None if args.no_report else args.output,
        self_audit=not args.no_audit,
        show_thinking=not args.quiet,
    )

    try:
        if args.question:
            agent.ask(args.question)
        else:
            _interactive(agent)
    finally:
        registry.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

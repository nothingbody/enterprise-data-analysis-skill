"""Skill core: a persistent SQL + Python execution sandbox.

State persists across calls within a session: a variable defined in one
run_python call is available in the next, and both tools share the same DuckDB
connection. Results are formatted compactly (shape + dtypes + a head preview)
and length-capped so large outputs don't flood the model's context.
"""

from __future__ import annotations

import ast
import contextlib
import io
import traceback
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from .config import MAX_RESULT_CHARS, PREVIEW_ROWS
from .datasource import DataRegistry
from .report import Report, plt


def _truncate(text: str, limit: int = MAX_RESULT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... (output truncated at {limit} chars)"


class Sandbox:
    def __init__(self, registry: DataRegistry, preview_rows: int = PREVIEW_ROWS) -> None:
        self.con = registry.con
        self.preview_rows = preview_rows
        # Collects report artifacts the agent pins during analysis.
        self.report = Report(self)
        # Namespace shared across every run_python call.
        self.ns: dict[str, Any] = {
            "pd": pd,
            "np": np,
            "duckdb": duckdb,
            "con": self.con,
            "sql": lambda q: self.con.execute(q).df(),
            "report": self.report,
        }
        if plt is not None:
            self.ns["plt"] = plt

    # -- tools -----------------------------------------------------------

    def run_sql(self, query: str) -> dict[str, Any]:
        try:
            df = self.con.execute(query).df()
        except Exception:
            return {"ok": False, "error": _truncate(traceback.format_exc(limit=2))}
        return {"ok": True, "result": self._format_df(df)}

    def run_python(self, code: str) -> dict[str, Any]:
        try:
            tree = ast.parse(code, mode="exec")
        except SyntaxError as exc:
            return {"ok": False, "error": f"SyntaxError: {exc}"}

        last_expr = None
        if tree.body and isinstance(tree.body[-1], ast.Expr):
            last_expr = ast.Expression(tree.body.pop().value)

        stdout = io.StringIO()
        value = None
        try:
            with contextlib.redirect_stdout(stdout):
                if tree.body:
                    exec(compile(tree, "<agent>", "exec"), self.ns)
                if last_expr is not None:
                    value = eval(compile(last_expr, "<agent>", "eval"), self.ns)
        except Exception:
            return {
                "ok": False,
                "error": _truncate(traceback.format_exc(limit=3)),
                "stdout": stdout.getvalue(),
            }
        return {
            "ok": True,
            "stdout": stdout.getvalue(),
            "result": self._format_value(value),
        }

    # -- formatting ------------------------------------------------------

    def _format_df(self, df: pd.DataFrame) -> str:
        dtypes = ", ".join(
            f"{c}:{t}" for c, t in zip(df.columns, df.dtypes.astype(str))
        )
        head = df.head(self.preview_rows)
        body = head.to_string(index=False, max_colwidth=40)
        note = ""
        if len(df) > self.preview_rows:
            note = f"\n... ({len(df)} rows total; showing first {self.preview_rows})"
        return _truncate(
            f"shape: {df.shape[0]} rows x {df.shape[1]} cols\n"
            f"columns: {dtypes}\n{body}{note}"
        )

    def _format_value(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, pd.DataFrame):
            return self._format_df(value)
        if isinstance(value, pd.Series):
            return self._format_df(value.to_frame())
        return _truncate(repr(value))

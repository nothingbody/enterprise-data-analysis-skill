"""Tool schemas exposed to Claude, and dispatch into the sandbox."""

from __future__ import annotations

from typing import Any

from .sandbox import Sandbox

TOOLS = [
    {
        "name": "run_sql",
        "description": (
            "Run a DuckDB SQL query against all registered data sources. Local "
            "files and attached databases are all queryable by their table name; "
            "cross-source joins in a single query are allowed. Returns a preview "
            "of the result (row x col shape, column types, and the first rows). "
            "Prefer SQL for set-based aggregation, filtering, grouping, and joins."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "A single DuckDB SQL statement.",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "run_python",
        "description": (
            "Execute Python in a namespace that PERSISTS across calls. Available: "
            "`pd` (pandas), `np` (numpy), `con` (the DuckDB connection), and "
            "`sql(query)` which runs SQL and returns a DataFrame. Variables you "
            "define persist into later calls. The value of the final expression "
            "(or anything you print) is returned, truncated for large objects. "
            "Use Python for statistics, reshaping, time-series, modeling, and "
            "anything awkward to express in SQL."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python source to execute.",
                }
            },
            "required": ["code"],
        },
    },
]


def dispatch(sandbox: Sandbox, name: str, tool_input: dict[str, Any]) -> str:
    """Run a tool call and return a string suitable for a tool_result block."""
    if name == "run_sql":
        result = sandbox.run_sql(tool_input.get("query", ""))
    elif name == "run_python":
        result = sandbox.run_python(tool_input.get("code", ""))
    else:
        return f"ERROR: unknown tool {name!r}"

    if not result.get("ok"):
        out = "ERROR:\n" + result.get("error", "")
        if result.get("stdout"):
            out += "\n--- stdout before error ---\n" + result["stdout"]
        return out

    parts: list[str] = []
    if result.get("stdout"):
        parts.append("stdout:\n" + result["stdout"].rstrip())
    if result.get("result"):
        parts.append(result["result"])
    return "\n\n".join(parts) if parts else "(no output)"

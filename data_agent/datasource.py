"""Skill core: multi-source data registration and schema introspection.

Everything is funneled into a single in-process DuckDB connection so that local
files (CSV / TSV / Parquet / JSON / Excel) and attached SQL databases (SQLite /
PostgreSQL / MySQL) become uniformly queryable — including cross-source joins in
one SQL statement. No LLM involved; this layer is fully scriptable on its own.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import duckdb
import pandas as pd

_CSV_EXTS = {".csv", ".tsv", ".txt"}
_SYSTEM_CATALOGS = {"system", "temp"}
_SYSTEM_SCHEMAS = {"information_schema", "pg_catalog"}


def _safe_name(raw: str) -> str:
    """Turn an arbitrary file/sheet name into a safe SQL identifier."""
    name = re.sub(r"[^0-9a-zA-Z_]+", "_", raw).strip("_").lower()
    if not name:
        name = "t"
    if name[0].isdigit():
        name = f"t_{name}"
    return name


def _lit(value: str) -> str:
    """A safely single-quoted SQL string literal.

    Parameters can't be prepared inside CREATE VIEW / ATTACH statements, so the
    path is inlined. DuckDB does not process backslash escapes in single-quoted
    strings, so Windows paths are safe once single quotes are doubled.
    """
    return "'" + str(value).replace("'", "''") + "'"


class DataRegistry:
    """Registers data sources into one DuckDB connection and introspects them."""

    def __init__(self) -> None:
        self.con = duckdb.connect()
        self._frames: dict[str, pd.DataFrame] = {}  # keep DataFrames alive
        self.registered: list[dict[str, Any]] = []

    # -- registration ----------------------------------------------------

    def register_path(self, path: str | Path, name: str | None = None) -> list[str]:
        """Register a local data file. Returns the table/view names created."""
        p = Path(path).expanduser()
        if not p.exists():
            raise FileNotFoundError(f"No such file: {p}")
        ext = p.suffix.lower()
        base = _safe_name(name or p.stem)

        loc = _lit(str(p))
        if ext in _CSV_EXTS:
            self.con.execute(
                f'CREATE OR REPLACE VIEW "{base}" AS SELECT * FROM read_csv_auto({loc})'
            )
            created = [base]
        elif ext == ".parquet":
            self.con.execute(
                f'CREATE OR REPLACE VIEW "{base}" AS SELECT * FROM read_parquet({loc})'
            )
            created = [base]
        elif ext in {".json", ".ndjson"}:
            self.con.execute(
                f'CREATE OR REPLACE VIEW "{base}" AS SELECT * FROM read_json_auto({loc})'
            )
            created = [base]
        elif ext in {".xlsx", ".xls"}:
            created = self._register_excel(p, base)
        else:
            raise ValueError(f"Unsupported file type: {ext} ({p.name})")

        for tname in created:
            self.registered.append({"kind": "file", "source": str(p), "table": tname})
        return created

    def _register_excel(self, p: Path, base: str) -> list[str]:
        sheets = pd.read_excel(p, sheet_name=None)  # dict[name -> DataFrame]
        created: list[str] = []
        multi = len(sheets) > 1
        for sheet_name, df in sheets.items():
            tname = f"{base}_{_safe_name(sheet_name)}" if multi else base
            self._frames[tname] = df  # prevent GC; DuckDB scans it by reference
            self.con.register(tname, df)
            created.append(tname)
        return created

    def attach_database(self, uri: str, alias: str | None = None) -> str:
        """Attach a SQL database so its tables become queryable as alias.table.

        Accepts: sqlite:///path.db (or a bare .db/.sqlite path),
        postgres://user:pwd@host/db, mysql://user:pwd@host/db.
        """
        parsed = urlparse(uri)
        scheme = (parsed.scheme or "").lower()

        # Bare path to a sqlite file.
        if not scheme and Path(uri).suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
            scheme = "sqlite"
            parsed = urlparse(f"sqlite:///{uri}")

        if scheme == "sqlite":
            db_path = uri[len("sqlite:///"):] if uri.startswith("sqlite:///") else uri
            alias = _safe_name(alias or Path(db_path).stem)
            self.con.execute("INSTALL sqlite; LOAD sqlite;")
            self.con.execute(f'ATTACH {_lit(db_path)} AS "{alias}" (TYPE sqlite)')
        elif scheme in {"postgres", "postgresql"}:
            alias = _safe_name(alias or (parsed.path.lstrip("/") or "pg"))
            self.con.execute("INSTALL postgres; LOAD postgres;")
            self.con.execute(f'ATTACH {_lit(uri)} AS "{alias}" (TYPE postgres)')
        elif scheme == "mysql":
            alias = _safe_name(alias or (parsed.path.lstrip("/") or "mysql"))
            self.con.execute("INSTALL mysql; LOAD mysql;")
            self.con.execute(f'ATTACH {_lit(uri)} AS "{alias}" (TYPE mysql)')
        else:
            raise ValueError(f"Unsupported database URI: {uri!r}")

        self.registered.append({"kind": "database", "source": uri, "alias": alias})
        return alias

    # -- introspection ---------------------------------------------------

    def _all_tables(self) -> list[tuple]:
        # database, schema, name, column_names[], column_types[], temporary
        rows = self.con.execute("SHOW ALL TABLES").fetchall()
        keep = []
        for db, schema, name, colnames, coltypes, *_ in rows:
            if db in _SYSTEM_CATALOGS or schema in _SYSTEM_SCHEMAS:
                continue
            keep.append((db, schema, name, colnames, coltypes))
        return keep

    def _qualified(self, db: str, schema: str, name: str) -> str:
        if db == "memory" and schema == "main":
            return f'"{name}"'
        return f'"{db}"."{schema}"."{name}"'

    def schema_summary(self, sample_rows: int = 3, max_tables: int = 80) -> str:
        """A compact, model-readable description of every queryable table."""
        tables = self._all_tables()
        if not tables:
            return "(no data sources registered yet)"

        blocks: list[str] = []
        for db, schema, name, colnames, coltypes in tables[:max_tables]:
            qualified = self._qualified(db, schema, name)
            cols = ", ".join(
                f"{c}:{t}" for c, t in zip(colnames or [], coltypes or [])
            )
            header = f"TABLE {qualified}"
            try:
                n = self.con.execute(f"SELECT count(*) FROM {qualified}").fetchone()[0]
                header += f"  (~{n} rows)"
            except Exception:
                pass
            lines = [header, f"  columns: {cols}"]
            if sample_rows > 0:
                try:
                    sample = self.con.execute(
                        f"SELECT * FROM {qualified} LIMIT {sample_rows}"
                    ).df()
                    if not sample.empty:
                        preview = sample.to_string(index=False, max_colwidth=24)
                        lines.append(
                            "  sample:\n"
                            + "\n".join("    " + ln for ln in preview.splitlines())
                        )
                except Exception:
                    pass
            blocks.append("\n".join(lines))

        extra = ""
        if len(tables) > max_tables:
            extra = f"\n... and {len(tables) - max_tables} more tables."
        return "\n\n".join(blocks) + extra

    def table_names(self) -> list[str]:
        return [self._qualified(db, sc, nm) for db, sc, nm, _, _ in self._all_tables()]

    def close(self) -> None:
        self.con.close()

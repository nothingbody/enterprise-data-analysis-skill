"""Standard data-analysis report: collect evidence and render a self-contained HTML file.

The agent pins key findings during analysis (`report.add_table(...)`,
`report.add_chart(...)`, `report.add_markdown(...)`); the conclusion-first
narrative it writes at the end becomes the report body. `render_html` composes a
single offline HTML file (charts embedded as base64 PNG; no external assets).
"""

from __future__ import annotations

import base64
import html
import io
import re
from typing import Any

import pandas as pd

# Headless matplotlib with a CJK-capable font, configured once.
try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = [
        "Microsoft YaHei", "SimHei", "Microsoft JhengHei", "SimSun", "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False
    _HAS_MPL = True
except Exception:  # pragma: no cover - matplotlib optional at import time
    plt = None  # type: ignore
    _HAS_MPL = False


class Report:
    """Collects the artifacts that should appear in the final HTML report."""

    def __init__(self, sandbox: Any | None = None) -> None:
        self._sandbox = sandbox
        self._blocks: list[dict[str, Any]] = []

    def reset(self) -> None:
        self._blocks = []

    @property
    def blocks(self) -> list[dict[str, Any]]:
        return self._blocks

    def add_markdown(self, text: str, title: str | None = None) -> str:
        self._blocks.append({"type": "markdown", "title": title, "text": str(text)})
        return "added markdown block"

    # convenient alias
    def note(self, text: str, title: str | None = None) -> str:
        return self.add_markdown(text, title)

    def add_table(
        self,
        data: Any,
        title: str | None = None,
        note: str | None = None,
        max_rows: int = 100,
    ) -> str:
        df = self._coerce_df(data)
        self._blocks.append(
            {
                "type": "table",
                "title": title,
                "note": note,
                "df": df.head(max_rows),
                "total_rows": len(df),
                "max_rows": max_rows,
            }
        )
        return f"added table block ({len(df)} rows)"

    def add_chart(
        self, fig: Any = None, title: str | None = None, note: str | None = None
    ) -> str:
        if not _HAS_MPL:
            raise RuntimeError("matplotlib is not available; cannot render charts.")
        figure = fig if fig is not None else plt.gcf()
        buf = io.BytesIO()
        figure.tight_layout()
        figure.savefig(buf, format="png", dpi=120, bbox_inches="tight")
        plt.close(figure)
        png_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        self._blocks.append(
            {"type": "chart", "title": title, "note": note, "png": png_b64}
        )
        return "added chart block"

    def _coerce_df(self, data: Any) -> pd.DataFrame:
        if isinstance(data, str):
            if self._sandbox is None:
                raise ValueError("string data given but no SQL connection available")
            return self._sandbox.con.execute(data).df()
        if isinstance(data, pd.DataFrame):
            return data
        if isinstance(data, pd.Series):
            return data.to_frame()
        return pd.DataFrame(data)


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

# --- Markdown -> structured nodes (shared by the HTML and Word renderers) ----

def _is_table_row(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and s.count("|") >= 2


def _is_table_sep(line: str) -> bool:
    s = line.strip().strip("|")
    cells = [c.strip() for c in s.split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c != "")


def _split_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def parse_markdown(md: str) -> list[dict]:
    """Parse a small Markdown subset into nodes both renderers can consume.

    Node types: heading{level,text}, paragraph{text}, list{ordered,items[]},
    table{headers[],rows[][]}. Inline **bold** / `code` is left in the text and
    handled per-renderer.
    """
    lines = md.replace("\r\n", "\n").split("\n")
    nodes: list[dict] = []
    list_items: list[str] = []
    list_ordered: bool | None = None
    i = 0

    def flush_list() -> None:
        nonlocal list_ordered
        if list_items:
            nodes.append(
                {"type": "list", "ordered": bool(list_ordered), "items": list(list_items)}
            )
            list_items.clear()
            list_ordered = None

    while i < len(lines):
        raw = lines[i].rstrip()
        stripped = raw.strip()

        if not stripped:
            flush_list()
            i += 1
            continue

        # Markdown table: a row followed by a separator row.
        if _is_table_row(raw) and i + 1 < len(lines) and _is_table_sep(lines[i + 1]):
            flush_list()
            headers = _split_row(raw)
            rows: list[list[str]] = []
            i += 2
            while i < len(lines) and _is_table_row(lines[i]):
                rows.append(_split_row(lines[i]))
                i += 1
            nodes.append({"type": "table", "headers": headers, "rows": rows})
            continue

        m_h = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        m_ul = re.match(r"^[-*•]\s+(.*)$", stripped)
        m_ol = re.match(r"^\d+[.、)]\s*(.*)$", stripped)

        if m_h:
            flush_list()
            nodes.append({"type": "heading", "level": len(m_h.group(1)), "text": m_h.group(2)})
        elif m_ul:
            if list_ordered is True:
                flush_list()
            list_ordered = False
            list_items.append(m_ul.group(1))
        elif m_ol:
            if list_ordered is False:
                flush_list()
            list_ordered = True
            list_items.append(m_ol.group(1))
        else:
            flush_list()
            nodes.append({"type": "paragraph", "text": stripped})
        i += 1

    flush_list()
    return nodes


def _inline(text: str) -> str:
    """Escape, then apply **bold** and `code` inline formatting (HTML)."""
    out = html.escape(text)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"`([^`]+?)`", r"<code>\1</code>", out)
    return out


def _nodes_to_html(nodes: list[dict]) -> str:
    parts: list[str] = []
    for n in nodes:
        if n["type"] == "heading":
            level = min(max(n["level"], 2), 6)  # report title is h1; sections start at h2
            parts.append(f"<h{level}>{_inline(n['text'])}</h{level}>")
        elif n["type"] == "list":
            tag = "ol" if n["ordered"] else "ul"
            items = "".join(f"<li>{_inline(it)}</li>" for it in n["items"])
            parts.append(f"<{tag}>{items}</{tag}>")
        elif n["type"] == "table":
            head = "".join(f"<th>{_inline(c)}</th>" for c in n["headers"])
            body = "".join(
                "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>"
                for r in n["rows"]
            )
            parts.append(
                '<div class="table-wrap"><table class="rpt-table">'
                f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"
            )
        else:
            parts.append(f"<p>{_inline(n['text'])}</p>")
    return "\n".join(parts)


def md_to_html(md: str) -> str:
    """Render a small Markdown subset (headings, lists, tables, bold) to HTML."""
    return _nodes_to_html(parse_markdown(md))


def _render_block(block: dict[str, Any]) -> str:
    title = block.get("title")
    head = f'<h3>{html.escape(title)}</h3>' if title else ""
    note = block.get("note")
    note_html = f'<p class="note">{_inline(note)}</p>' if note else ""

    if block["type"] == "markdown":
        return f'<section class="block">{head}{md_to_html(block["text"])}</section>'

    if block["type"] == "table":
        df: pd.DataFrame = block["df"]
        table_html = df.to_html(index=False, border=0, classes="rpt-table", justify="left")
        trunc = ""
        if block["total_rows"] > block["max_rows"]:
            trunc = (
                f'<p class="note">共 {block["total_rows"]} 行，仅展示前 '
                f'{block["max_rows"]} 行。</p>'
            )
        return (
            f'<section class="block">{head}'
            f'<div class="table-wrap">{table_html}</div>{trunc}{note_html}</section>'
        )

    if block["type"] == "chart":
        img = f'data:image/png;base64,{block["png"]}'
        return (
            f'<section class="block">{head}'
            f'<div class="chart-wrap"><img src="{img}" alt="chart"></div>'
            f'{note_html}</section>'
        )

    return ""


_CSS = """
:root { --fg:#1f2933; --muted:#6b7280; --line:#e5e7eb; --accent:#2563eb; --bg:#f7f8fa; }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
  font-family:"Microsoft YaHei","Segoe UI","Helvetica Neue",Arial,sans-serif;
  line-height:1.7; font-size:15px; }
.page { max-width:920px; margin:0 auto; padding:32px 24px 64px; }
header.report-head { border-bottom:3px solid var(--accent); padding-bottom:16px; margin-bottom:24px; }
header.report-head h1 { font-size:26px; margin:0 0 6px; }
header.report-head .q { color:var(--fg); font-size:16px; margin:8px 0 0; }
.meta { display:flex; flex-wrap:wrap; gap:6px 20px; color:var(--muted); font-size:13px; margin-top:12px; }
.meta b { color:var(--fg); font-weight:600; }
h2 { font-size:20px; margin:28px 0 10px; padding-bottom:6px; border-bottom:1px solid var(--line); }
h3 { font-size:17px; margin:22px 0 8px; color:var(--accent); }
h4 { font-size:15px; margin:16px 0 6px; }
p { margin:8px 0; }
ul,ol { margin:8px 0 8px 4px; padding-left:22px; }
li { margin:4px 0; }
code { background:#eef1f5; padding:1px 5px; border-radius:4px; font-size:90%; }
.note { color:var(--muted); font-size:13px; }
section.block { background:#fff; border:1px solid var(--line); border-radius:10px;
  padding:16px 20px; margin:16px 0; box-shadow:0 1px 2px rgba(0,0,0,.03); }
.table-wrap { overflow-x:auto; }
table.rpt-table { border-collapse:collapse; width:100%; font-size:13.5px; }
table.rpt-table th, table.rpt-table td { border:1px solid var(--line); padding:7px 10px; text-align:left; white-space:nowrap; }
table.rpt-table thead th { background:#f1f5f9; font-weight:600; }
table.rpt-table tbody tr:nth-child(even) { background:#fafbfc; }
.chart-wrap { text-align:center; }
.chart-wrap img { max-width:100%; height:auto; }
footer.report-foot { margin-top:40px; padding-top:16px; border-top:1px solid var(--line);
  color:var(--muted); font-size:12.5px; }
@media print { body { background:#fff; } section.block { box-shadow:none; } }
"""


def render_html(meta: dict[str, Any], narrative: str, blocks: list[dict[str, Any]]) -> str:
    """Compose the full self-contained HTML report."""
    sources = meta.get("sources") or []
    src_html = "、".join(html.escape(s) for s in sources) if sources else "—"
    meta_row = (
        f'<div class="meta">'
        f'<span><b>数据源</b> {src_html}</span>'
        f'<span><b>生成时间</b> {html.escape(meta.get("generated_at", ""))}</span>'
        f'<span><b>分析模型</b> {html.escape(meta.get("model", ""))}</span>'
        f"</div>"
    )

    narrative_html = (
        f'<main class="narrative">{md_to_html(narrative)}</main>'
        if narrative.strip()
        else ""
    )

    blocks_html = ""
    if blocks:
        rendered = "\n".join(_render_block(b) for b in blocks)
        blocks_html = f"<h2>图表与数据明细</h2>{rendered}"

    question = html.escape(meta.get("question", ""))
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>数据分析报告</title>
<style>{_CSS}</style>
</head>
<body>
<div class="page">
<header class="report-head">
  <h1>数据分析报告</h1>
  <p class="q"><b>业务问题：</b>{question}</p>
  {meta_row}
</header>
{narrative_html}
{blocks_html}
<footer class="report-foot">
  本报告由数据分析 Agent 自动生成：基于所提供数据的一次性探索性分析，图表与数值均来自实际执行的查询。
  结论供业务参考，正式决策口径请结合指标治理与跨表校验。
</footer>
</div>
</body>
</html>"""

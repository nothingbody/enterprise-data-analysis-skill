"""Agent shell: drive Claude in a tool-use loop over the sandbox."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import anthropic

from .config import (
    BASE_URL,
    DEFAULT_MODEL,
    EFFORT,
    MAX_ITERATIONS,
    MAX_TOKENS,
    SELF_AUDIT,
)
from .datasource import DataRegistry
from .docx_writer import render_docx
from .prompts import AUDIT_INSTRUCTION, build_system_prompt
from .report import render_html
from .sandbox import Sandbox
from .tools import TOOLS, dispatch


def _text_of(message: Any) -> str:
    return "".join(b.text for b in message.content if b.type == "text").strip()


class DataAnalysisAgent:
    """A multi-turn data-analysis agent. The conversation (and the sandbox's
    Python namespace) persist across questions, so follow-ups build on prior work.
    """

    def __init__(
        self,
        registry: DataRegistry,
        model: str = DEFAULT_MODEL,
        *,
        output: str | None = None,
        self_audit: bool = SELF_AUDIT,
        verbose: bool = True,
        show_thinking: bool = True,
    ) -> None:
        self.client = (
            anthropic.Anthropic(base_url=BASE_URL) if BASE_URL else anthropic.Anthropic()
        )
        self.registry = registry
        self.sandbox = Sandbox(registry)
        self.model = model
        self.self_audit = self_audit
        # Claude-only request features (adaptive thinking, effort, prompt-cache
        # control) are sent only for genuine Claude models; other Anthropic-
        # compatible backends (DeepSeek, etc.) reject them.
        self.native = model.startswith("claude")
        self.output = output  # file path (.html) or directory; None = no report
        self.verbose = verbose
        self.show_thinking = show_thinking
        self.system = build_system_prompt(registry.schema_summary())
        self.messages: list[dict[str, Any]] = []
        self.last_report_path: str | None = None
        self._report_count = 0

    # -- public API ------------------------------------------------------

    def ask(self, question: str) -> str:
        """Answer one question, running tools as needed. Returns the final text.

        If an output location is configured, also writes a standard HTML report.
        """
        self.sandbox.report.reset()
        self.messages.append({"role": "user", "content": question})
        narrative = self._run_loop()
        if self.self_audit and not narrative.startswith("（"):
            narrative = self._audit_pass() or narrative
        if self.output:
            self._write_report(question, narrative)
        return narrative

    def _audit_pass(self) -> str:
        """A structured self-review pass: re-verify claims, decompose, re-emit."""
        self._emit("\n\033[36m▶ 自我审计与复核…\033[0m\n", err=True)
        self.messages.append({"role": "user", "content": AUDIT_INSTRUCTION})
        return self._run_loop()

    # -- report ----------------------------------------------------------

    def _write_report(self, question: str, narrative: str) -> None:
        base = Path(self._resolve_output_base())
        base.parent.mkdir(parents=True, exist_ok=True)
        meta = {
            "question": question,
            "model": self.model,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "sources": [
                r.get("source", r.get("table", r.get("alias", "")))
                for r in self.registry.registered
            ],
        }
        blocks = self.sandbox.report.blocks

        html_path = base.with_suffix(".html")
        html_path.write_text(render_html(meta, narrative, blocks), encoding="utf-8")

        docx_path = base.with_suffix(".docx")
        try:
            render_docx(meta, narrative, blocks, str(docx_path))
            self._emit(
                f"\n\033[32m✓ 报告已生成: {html_path}  |  {docx_path}\033[0m\n", err=True
            )
        except Exception as exc:  # noqa: BLE001 - HTML still written; surface docx failure
            self._emit(
                f"\n\033[32m✓ HTML 报告: {html_path}\033[0m"
                f"\n\033[33m! Word 生成失败: {exc}\033[0m\n",
                err=True,
            )
        self.last_report_path = str(html_path)

    def _resolve_output_base(self) -> str:
        """Return the output path WITHOUT extension; .html and .docx are appended."""
        self._report_count += 1
        out = Path(self.output)  # type: ignore[arg-type]
        if out.suffix.lower() in (".html", ".docx"):
            stem = out.with_suffix("")
            if self._report_count == 1:
                return str(stem)
            return str(stem.with_name(f"{stem.name}-{self._report_count:02d}"))
        return str(out / f"report-{self._report_count:02d}")

    # -- internals -------------------------------------------------------

    def _run_loop(self) -> str:
        for _ in range(MAX_ITERATIONS):
            final = self._stream_turn()

            if final.stop_reason == "refusal":
                note = "（请求被安全策略拒绝，无法继续该分析。）"
                self._emit("\n" + note + "\n")
                return note

            self.messages.append({"role": "assistant", "content": final.content})

            if final.stop_reason != "tool_use":
                return _text_of(final)

            tool_results = []
            for block in final.content:
                if block.type != "tool_use":
                    continue
                self._show_tool_call(block.name, block.input)
                output = dispatch(self.sandbox, block.name, block.input)
                self._show_tool_result(output)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": output,
                    }
                )
            self.messages.append({"role": "user", "content": tool_results})

        return "（已达到最大工具调用轮数，分析提前结束。）"

    def _stream_turn(self) -> Any:
        if self.native:
            kwargs: dict[str, Any] = {
                "max_tokens": MAX_TOKENS,
                "system": [
                    {
                        "type": "text",
                        "text": self.system,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                "thinking": {"type": "adaptive", "display": "summarized"},
                "output_config": {"effort": EFFORT},
            }
        else:
            kwargs = {
                "max_tokens": min(MAX_TOKENS, 8000),
                "system": self.system,
            }

        thinking_open = False
        with self.client.messages.stream(
            model=self.model,
            messages=self.messages,
            tools=TOOLS,
            **kwargs,
        ) as stream:
            for event in stream:
                if event.type == "content_block_delta":
                    delta = event.delta
                    if delta.type == "text_delta":
                        self._emit(delta.text)
                    elif delta.type == "thinking_delta" and self.show_thinking:
                        if not thinking_open:
                            self._emit("\n\033[2m[思考] ", err=True)
                            thinking_open = True
                        self._emit(delta.text, err=True)
                elif event.type == "content_block_stop" and thinking_open:
                    self._emit("\033[0m\n", err=True)
                    thinking_open = False
            self._emit("\n")
            return stream.get_final_message()

    # -- output ----------------------------------------------------------

    def _emit(self, text: str, *, err: bool = False) -> None:
        if not self.verbose:
            return
        stream = sys.stderr if err else sys.stdout
        stream.write(text)
        stream.flush()

    def _show_tool_call(self, name: str, tool_input: dict[str, Any]) -> None:
        if not self.verbose:
            return
        payload = tool_input.get("query") or tool_input.get("code") or ""
        snippet = payload.strip()
        if len(snippet) > 400:
            snippet = snippet[:400] + " ..."
        self._emit(f"\n\033[36m▶ {name}\033[0m\n{snippet}\n", err=True)

    def _show_tool_result(self, output: str) -> None:
        if not self.verbose:
            return
        preview = output if len(output) <= 800 else output[:800] + " ..."
        self._emit(f"\033[2m{preview}\033[0m\n", err=True)

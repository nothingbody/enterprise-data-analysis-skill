"""Runtime configuration, all overridable via environment variables."""

import os

# Default to Opus 4.8 (the recommended general-purpose model). Set
# DATA_AGENT_MODEL=claude-fable-5 for Anthropic's most capable model.
DEFAULT_MODEL = os.environ.get("DATA_AGENT_MODEL", "claude-opus-4-8")

# Optional base-URL override. Lets the agent run against any Anthropic-Messages-
# compatible endpoint (e.g. DeepSeek's https://api.deepseek.com/anthropic with
# model deepseek-chat). The Anthropic SDK also honors ANTHROPIC_BASE_URL itself.
BASE_URL = os.environ.get("DATA_AGENT_BASE_URL") or os.environ.get("ANTHROPIC_BASE_URL")

# Effort controls thinking depth / token spend on Opus 4.x and Fable 5.
EFFORT = os.environ.get("DATA_AGENT_EFFORT", "high")

# Hard ceiling on tool-use round trips per question, so a runaway loop stops.
MAX_ITERATIONS = int(os.environ.get("DATA_AGENT_MAX_ITERS", "40"))

# Rows of a result preview fed back to the model as a tool result.
PREVIEW_ROWS = int(os.environ.get("DATA_AGENT_PREVIEW_ROWS", "20"))

# Cap on the character length of any single tool result, to bound context use.
MAX_RESULT_CHARS = int(os.environ.get("DATA_AGENT_MAX_RESULT_CHARS", "6000"))

# Per-turn output cap (streaming, so well under the SDK timeout).
MAX_TOKENS = int(os.environ.get("DATA_AGENT_MAX_TOKENS", "16000"))

# After the first report, run one structured self-audit pass (re-verify every
# claim against tool results, force factor decomposition, gate small samples,
# rule out alternatives) and re-emit a revised report. Costs an extra round of
# model + tool calls; the single biggest lever on analytical reliability.
SELF_AUDIT = os.environ.get("DATA_AGENT_SELF_AUDIT", "1").lower() not in {"0", "false", "no"}

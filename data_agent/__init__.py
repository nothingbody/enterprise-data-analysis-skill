"""A general-purpose enterprise data-analysis agent.

Two layers:
- Skill core (provider-agnostic, scriptable): `DataRegistry` (DuckDB-backed
  multi-source registration + schema introspection) and `Sandbox` (persistent
  SQL + Python execution). Neither touches an LLM.
- Agent shell: `DataAnalysisAgent` drives Claude in a tool-use loop on top of
  the core.
"""

from .datasource import DataRegistry
from .sandbox import Sandbox
from .agent import DataAnalysisAgent

__version__ = "0.1.0"

__all__ = ["DataRegistry", "Sandbox", "DataAnalysisAgent", "__version__"]

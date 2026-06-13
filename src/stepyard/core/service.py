"""
Stepyard core service - Scheduler and Engine access.

Provides:
  - Engine    (re-exported from stepyard.engine.executor)
  - Scheduler (uses FlowResolver for flow file lookup)
"""

from __future__ import annotations

from stepyard.core.flow import FlowResolver
from stepyard.engine.executor import Engine  # noqa: F401
from stepyard.storage.facade import Storage


class Scheduler:
    """Thin wrapper providing flow-file resolution for CLI usage."""

    def __init__(self, storage: Storage) -> None:
        self.storage = storage
        self._resolver = FlowResolver(storage.project_dir)

    def find_flow_file(self, flow_name: str) -> str | None:
        """Resolve flow name → YAML file path."""
        return self._resolver.find(flow_name)


__all__ = ["Engine", "Scheduler"]

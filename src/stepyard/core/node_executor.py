"""
Stepyard subprocess node executor.

This module is the entry point for isolated node execution::

    python -m stepyard.core.node_executor

It reads a JSON payload from stdin, executes the requested node, and writes
a JSON result to stdout.  stderr is left for diagnostic output so it does
not corrupt the JSON channel.

The stdout/stderr redirect happens *inside* ``execute()`` - never at
module-level - so importing this module has no side effects.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import traceback
from typing import Any


def apply_limits(
    memory_limit_bytes: int | None = None,
    cpu_limit_seconds: int | None = None,
) -> None:
    """Enforce CPU time and address-space limits (Unix only)."""
    try:
        import resource  # noqa: PLC0415

        if cpu_limit_seconds is not None and cpu_limit_seconds > 0:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_limit_seconds, cpu_limit_seconds + 5))
        if memory_limit_bytes is not None and memory_limit_bytes > 0:
            resource.setrlimit(resource.RLIMIT_AS, (memory_limit_bytes, memory_limit_bytes))
    except (ImportError, ValueError, OSError) as exc:
        sys.stderr.write(f"Warning: Could not apply resource limits: {exc}\n")


def execute() -> None:
    """Read a node-invocation payload from stdin and write the result to stdout."""
    # Redirect stdout → stderr so accidental ``print()`` calls inside a node
    # do not corrupt the JSON result channel.
    original_stdout = sys.stdout
    sys.stdout = sys.stderr

    try:
        payload_data = sys.stdin.read()
        if not payload_data:
            raise ValueError("Empty input data (stdin is empty).")

        payload = json.loads(payload_data)

        node_name: str = payload["node_name"]
        inputs: dict[str, Any] = payload.get("inputs", {})
        run_id: str = payload.get("run_id", "test-run")
        step_id: str = payload.get("step_id", "test-step")
        project_dir: str = payload.get("project_dir") or os.getcwd()
        memory_limit: int | None = payload.get("memory_limit")
        cpu_limit: int | None = payload.get("cpu_limit")

        apply_limits(memory_limit, cpu_limit)

        from stepyard.plugin import discover_capabilities  # noqa: PLC0415
        from stepyard.plugins.execution import invoke_node  # noqa: PLC0415
        from stepyard.sdk.node import NodeContext, NodeStatus  # noqa: PLC0415

        registry = discover_capabilities(project_dir)
        func = registry.get_node(node_name)
        if not func:
            raise ImportError(f"Node '{node_name}' not found in the capability registry.")

        class _SubprocessLogger:
            def info(self, msg: str, *args: object, **_: object) -> None:
                sys.stderr.write(f"INFO: {msg % args if args else msg}\n")

            def warning(self, msg: str, *args: object, **_: object) -> None:
                sys.stderr.write(f"WARNING: {msg % args if args else msg}\n")

            def error(self, msg: str, *args: object, **_: object) -> None:
                sys.stderr.write(f"ERROR: {msg % args if args else msg}\n")

        ctx = NodeContext(run_id=run_id, step_id=step_id, logger=_SubprocessLogger())

        # Use the shared invocation core (same validation + ctx-injection as in-process).
        result = asyncio.run(invoke_node(func, inputs, ctx))

        response = {
            "status": result.status.value,
            "output": result.output,
            "error": result.error,
            "traceback": result.traceback,
            "metrics": result.metrics or ctx.metrics,
            "state": result.state,
            "stderr": result.stderr,
        }
        original_stdout.write(json.dumps(response))
        sys.exit(0 if result.status is NodeStatus.SUCCESS else 1)

    except Exception as exc:
        tb_str = traceback.format_exc()
        response = {"status": "failed", "error": str(exc), "traceback": tb_str}
        original_stdout.write(json.dumps(response))
        sys.exit(1)


if __name__ == "__main__":
    execute()

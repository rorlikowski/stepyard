"""Node invocation adapters for in-process and isolated plugin execution."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Protocol

from stepyard.plugins.execution import invoke_node
from stepyard.plugins.host import CapabilityProvider
from stepyard.sdk.node import NodeContext, NodeResult, NodeStatus


class NodeInvoker(Protocol):
    async def invoke(
        self,
        node_name: str,
        inputs: dict[str, Any],
        run_id: str,
        step_id: str,
        node_ctx: NodeContext,
    ) -> NodeResult: ...


class NodeInvocationService:
    """Invoke nodes using registry metadata from PluginHost."""

    def __init__(self, registry: CapabilityProvider, project_dir: str) -> None:
        self.registry = registry
        self.project_dir = project_dir

    async def invoke(
        self,
        node_name: str,
        inputs: dict[str, Any],
        run_id: str,
        step_id: str,
        node_ctx: NodeContext,
    ) -> NodeResult:
        info = self.registry.get_node_info(node_name)
        node_func = self.registry.get_node(node_name)

        if node_func is None:
            return NodeResult(
                status=NodeStatus.FAILED,
                error=(
                    f"Node '{node_name}' was not found. Discovery searched project "
                    f"'{self.project_dir}'. Run 'stepyard plugin sync' if the plugin "
                    "environment is missing, or 'stepyard tools list' to inspect available nodes."
                ),
            )

        if info and info.isolated and info.python_executable:
            return await self._run_subprocess(
                info.python_executable,
                node_name,
                inputs,
                run_id,
                step_id,
            )

        return await self._run_in_process(node_func, inputs, node_ctx)

    async def _run_subprocess(
        self,
        python_executable: str,
        node_name: str,
        inputs: dict[str, Any],
        run_id: str,
        step_id: str,
    ) -> NodeResult:
        payload = {
            "node_name": node_name,
            "inputs": inputs,
            "run_id": run_id,
            "step_id": step_id,
            "project_dir": self.project_dir,
        }
        proc = await asyncio.create_subprocess_exec(
            python_executable,
            "-m",
            "stepyard.core.node_executor",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(json.dumps(payload).encode("utf-8"))

        try:
            data = json.loads(stdout.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return NodeResult(
                status=NodeStatus.FAILED,
                error="Plugin subprocess returned invalid JSON.",
                stderr=stderr.decode("utf-8", errors="replace"),
                traceback=stdout.decode("utf-8", errors="replace"),
            )

        status = data.get("status", "failed")
        return NodeResult(
            status=status,
            output=data.get("output"),
            error=data.get("error"),
            traceback=data.get("traceback"),
            metrics=data.get("metrics") or {},
            state=data.get("state"),
            stderr=(data.get("stderr") or "") + stderr.decode("utf-8", errors="replace"),
        )

    async def _run_in_process(
        self,
        node_func: Any,
        inputs: dict[str, Any],
        node_ctx: NodeContext,
    ) -> NodeResult:
        return await invoke_node(node_func, inputs, node_ctx)


def default_node_invoker(registry: CapabilityProvider, project_dir: str) -> NodeInvoker:
    return NodeInvocationService(registry, project_dir)

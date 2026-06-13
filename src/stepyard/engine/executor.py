"""
Stepyard Engine - executes a single Flow run step-by-step.

Architecture
------------
The Engine orchestrates flow execution by delegating to focused helpers:

* :class:`~stepyard.engine.recorder.StepRecorder`   - all step persistence
* :class:`~stepyard.engine.evaluator.ConditionEvaluator` - if/loop/while logic
* :class:`~stepyard.engine.navigation.FlowNavigator`     - next-step resolution
* :class:`~stepyard.engine.strategies.NodeExecutionStrategy` - retry + hooks
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from stepyard.config import settings
from stepyard.core.expressions import resolve_variables
from stepyard.core.flow import Flow
from stepyard.core.models import RunStatus
from stepyard.engine.evaluator import ConditionEvaluator
from stepyard.engine.navigation import FlowNavigationError, FlowNavigator
from stepyard.engine.recorder import StepRecorder
from stepyard.engine.strategies import NodeExecutionStrategy
from stepyard.plugin import CapabilityRegistry, discover_capabilities
from stepyard.plugins.invoker import NodeInvoker, default_node_invoker
from stepyard.sdk.node import NodeResult, NodeStatus
from stepyard.storage.facade import Storage

logger = logging.getLogger("stepyard.engine")


@dataclass
class StepExecutionState:
    all_outputs: list[Any] = field(default_factory=list)
    has_error: bool = False
    error_msg: str | None = None


def _update_step_context(steps_dict: dict[str, Any], path: str, value: dict[str, Any]) -> None:
    """Update the steps context for both flat and dot-notation lookups."""
    steps_dict[path] = value
    parts = path.split(".")
    current = steps_dict
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]

    last_part = parts[-1]
    if last_part not in current or not isinstance(current[last_part], dict):
        current[last_part] = value
    else:
        current[last_part].update(value)


class Engine:
    """Executes a single Flow run step-by-step.

    Parameters
    ----------
    storage:
        Persistence layer.  All state changes are written here immediately.
    max_step_visits:
        Upper bound on how many times a single step may be visited (prevents
        infinite loops).  Defaults to ``settings.max_step_visits``.
    registry:
        Pre-built capability registry.  Discovered automatically when omitted.
    node_invoker:
        Custom node invoker.  Built from *registry* when omitted.
    """

    def __init__(
        self,
        storage: Storage,
        max_step_visits: int | None = None,
        registry: CapabilityRegistry | None = None,
        node_invoker: NodeInvoker | None = None,
    ) -> None:
        self.storage = storage
        self.max_step_visits = (
            max_step_visits if max_step_visits is not None else settings.max_step_visits
        )
        self.registry = registry or discover_capabilities(storage.project_dir)
        self.node_invoker = node_invoker or default_node_invoker(self.registry, storage.project_dir)
        self._recorder = StepRecorder(storage)
        self._evaluator = ConditionEvaluator()

    # ── Public API ─────────────────────────────────────────────────────────

    async def execute_run(
        self,
        run_id: str,
        flow: Flow,
        vars: dict[str, Any] | None = None,
    ) -> None:
        """Execute *flow* for *run_id*, persisting every state change."""
        logger.info("Starting flow execution: %s (run_id=%s)", flow.model.name, run_id)
        self.storage.update_run_status(run_id, RunStatus.RUNNING.value)

        # Build one strategy instance per run (not per node).
        strategy = NodeExecutionStrategy(
            storage=self.storage,
            registry=self.registry,
            node_invoker=self.node_invoker,
        )

        # Build the merged env: dotenv files first (first file wins when a key
        # appears in multiple files), then explicit env: values override them.
        # Finally, apply the merged map to os.environ as *defaults* - existing
        # OS/shell/.env values always win.
        dotenv_env: dict[str, str] = {}
        project_dir = Path(self.storage.project_dir)
        for dotenv_path in flow.model.dotenv:
            resolved = (
                Path(dotenv_path) if Path(dotenv_path).is_absolute() else project_dir / dotenv_path
            )
            if resolved.is_file():
                try:
                    with open(resolved, encoding="utf-8") as _f:
                        for _line in _f:
                            _line = _line.strip()
                            if _line and not _line.startswith("#") and "=" in _line:
                                _k, _v = _line.split("=", 1)
                                _k = _k.strip()
                                _v = _v.strip().strip('"').strip("'")
                                if _k not in dotenv_env:  # first file wins
                                    dotenv_env[_k] = _v
                except Exception as _exc:
                    logger.warning("Failed to load dotenv file '%s': %s", resolved, _exc)
            else:
                logger.warning("dotenv file not found: %s", resolved)

        # Explicit env: values override dotenv values.
        merged_env = {**dotenv_env, **flow.model.env}

        applied_env_keys: list[str] = []
        for key, value in merged_env.items():
            if key not in os.environ:
                os.environ[key] = value
                applied_env_keys.append(key)

        context: dict[str, Any] = {
            "steps": {},
            "env": dict(os.environ),
            "vars": vars or {},
            "visits": {},
            "_step_status": {},
            "_existing_step_status": {},
        }

        current_run = self.storage.get_run(run_id)
        if current_run:
            payload = current_run.get("trigger_payload")
            context["trigger"] = {
                "run_id": run_id,
                "type": current_run.get("trigger_type"),
                "event_id": current_run.get("trigger_event_id"),
                "payload": payload if payload is not None else {},
            }

        # Hydrate context from already-completed steps (resume support).
        step_runs = {sr["step_id"]: sr for sr in self.storage.get_step_runs(run_id)}
        for step_id, existing in step_runs.items():
            if existing["status"] in ("completed", "skipped"):
                context["_existing_step_status"][step_id] = existing["status"]
            if existing["status"] == "completed":
                try:
                    out_val = (
                        json.loads(existing["output"]) if existing["output"] is not None else None
                    )
                except (json.JSONDecodeError, TypeError):
                    out_val = existing["output"]
                logical_step_id = step_id.split("#", 1)[0]
                _update_step_context(context["steps"], logical_step_id, {"output": out_val})

        run_failed = False
        run_error: str | None = None
        navigator = FlowNavigator(flow.model.steps)
        visit_counts: dict[str, int] = {}
        step_index: int | None = 0

        try:
            while step_index is not None:
                step = flow.model.steps[step_index]
                visit_counts[step.id] = visit_counts.get(step.id, 0) + 1
                context["visits"][step.id] = visit_counts[step.id]

                try:
                    navigator.validate_visit_limit(
                        step, visit_counts[step.id], self.max_step_visits
                    )
                except FlowNavigationError as exc:
                    run_failed = True
                    run_error = str(exc)
                    logger.error("Flow navigation error: %s", exc)
                    break

                execution_id = navigator.execution_id(step.id, visit_counts[step.id])
                failed, error = await self._execute_step(
                    step=step,
                    run_id=run_id,
                    context=context,
                    execution_id=execution_id,
                    context_id=step.id,
                    allow_reentry=visit_counts[step.id] > 1,
                    strategy=strategy,
                )

                # Step may have halted the run for approval / input.
                current_run = self.storage.get_run(run_id)
                if current_run and current_run.get("status") in RunStatus.suspended_values():
                    logger.info(
                        "Flow '%s' (run_id=%s) halted with status '%s'.",
                        flow.model.name,
                        run_id,
                        current_run["status"],
                    )
                    return

                if failed:
                    run_failed = True
                    run_error = error
                    break

                if context["_step_status"].get(execution_id) == "skipped":
                    step_index = step_index + 1 if step_index + 1 < len(flow.model.steps) else None
                    continue

                try:
                    step_index = navigator.next_index(step_index, step, context)
                except FlowNavigationError as exc:
                    run_failed = True
                    run_error = str(exc)
                    logger.error("Flow navigation error: %s", exc)
                    break

            if run_failed:
                logger.error("Flow '%s' (run_id=%s) failed: %s", flow.model.name, run_id, run_error)
                self.storage.update_run_status(run_id, RunStatus.FAILED.value, error=run_error)
            else:
                logger.info("Flow '%s' (run_id=%s) completed.", flow.model.name, run_id)
                self.storage.update_run_status(run_id, RunStatus.COMPLETED.value)
        finally:
            for key in applied_env_keys:
                os.environ.pop(key, None)

    # ── Step orchestrator ───────────────────────────────────────────────────

    async def _execute_step(
        self,
        step: Any,
        run_id: str,
        context: dict[str, Any],
        parent_iter_id: str | None = None,
        execution_id: str | None = None,
        context_id: str | None = None,
        allow_reentry: bool = False,
        strategy: NodeExecutionStrategy | None = None,
    ) -> tuple[bool, str | None]:
        step_id_key = context_id or (f"{parent_iter_id}.{step.id}" if parent_iter_id else step.id)
        run_step_id = execution_id or step_id_key

        existing_status = context["_existing_step_status"].get(run_step_id)
        if existing_status in ("completed", "skipped"):
            context["_step_status"][run_step_id] = existing_status
            return False, None

        if step_id_key in context["steps"] and not allow_reentry:
            context["_step_status"][run_step_id] = "completed"
            return False, None

        logger.info("Running step: %s", run_step_id)

        # ── Evaluate if-condition ───────────────────────────────────────────
        if step.if_cond:
            skip, error_msg = self._evaluator.evaluate_if(step, context)
            if error_msg:
                self._recorder.start(run_id, run_step_id, status="failed")
                self._recorder.fail(run_id, run_step_id, error=error_msg)
                context["_step_status"][run_step_id] = "failed"
                return True, error_msg
            if skip:
                logger.info("Skipped step '%s' (if condition not met)", run_step_id)
                self._recorder.skip(run_id, run_step_id)
                context["_step_status"][run_step_id] = "skipped"
                return False, None

        # ── Resolve loop items ──────────────────────────────────────────────
        loop_items, is_loop, is_while, loop_error = self._evaluator.resolve_loop(step, context)
        if loop_error:
            self._recorder.start(run_id, run_step_id, status="failed")
            self._recorder.fail(run_id, run_step_id, error=loop_error)
            context["_step_status"][run_step_id] = "failed"
            return True, loop_error

        if is_loop and not loop_items:
            logger.info("Skipped step '%s' (loop list is empty)", step_id_key)
            self._recorder.skip(run_id, run_step_id)
            context["_step_status"][run_step_id] = "skipped"
            return False, None

        state = StepExecutionState()
        self._recorder.start(run_id, run_step_id, status="running", inputs={})

        suspended = await self._run_step_iterations(
            step=step,
            step_id_key=step_id_key,
            run_step_id=run_step_id,
            run_id=run_id,
            context=context,
            loop_items=loop_items,
            is_loop=is_loop,
            is_while=is_while,
            state=state,
            strategy=strategy,
        )
        if suspended is not None:
            return suspended

        return self._finalize_step(
            step=step,
            step_id_key=step_id_key,
            run_step_id=run_step_id,
            run_id=run_id,
            context=context,
            all_outputs=state.all_outputs,
            is_loop=is_loop,
            is_while=is_while,
            step_has_error=state.has_error,
            step_error_msg=state.error_msg,
        )

    # ── Iteration loop ──────────────────────────────────────────────────────

    async def _run_step_iterations(
        self,
        step: Any,
        step_id_key: str,
        run_step_id: str,
        run_id: str,
        context: dict[str, Any],
        loop_items: list[Any],
        is_loop: bool,
        is_while: bool,
        state: StepExecutionState,
        strategy: NodeExecutionStrategy | None = None,
    ) -> tuple[bool, str | None] | None:
        loop_idx = 0
        while True:
            # ── Determine whether to continue ───────────────────────────────
            if is_loop:
                if loop_idx >= len(loop_items):
                    break
                loop_item = loop_items[loop_idx]
            elif is_while:
                _update_step_context(
                    context["steps"],
                    step_id_key,
                    {"output": state.all_outputs[-1] if state.all_outputs else None},
                )
                should_stop, while_error = self._evaluator.check_while(step, context)
                if while_error:
                    state.has_error = True
                    state.error_msg = while_error
                    self._recorder.fail(run_id, run_step_id, error=while_error)
                    context["_step_status"][run_step_id] = "failed"
                    break
                if should_stop:
                    break
                loop_item = None
            else:
                if loop_idx > 0:
                    break
                loop_item = None

            iter_id = _iter_id(run_step_id, loop_idx, is_loop, is_while)
            if is_loop:
                context["item"] = loop_item

            # ── Resolve inputs ──────────────────────────────────────────────
            try:
                resolved_inputs = resolve_variables(step.with_config, context)
            except Exception as exc:
                error_msg = f"Error evaluating parameters of step '{step_id_key}': {exc}"
                logger.error(error_msg)
                state.has_error = True
                state.error_msg = error_msg
                if is_loop or is_while:
                    self._recorder.fail(run_id, iter_id, error=error_msg)
                break

            # ── Execute with optional timeout ───────────────────────────────
            self._recorder.start(run_id, iter_id, status="running", inputs=resolved_inputs)
            timeout_sec = _parse_timeout(step)
            res = await self._execute_step_iteration(
                step=step,
                run_id=run_id,
                iter_id=iter_id,
                resolved_inputs=resolved_inputs,
                context=context,
                timeout=timeout_sec,
                strategy=strategy,
            )

            if res.status is NodeStatus.SUSPENDED:
                self._recorder.suspend(
                    run_id,
                    iter_id,
                    resolved_inputs=resolved_inputs,
                    state=res.state or {},
                )
                return False, None

            if res.status is NodeStatus.SUCCESS:
                state.all_outputs.append(res.output)
            else:
                state.has_error = True
                state.error_msg = res.error
                self._recorder.fail(run_id, iter_id, error=state.error_msg)
                if not getattr(step, "continue_on_error", False):
                    break
                state.all_outputs.append({"error": state.error_msg})

            loop_idx += 1

        return None

    async def _execute_step_iteration(
        self,
        step: Any,
        run_id: str,
        iter_id: str,
        resolved_inputs: dict[str, Any],
        context: dict[str, Any],
        timeout: float | None = None,
        strategy: NodeExecutionStrategy | None = None,
    ) -> NodeResult:
        if getattr(step, "steps", None) is not None:
            coro = self._execute_group(step, run_id, iter_id, context, strategy=strategy)
        else:
            coro = self._execute_node(
                step, run_id, iter_id, resolved_inputs, context, strategy=strategy
            )

        if timeout is not None:
            try:
                return await asyncio.wait_for(coro, timeout=timeout)
            except asyncio.TimeoutError:
                error_msg = (
                    f"Step '{iter_id}' timed out after {timeout}s (timeout={step.timeout!r})"
                )
                logger.error(error_msg)
                return NodeResult(status=NodeStatus.FAILED, error=error_msg)

        return await coro

    # ── Group and node execution ────────────────────────────────────────────

    async def _execute_group(
        self,
        step: Any,
        run_id: str,
        iter_id: str,
        context: dict[str, Any],
        strategy: NodeExecutionStrategy | None = None,
    ) -> NodeResult:
        for child in step.steps:
            child_failed, child_error = await self._execute_step(
                step=child,
                run_id=run_id,
                context=context,
                parent_iter_id=iter_id,
                strategy=strategy,
            )
            current_run = self.storage.get_run(run_id)
            if current_run and current_run.get("status") in RunStatus.suspended_values():
                return NodeResult(
                    status=NodeStatus.SUSPENDED, state={"reason": "group_child_suspended"}
                )
            if child_failed:
                return NodeResult(status=NodeStatus.FAILED, error=child_error)
        return NodeResult(status=NodeStatus.SUCCESS, output={"status": "group_completed"})

    async def _execute_node(
        self,
        step: Any,
        run_id: str,
        iter_id: str,
        resolved_inputs: dict[str, Any],
        context: dict[str, Any],
        strategy: NodeExecutionStrategy | None = None,
    ) -> NodeResult:
        strat = strategy or NodeExecutionStrategy(
            storage=self.storage,
            registry=self.registry,
            node_invoker=self.node_invoker,
        )
        return await strat.execute(step, run_id, iter_id, resolved_inputs, context)

    # ── Step finalization ───────────────────────────────────────────────────

    def _finalize_step(
        self,
        step: Any,
        step_id_key: str,
        run_step_id: str,
        run_id: str,
        context: dict[str, Any],
        all_outputs: list[Any],
        is_loop: bool,
        is_while: bool,
        step_has_error: bool,
        step_error_msg: str | None,
    ) -> tuple[bool, str | None]:
        final_output = (
            all_outputs if (is_loop or is_while) else (all_outputs[0] if all_outputs else None)
        )

        if step_has_error and not getattr(step, "continue_on_error", False):
            self._recorder.fail(run_id, run_step_id, error=step_error_msg, output=final_output)
            context["_step_status"][run_step_id] = "failed"
            context["_existing_step_status"][run_step_id] = "failed"
            return True, step_error_msg

        if is_loop and "item" in context:
            del context["item"]

        if step_has_error:
            logger.info("Step '%s' had errors but continue_on_error=True; continuing.", step_id_key)
            _update_step_context(
                context["steps"], step_id_key, {"output": final_output, "error": step_error_msg}
            )
            self._recorder.fail(run_id, run_step_id, error=step_error_msg, output=final_output)
            context["_step_status"][run_step_id] = "failed"
            context["_existing_step_status"][run_step_id] = "failed"
            return False, None

        self._recorder.complete(run_id, run_step_id, output=final_output)
        _update_step_context(context["steps"], step_id_key, {"output": final_output})
        context["_step_status"][run_step_id] = "completed"
        context["_existing_step_status"][run_step_id] = "completed"
        return False, None


# ── Module-level helpers ────────────────────────────────────────────────────


def _iter_id(step_id_key: str, loop_idx: int, is_loop: bool, is_while: bool) -> str:
    if is_loop or is_while:
        return f"{step_id_key}[{loop_idx + 1}]"
    return step_id_key


def _parse_timeout(step: Any) -> float | None:
    """Parse the ``timeout`` field of a step into seconds (float) or None."""
    raw = getattr(step, "timeout", None)
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        raw = raw.strip()
        if raw.endswith("s"):
            try:
                return float(raw[:-1])
            except ValueError:
                pass
        if raw.endswith("m"):
            try:
                return float(raw[:-1]) * 60
            except ValueError:
                pass
        try:
            return float(raw)
        except ValueError:
            logger.warning("Could not parse step timeout %r; ignoring.", raw)
    return None

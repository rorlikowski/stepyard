"""
Stepyard Engine Strategies - step execution with retries and hook dispatch.
"""

from __future__ import annotations

import logging
from typing import Any

from tenacity import AsyncRetrying, RetryError, stop_after_attempt, wait_exponential

from stepyard.core.errors import NodeExecutionError, TransientError
from stepyard.plugin import CapabilityRegistry, discover_capabilities
from stepyard.plugins.invoker import NodeInvoker, default_node_invoker
from stepyard.sdk.node import NodeContext, NodeResult, NodeStatus
from stepyard.storage.facade import Storage

logger = logging.getLogger("stepyard.engine.strategies")


class NodeExecutionStrategy:
    """Executes a single action node with retries and hook dispatch."""

    def __init__(
        self,
        storage: Storage,
        registry: CapabilityRegistry | None = None,
        node_invoker: NodeInvoker | None = None,
    ) -> None:
        self.storage = storage
        self.registry = registry or discover_capabilities(storage.project_dir)
        self.node_invoker = node_invoker or default_node_invoker(self.registry, storage.project_dir)

    async def execute(
        self,
        step: Any,
        run_id: str,
        iter_id: str,
        resolved_inputs: dict[str, Any],
        context: dict[str, Any],
    ) -> NodeResult:
        node_name = step.uses

        max_attempts = 1
        wait_kw: dict[str, Any] = {}
        if getattr(step, "retry", None):
            if isinstance(step.retry, int):
                max_attempts = step.retry
            else:
                max_attempts = step.retry.attempts
                wait_kw = {
                    "multiplier": step.retry.initial_delay,
                    "exp_base": step.retry.backoff_factor,
                }

        node_res: NodeResult | None = None
        node_ctx = NodeContext(run_id=run_id, step_id=iter_id)

        # 1. Run before_execute hooks - isolated so a broken hook never silently
        #    kills the step.  A PluginError from a hook is logged and skipped.
        for hook in self.registry.hooks:
            try:
                hook_res = await hook.before_execute(node_ctx, step, resolved_inputs)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Hook %s.before_execute raised an error for step '%s': %s",
                    type(hook).__name__,
                    iter_id,
                    exc,
                )
                continue
            if hook_res is not None:
                return hook_res

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(max_attempts),
                wait=wait_exponential(**wait_kw) if wait_kw else None,
                reraise=True,
            ):
                with attempt:
                    attempt_num = attempt.retry_state.attempt_number
                    self.storage.create_step_run(
                        run_id,
                        iter_id,
                        status="running",
                        attempt=attempt_num,
                        inputs=resolved_inputs,
                    )

                    node_res = await self.node_invoker.invoke(
                        node_name,
                        resolved_inputs,
                        run_id,
                        iter_id,
                        node_ctx,
                    )

                    if node_res.status is NodeStatus.SUCCESS:
                        self.storage.update_step_run(
                            run_id, iter_id, status="completed", output=node_res.output
                        )
                        # 2. Run after_execute hooks on success - same isolation.
                        node_res = await self._run_after_hooks(
                            hook_list=self.registry.hooks,
                            node_ctx=node_ctx,
                            step=step,
                            node_res=node_res,
                            iter_id=iter_id,
                        )
                        return node_res

                    logger.warning(
                        "Step '%s' failed (attempt %d/%d): %s",
                        iter_id,
                        attempt_num,
                        max_attempts,
                        node_res.error,
                    )
                    # Raise TransientError so tenacity will retry; permanent
                    # failures are wrapped in NodeExecutionError and not retried.
                    raise TransientError(node_res.error or "node returned failed status")

        except RetryError:
            error_msg = node_res.error if node_res else "Step failed after all retry attempts"
        except (TransientError, NodeExecutionError) as exc:
            error_msg = str(exc)
        except Exception as exc:
            error_msg = str(exc)

        final_result = NodeResult(status=NodeStatus.FAILED, error=error_msg)
        # 3. Run after_execute hooks even on failure so hooks can clean up or alert.
        final_result = await self._run_after_hooks(
            hook_list=self.registry.hooks,
            node_ctx=node_ctx,
            step=step,
            node_res=final_result,
            iter_id=iter_id,
        )
        return final_result

    @staticmethod
    async def _run_after_hooks(
        *,
        hook_list: list[Any],
        node_ctx: NodeContext,
        step: Any,
        node_res: NodeResult,
        iter_id: str,
    ) -> NodeResult:
        """Run after_execute hooks with per-hook error isolation."""
        for hook in hook_list:
            try:
                node_res = await hook.after_execute(node_ctx, step, node_res)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Hook %s.after_execute raised an error for step '%s': %s",
                    type(hook).__name__,
                    iter_id,
                    exc,
                )
        return node_res

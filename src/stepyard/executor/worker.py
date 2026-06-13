from __future__ import annotations

import asyncio
import logging

from stepyard.config import settings
from stepyard.core.flow import FlowResolver
from stepyard.core.models import RunStatus
from stepyard.executor.process_manager import ProcessManager
from stepyard.logging_.log_store import LogStore
from stepyard.storage.facade import Storage

logger = logging.getLogger("stepyard.executor.worker")


class ExecutorWorker:
    """Worker that polls the storage queue and spawns flows."""

    def __init__(
        self,
        storage: Storage,
        process_manager: ProcessManager,
        log_store: LogStore,
        tick_interval: float = settings.executor_tick_interval,
        max_concurrent: int = settings.max_concurrent_flows,
    ) -> None:
        self.storage = storage
        self.process_manager = process_manager
        self.log_store = log_store
        self.tick_interval = tick_interval
        self.max_concurrent = max_concurrent
        self._resolver = FlowResolver(storage.project_dir)

    async def run_forever(self) -> None:
        logger.info(
            "Executor worker started (tick=%.0fs, max_concurrent=%d)",
            self.tick_interval,
            self.max_concurrent,
        )
        try:
            while True:
                self._process_queue_and_reap()
                await asyncio.sleep(self.tick_interval)
        except asyncio.CancelledError:
            logger.info("Executor worker stopping.")

    def _process_queue_and_reap(self) -> None:
        self._kill_cancelled_runs()
        self._reap_finished()
        self._spawn_queued()

    def _kill_cancelled_runs(self) -> None:
        for fp in self.process_manager.list_running():
            run = self.storage.get_run(fp.run_id)
            if run and run.get("status") == "cancelled":
                logger.info("Run '%s' was cancelled in DB. Killing process %d.", fp.run_id, fp.pid)
                self.process_manager.kill_flow(fp.run_id)

    def _reap_finished(self) -> None:
        for fp, exit_code in self.process_manager.reap_finished():
            logger.info(
                "Flow '%s' (run_id=%s, pid=%d) exited with code %d",
                fp.flow_name,
                fp.run_id,
                fp.pid,
                exit_code,
            )
            self.storage.record_process_exit(fp.run_id, exit_code)

            run = self.storage.get_run(fp.run_id)
            # Never overwrite terminal or suspended statuses - suspended runs
            # (waiting_for_approval / waiting_for_input) exit with code 0 from
            # the runner, but guard here too in case of unexpected crashes.
            safe_statuses = {"failed", "completed", "cancelled"} | RunStatus.suspended_values()
            if run and run["status"] not in safe_statuses:
                if exit_code != 0:
                    self.storage.update_run_status(
                        fp.run_id,
                        "failed",
                        error=f"Flow process exited with code {exit_code}",
                    )
                else:
                    self.storage.update_run_status(fp.run_id, "completed")

    def _spawn_queued(self) -> None:
        running_count = len(self.process_manager.list_running())
        if running_count >= self.max_concurrent:
            return

        queued = self.storage.list_queued_runs()
        slots = self.max_concurrent - running_count

        for run in queued[:slots]:
            run_id = run["id"]
            flow_name = run["flow_name"]

            flow_file = self._resolver.find(flow_name)
            if not flow_file:
                logger.error(
                    "Flow file for '%s' not found - cancelling run_id=%s", flow_name, run_id
                )
                self.storage.update_run_status(run_id, "cancelled", error="Flow file not found")
                continue

            try:
                fp = self.process_manager.spawn_flow(
                    run_id=run_id,
                    flow_name=flow_name,
                    flow_file=flow_file,
                    project_dir=self.storage.project_dir,
                )
                self.storage.register_process(run_id, fp.pid, str(fp.log_path))
                self.storage.update_run_status(run_id, "running")
            except Exception as exc:
                logger.error("Failed to spawn flow '%s': %s", flow_name, exc)
                self.storage.update_run_status(run_id, "failed", error=str(exc))

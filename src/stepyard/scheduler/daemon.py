"""
Stepyard Scheduler Daemon.

The daemon is a long-running supervisor process that:
1. Uses APScheduler to schedule triggers from YAML flows.
2. Creates a queued run in storage when a trigger fires.
3. Periodically spawns each queued run as an isolated subprocess.
4. Reaps finished processes and records their exit codes.

Entry point
-----------
    python -m stepyard.scheduler.daemon --project-dir <dir>
"""

from __future__ import annotations

import asyncio
import datetime
import inspect
import logging
import os
import sys
import uuid

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from stepyard.config import settings
from stepyard.core.flow import Flow
from stepyard.logging_.log_store import LogStore
from stepyard.plugin import discover_capabilities
from stepyard.scheduler.triggers import build_apscheduler_trigger
from stepyard.storage.facade import Storage

logger = logging.getLogger("stepyard.scheduler.daemon")

# Re-exported for external consumers that import these constants from this module.
MAX_CONCURRENT_FLOWS = settings.max_concurrent_flows
TICK_INTERVAL = settings.scheduler_tick_interval


class SchedulerDaemon:
    """Supervisor daemon for Stepyard scheduled and queued flow executions."""

    def __init__(
        self,
        storage: Storage,
        log_store: LogStore,
    ) -> None:
        self.storage = storage
        self.log_store = log_store
        self.scheduler = AsyncIOScheduler()

    async def run_forever(self) -> None:
        logger.info("Scheduler daemon started")
        self._load_flow_jobs()
        self.scheduler.start()

        try:
            while True:
                await asyncio.sleep(3600)
        except (asyncio.CancelledError, KeyboardInterrupt):
            logger.info("Scheduler daemon stopping.")
            self.scheduler.shutdown()

    def _load_flow_jobs(self) -> None:
        flows_dir = os.path.join(self.storage.project_dir, "flows")
        if not os.path.isdir(flows_dir):
            return

        registry = discover_capabilities(self.storage.project_dir)
        for filename in os.listdir(flows_dir):
            if not filename.endswith((".yaml", ".yml")):
                continue
            filepath = os.path.join(flows_dir, filename)
            try:
                flow = Flow.from_file(filepath)
                if not self.storage.is_flow_active(flow.model.name):
                    continue
                if not flow.model.trigger:
                    continue

                if flow.model.trigger.mode == "console":
                    logger.debug("Skipping console trigger for '%s'", flow.model.name)
                    continue

                res = build_apscheduler_trigger(flow.model.trigger, registry=registry)
                if not res:
                    continue

                trigger, trigger_type = res

                if inspect.isasyncgen(trigger):
                    asyncio.create_task(
                        self._consume_event_stream(trigger, flow.model.name, trigger_type)
                    )
                    logger.info(
                        "Started async event stream for flow '%s' (type=%s)",
                        flow.model.name,
                        trigger_type,
                    )
                else:
                    self.scheduler.add_job(
                        self._fire_trigger,
                        trigger=trigger,
                        args=[flow.model.name, trigger_type],
                        id=f"flow_{flow.model.name}",
                        replace_existing=True,
                    )
                    logger.info(
                        "Registered APScheduler job for flow '%s' (type=%s)",
                        flow.model.name,
                        trigger_type,
                    )
            except Exception as exc:
                logger.error("Error loading triggers from '%s': %s", filepath, exc)

    def _fire_trigger(self, flow_name: str, trigger_type: str, payload: dict | None = None) -> None:
        # Prevent concurrent executions if one is already active
        if bool(self.storage.list_active_runs(flow_name)):
            logger.debug("Skipping trigger for '%s': active run exists", flow_name)
            return

        run_id = f"run-{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}-{uuid.uuid4().hex[:6]}"
        self.storage.create_run(
            run_id, flow_name, trigger_type=trigger_type, trigger_payload=payload
        )
        logger.info(
            "Trigger '%s' fired for '%s' → queued run_id=%s", trigger_type, flow_name, run_id
        )

    async def _consume_event_stream(self, stream, flow_name: str, trigger_type: str) -> None:
        try:
            async for payload in stream:
                self._fire_trigger(flow_name, trigger_type, payload)
        except asyncio.CancelledError:
            logger.info("Event stream consumer for %s cancelled.", flow_name)
        except Exception as exc:
            logger.error("Event stream error for %s: %s", flow_name, exc)


def _configure_logging(log_path: str | None = None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_path:
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        handlers=handlers,
    )

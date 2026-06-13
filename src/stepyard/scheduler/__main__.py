import argparse
import asyncio
import logging
import os
import sys

from stepyard.executor.process_manager import ProcessManager
from stepyard.executor.worker import ExecutorWorker
from stepyard.logging_.log_store import LogStore
from stepyard.scheduler.daemon import (
    MAX_CONCURRENT_FLOWS,
    TICK_INTERVAL,
    SchedulerDaemon,
    _configure_logging,
)
from stepyard.storage.facade import Storage

logger = logging.getLogger("stepyard.scheduler.daemon")


def main() -> None:
    parser = argparse.ArgumentParser(description="Stepyard Scheduler Daemon")
    parser.add_argument("--project-dir", default=".", help="Project directory")
    parser.add_argument("--max-concurrent", type=int, default=MAX_CONCURRENT_FLOWS)
    parser.add_argument("--tick-interval", type=float, default=TICK_INTERVAL)
    args = parser.parse_args()

    project_dir = os.path.abspath(args.project_dir)
    stepyard_dir = os.path.join(project_dir, ".stepyard")

    log_store = LogStore(stepyard_dir)
    scheduler_log = str(log_store.scheduler_log_path())
    _configure_logging(log_path=scheduler_log)

    # Filter out APScheduler debug spam
    logging.getLogger("apscheduler").setLevel(logging.WARNING)

    logger.info("Starting Stepyard Scheduler Daemon  project_dir=%s", project_dir)

    storage = Storage(project_dir)
    process_manager = ProcessManager(logs_dir=os.path.join(stepyard_dir, "logs"))

    scheduler = SchedulerDaemon(
        storage=storage,
        log_store=log_store,
    )

    executor = ExecutorWorker(
        storage=storage,
        process_manager=process_manager,
        log_store=log_store,
        tick_interval=args.tick_interval,
        max_concurrent=args.max_concurrent,
    )

    pid_file = os.path.join(stepyard_dir, "scheduler.pid")

    # Enforce strict singleton
    if os.path.exists(pid_file):
        try:
            with open(pid_file) as fh:
                old_pid = int(fh.read().strip())

            if old_pid != os.getpid():
                os.kill(old_pid, 0)
                logger.error("Daemon is already running with PID %d. Exiting.", old_pid)
                sys.exit(1)
        except (ProcessLookupError, ValueError, OSError):
            pass  # Stale pid file

    with open(pid_file, "w") as fh:
        fh.write(str(os.getpid()))

    async def run_supervisor():
        await asyncio.gather(
            scheduler.run_forever(),
            executor.run_forever(),
        )

    try:
        asyncio.run(run_supervisor())
    finally:
        try:
            os.remove(pid_file)
        except OSError:
            pass


if __name__ == "__main__":
    main()

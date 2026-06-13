"""
Stepyard engine runner - subprocess entry point for a single flow execution.

This module is invoked as::

    python -m stepyard.engine.runner \\
        --run-id <run_id> \\
        --flow-file <path/to/flow.yaml> \\
        --project-dir <project_dir>

It is the child process spawned by ProcessManager.spawn_flow().
All output (stdout + stderr) is captured by the parent via log file redirect.

Exit codes
----------
0  - flow completed successfully
1  - flow failed (error written to storage before exit)
2  - unrecoverable startup error (bad args, missing file, etc.)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys


def _configure_logging() -> None:
    """Configure structured logging for the runner process."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
    )


def main() -> None:
    _configure_logging()
    logger = logging.getLogger("stepyard.engine.runner")

    parser = argparse.ArgumentParser(description="Stepyard flow executor (child process)")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--flow-file", required=True)
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--vars", required=False, default="{}")
    args = parser.parse_args()

    logger.info(
        "Runner started - run_id=%s  flow_file=%s  project_dir=%s",
        args.run_id,
        args.flow_file,
        args.project_dir,
    )

    try:
        import json

        from stepyard.core.flow import Flow
        from stepyard.engine.executor import Engine
        from stepyard.storage.facade import Storage

        storage = Storage(args.project_dir)
        flow = Flow.from_file(args.flow_file)
        vars_dict = json.loads(args.vars)
    except ImportError as exc:
        logger.critical("Import error: %s", exc)
        sys.exit(2)
    except Exception as exc:
        logger.critical("Startup error: %s", exc, exc_info=True)
        sys.exit(2)

    engine = Engine(storage)

    try:
        asyncio.run(
            engine.execute_run(
                args.run_id,
                flow,
                vars=vars_dict,
            )
        )
    except Exception as exc:
        logger.error("Engine error: %s", exc, exc_info=True)
        try:
            storage.update_run_status(args.run_id, "failed", error=str(exc))
        except Exception:  # noqa: BLE001 - best-effort status update; already exiting
            pass
        sys.exit(1)

    run = storage.get_run(args.run_id)
    status = run["status"] if run else "unknown"
    logger.info("Runner finished - status=%s", status)

    # Suspended statuses mean the flow is paused waiting for human interaction.
    # Exit 0 so the worker does not overwrite the run status to "failed".
    SUCCESSFUL_EXIT_STATUSES = {"completed", "waiting_for_approval", "waiting_for_input"}
    sys.exit(0 if status in SUCCESSFUL_EXIT_STATUSES else 1)


if __name__ == "__main__":
    main()

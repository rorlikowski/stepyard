"""
Stepyard CLI - ``logs`` command (extended).

Provides:
    stepyard logs <run_id>               - show logs for a specific run
    stepyard logs <flow_name>            - show logs for the latest run of a flow
    stepyard logs <run_id> --follow      - live tail of a run log
    stepyard logs --scheduler            - show scheduler daemon log
    stepyard logs --scheduler --follow   - live tail scheduler log
    stepyard logs --all --follow         - interleaved live tail of all active runs
    stepyard logs --search <query>       - search across all run logs
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stepyard.api.service import StepyardService

import click
from rich import box
from rich.panel import Panel
from rich.rule import Rule
from sqlalchemy import text

from stepyard.cli.app import cli
from stepyard.cli.completions import complete_runs_or_flows
from stepyard.cli.theme import C_ACCENT, C_ERROR, C_MUTED, C_PRIMARY, C_SUCCESS, C_WARN, C_WHITE
from stepyard.cli.ui import console, print_cli_hint, print_error


def _get_service() -> StepyardService:  # type: ignore[name-defined]
    from stepyard.api.service import StepyardService

    return StepyardService.from_cwd()


# ─────────────────────────────────────────────────────────────────────────────
#  logs
# ─────────────────────────────────────────────────────────────────────────────


@cli.command()
@click.argument("run_id_or_flow", required=False, shell_complete=complete_runs_or_flows)
@click.option("--follow", "-f", is_flag=True, help="Live-tail the log (Ctrl+C to stop)")
@click.option("--scheduler", is_flag=True, help="Show the scheduler daemon log")
@click.option("--all", "all_logs", is_flag=True, help="Tail all currently active run logs")
@click.option(
    "--limit",
    type=click.IntRange(min=1),
    default=None,
    help="Maximum active runs to follow with --all",
)
@click.option("--search", "-s", default=None, help="Search log lines matching this query")
@click.option(
    "--lines", "-n", type=int, default=None, help="Number of lines to show (default: all)"
)
def logs(
    run_id_or_flow: str | None,
    follow: bool,
    scheduler: bool,
    all_logs: bool,
    limit: int | None,
    search: str | None,
    lines: int | None,
) -> None:
    """View logs from flow runs or the scheduler daemon."""

    svc = _get_service()

    # ── Scheduler log ────────────────────────────────────────────────────────
    if scheduler:
        console.print()
        console.print(
            Panel(
                f"[bold {C_WHITE}]Scheduler Daemon Log[/bold {C_WHITE}]",
                title=f"[bold {C_PRIMARY}]▶ STEPYARD | Scheduler Logs[/bold {C_PRIMARY}]",
                border_style=C_PRIMARY,
                padding=(0, 2),
                box=box.ROUNDED,
            )
        )
        if follow:
            console.print(f"[{C_MUTED}]Live tail - Ctrl+C to stop[/{C_MUTED}]\n")
            try:
                for line in svc.follow_scheduler_logs():
                    _print_log_line(line)
            except KeyboardInterrupt:
                pass
        else:
            with console.pager(styles=True):
                for line in svc.get_scheduler_logs(lines):
                    _print_log_line(line)
        return

    # ── Search ────────────────────────────────────────────────────────────────
    if search:
        results = svc.search_logs(search, run_id=run_id_or_flow)
        if not results:
            console.print(f"[{C_MUTED}]No matches for '{search}'[/{C_MUTED}]")
            return
        console.print()
        console.print(
            Rule(
                f"[bold {C_PRIMARY}]Search results for '{search}'[/bold {C_PRIMARY}]",
                style=C_MUTED,
            )
        )
        with console.pager(styles=True):
            for r in results:
                console.print(
                    f"[{C_MUTED}]{r['run_id']}:{r['line_number']}[/{C_MUTED}]  {r['text']}"
                )
        return

    # ── All active runs (interleaved) ─────────────────────────────────────────
    if all_logs:
        _follow_all_runs(svc, limit=limit)
        return

    # ── Single run or flow ────────────────────────────────────────────────────
    if not run_id_or_flow:
        print_error("Specify a run_id, flow name, or use --scheduler / --all.")
        raise click.exceptions.Exit(1)

    # Try as run_id first, then as flow name
    run = svc.get_run(run_id_or_flow)
    if run:
        run_id = run_id_or_flow
    else:
        # Try to find the latest run for this flow
        with svc.storage.get_connection() as conn:
            row = (
                conn.execute(
                    text(
                        "SELECT id FROM runs WHERE flow_name = :flow_name "
                        "ORDER BY start_time DESC LIMIT 1"
                    ),
                    {"flow_name": run_id_or_flow},
                )
                .mappings()
                .fetchone()
            )
            if not row:
                from stepyard.core.flow import Flow, FlowResolver

                flow_file = FlowResolver(svc.storage.project_dir).find(run_id_or_flow)
                if flow_file:
                    try:
                        resolved_name = Flow.from_file(flow_file).model.name
                        row = (
                            conn.execute(
                                text(
                                    "SELECT id FROM runs WHERE flow_name = :flow_name "
                                    "ORDER BY start_time DESC LIMIT 1"
                                ),
                                {"flow_name": resolved_name},
                            )
                            .mappings()
                            .fetchone()
                        )
                    except Exception:
                        row = None

        if row:
            run_id = row["id"]
            run = svc.get_run(run_id)
            console.print(
                f"[{C_MUTED}]Showing latest run of '{run_id_or_flow}': "
                f"[bold {C_ACCENT}]{run_id}[/bold {C_ACCENT}][/{C_MUTED}]"
            )
        else:
            print_error(f"No run or flow found for '{run_id_or_flow}'.")
            raise click.exceptions.Exit(1)

    flow_name = run["flow_name"] if run else "Unknown"

    from stepyard.core.flow import Flow
    from stepyard.core.service import Scheduler

    scheduler = Scheduler(svc.storage)
    flow_file = scheduler.find_flow_file(flow_name)
    desc_str = ""
    if flow_file:
        try:
            flow_obj = Flow.from_file(flow_file)
            if flow_obj.model.description:
                desc_str = f"\n[{C_MUTED}]{flow_obj.model.description}[/{C_MUTED}]"
        except Exception:  # noqa: BLE001 - description is display-only; skip parse errors
            pass

    console.print()
    console.print(
        Panel(
            f"[bold {C_WHITE}]Flow[/bold {C_WHITE}] [bold {C_ACCENT}]{flow_name}[/bold {C_ACCENT}]  "
            f"[{C_MUTED}]run_id=[/{C_MUTED}][bold {C_WHITE}]{run_id}[/bold {C_WHITE}]{desc_str}",
            title=f"[bold {C_PRIMARY}]▶ STEPYARD | Run Logs[/bold {C_PRIMARY}]",
            border_style=C_PRIMARY,
            padding=(0, 2),
            box=box.ROUNDED,
        )
    )
    console.print()

    if follow:
        console.print(f"[{C_MUTED}]Live tail - Ctrl+C to stop[/{C_MUTED}]\n")
        try:
            for line in svc.follow_logs(run_id):
                _print_log_line(line)
        except KeyboardInterrupt:
            pass
    else:
        lines_out = svc.get_log_lines(run_id, lines)
        if not lines_out:
            console.print(f"[{C_MUTED}]No logs found for run '{run_id}'.[/{C_MUTED}]")
        else:
            with console.pager(styles=True):
                for line in lines_out:
                    _print_log_line(line)

    print_cli_hint(f"stepyard logs {run_id} --follow", "to live-tail this run")


# ─────────────────────────────────────────────────────────────────────────────
#  Internal helpers
# ─────────────────────────────────────────────────────────────────────────────


def _print_log_line(line: str) -> None:
    """Print a log line, coloring it based on level keywords."""
    lower = line.lower()
    if "error" in lower or "critical" in lower:
        style = f"bold {C_ERROR}"
    elif "warning" in lower or "warn" in lower:
        style = C_WARN
    elif "completed" in lower or "success" in lower:
        style = C_SUCCESS
    else:
        style = C_WHITE
    console.print(f"[{style}]{line}[/{style}]")


def _follow_all_runs(svc: StepyardService, limit: int | None = None) -> None:  # type: ignore[name-defined]
    """Interleaved live tail of all active run logs."""
    console.print()
    console.print(
        Panel(
            f"[bold {C_WHITE}]All active runs - interleaved live logs[/bold {C_WHITE}]\n"
            f"[{C_MUTED}]Ctrl+C to stop[/{C_MUTED}]",
            title=f"[bold {C_PRIMARY}]▶ All Logs[/bold {C_PRIMARY}]",
            border_style=C_PRIMARY,
            padding=(0, 2),
            box=box.ROUNDED,
        )
    )

    query = "SELECT id, flow_name FROM runs WHERE status IN ('running', 'queued') ORDER BY start_time DESC"
    params = {}
    if limit is not None:
        query += " LIMIT :limit"
        params["limit"] = limit

    with svc.storage.get_connection() as conn:
        active_runs = conn.execute(text(query), params).mappings().fetchall()

    if not active_runs:
        console.print(f"[{C_MUTED}]No active runs found.[/{C_MUTED}]")
        return

    stop_event = threading.Event()

    def tail_run(run_id: str, flow_name: str) -> None:
        prefix = f"[bold {C_ACCENT}][{flow_name}][/bold {C_ACCENT}]"
        try:
            for line in svc.follow_logs(run_id):
                if stop_event.is_set():
                    break
                console.print(f"{prefix} [{C_MUTED}]{run_id[:12]}[/{C_MUTED}] {line}")
        except Exception:  # noqa: BLE001 - log tail thread may see errors when run ends
            pass

    threads = []
    for row in active_runs:
        t = threading.Thread(
            target=tail_run,
            args=(row["id"], row["flow_name"]),
            daemon=True,
        )
        t.start()
        threads.append(t)

    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        stop_event.set()

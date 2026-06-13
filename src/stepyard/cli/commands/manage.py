"""
Stepyard CLI - Management subgroups.

Groups: ``project``, ``service``.
"""

from __future__ import annotations

import os
import shutil

import click
from rich import box
from rich.panel import Panel

from stepyard.cli.app import SubRichGroup, cli, get_storage
from stepyard.cli.theme import C_ACCENT, C_ERROR, C_MUTED, C_SUCCESS, C_WHITE
from stepyard.cli.ui import console, print_success, print_warning


@cli.command(name="clear")
@click.option("--force", "-f", is_flag=True, help="Skip confirmation prompt")
def clear(force: bool):
    """Clear all run history and execution logs."""
    if not force:
        if not click.confirm(
            "Are you sure you want to clear ALL run history and logs? This cannot be undone.",
            default=False,
        ):
            console.print("[dim]Operation cancelled.[/dim]")
            return

    storage = get_storage()

    # Delete all run and step-run records through the Storage facade (commits atomically).
    deleted = storage.clear_history()

    # Delete logs directory contents.
    logs_dir = os.path.join(storage.stepyard_dir, "logs")
    if os.path.exists(logs_dir):
        runs_logs_dir = os.path.join(logs_dir, "runs")
        if os.path.exists(runs_logs_dir):
            shutil.rmtree(runs_logs_dir, ignore_errors=True)

        # Truncate scheduler.log without closing the open file handle of the daemon.
        scheduler_log = os.path.join(logs_dir, "scheduler.log")
        if os.path.exists(scheduler_log):
            with open(scheduler_log, "w"):
                pass

    print_success(f"Cleared {deleted} run(s) and all associated logs.")


# ═════════════════════════════════════════════════════════════════════════════
#  service
# ═════════════════════════════════════════════════════════════════════════════


@click.group(name="service", cls=SubRichGroup)
def service_group():
    """Manage the background scheduler daemon (required for proper operation of cron triggers)."""


@service_group.command(name="start")
@click.option("--foreground", is_flag=True, help="Run in foreground instead of detaching")
def service_start(foreground: bool):
    """Start the scheduler daemon process."""
    from stepyard.api.service import StepyardService

    svc = StepyardService.from_cwd()
    status = svc.scheduler_status()

    if status.is_running:
        print_warning(f"Scheduler is already running (PID {status.pid}).")
        return

    if foreground:
        console.print()
        console.print(
            Panel(
                f"[bold {C_WHITE}]Stepyard Scheduler Service[/bold {C_WHITE}]\n"
                f"[{C_MUTED}]Logs → .stepyard/logs/scheduler.log[/{C_MUTED}]\n"
                f"[{C_MUTED}]Press Ctrl+C to stop.[/{C_MUTED}]",
                title=f"[bold {C_SUCCESS}]▶ Starting Service (Foreground)[/bold {C_SUCCESS}]",
                border_style=C_SUCCESS,
                padding=(0, 3),
                box=box.ROUNDED,
            )
        )
        console.print()
        try:
            svc.start_scheduler(foreground=True)
        except KeyboardInterrupt:
            console.print()
            print_warning("Service stopped by user.")
        return

    svc.start_scheduler(foreground=False)
    new_status = svc.scheduler_status()
    print_success(
        "Scheduler service started in the background.",
        subtitle=f"PID: {new_status.pid}  │  Logs: .stepyard/logs/scheduler.log",
    )
    console.print(
        f"  [dim]Tail logs:[/dim] [bold {C_ACCENT}]stepyard logs --scheduler --follow[/bold {C_ACCENT}]\n"
    )


@service_group.command(name="stop")
def service_stop():
    """Stop the background scheduler daemon."""
    from stepyard.api.service import StepyardService

    svc = StepyardService.from_cwd()
    if svc.stop_scheduler():
        print_success("Scheduler service stopped successfully.")
    else:
        print_warning("Scheduler service is not currently running.")


@service_group.command(name="restart")
@click.pass_context
def service_restart(ctx: click.Context):
    """Restart the background scheduler daemon to reload flows."""
    import time

    from stepyard.api.service import StepyardService

    svc = StepyardService.from_cwd()

    if svc.scheduler_status().is_running:
        svc.stop_scheduler()
        print_success("Scheduler service stopped.")
        time.sleep(1)

    ctx.invoke(service_start, foreground=False)


@service_group.command(name="status")
def service_status():
    """Check if the scheduler daemon is running."""
    import time

    from stepyard.api.service import StepyardService
    from stepyard.cli.ui import format_duration

    svc = StepyardService.from_cwd()
    status = svc.scheduler_status()

    if status.is_running:
        pid_file = svc._scheduler_pid_path()
        uptime_str = "Unknown"
        if os.path.exists(pid_file):
            uptime_seconds = time.time() - os.path.getmtime(pid_file)
            uptime_str = format_duration(uptime_seconds)

        logs = svc.get_scheduler_logs(last_n=3)
        logs_str = (
            "\n".join([f"[{C_MUTED}]  {line.strip()}[/{C_MUTED}]" for line in logs])
            if logs
            else f"[{C_MUTED}]  (No logs yet)[/{C_MUTED}]"
        )

        console.print(
            Panel(
                f"[bold {C_SUCCESS}]🟢 Service is Running[/bold {C_SUCCESS}]\n"
                f"[{C_MUTED}]PID: {status.pid}[/{C_MUTED}]\n"
                f"[{C_MUTED}]Uptime: {uptime_str}[/{C_MUTED}]\n"
                f"[{C_MUTED}]Background cron triggers are active.[/{C_MUTED}]\n"
                f"[{C_MUTED}]Logs: .stepyard/logs/scheduler.log[/{C_MUTED}]\n\n"
                f"[bold]Recent Logs:[/bold]\n{logs_str}",
                border_style=C_SUCCESS,
                padding=(1, 3),
                box=box.ROUNDED,
            )
        )
        console.print(
            f"  [dim]Tail logs:[/dim] [bold {C_ACCENT}]stepyard logs --scheduler --follow[/bold {C_ACCENT}]\n"
        )
    else:
        console.print(
            Panel(
                f"[bold {C_ERROR}]🔴 Service is Stopped[/bold {C_ERROR}]\n"
                f"[{C_MUTED}]Run: [bold]stepyard service start[/bold][/{C_MUTED}]",
                border_style=C_ERROR,
                padding=(1, 3),
                box=box.ROUNDED,
            )
        )


@service_group.command(name="logs")
@click.option("--follow", "-f", is_flag=True, help="Live-tail the log (Ctrl+C to stop)")
@click.option("--lines", "-n", default=100, show_default=True, help="Number of lines to show")
@click.pass_context
def service_logs(ctx: click.Context, follow: bool, lines: int):
    """View the scheduler daemon logs."""
    from stepyard.cli.commands.logs import logs

    ctx.invoke(
        logs,
        run_id_or_flow=None,
        follow=follow,
        scheduler=True,
        all_logs=False,
        search=None,
        lines=lines,
    )


cli.add_command(service_group)

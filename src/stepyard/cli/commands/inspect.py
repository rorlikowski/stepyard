"""
Stepyard CLI - ``status``, ``show``, and ``logs`` commands.

Read-only inspection commands for viewing flow execution history.
"""

from __future__ import annotations

from datetime import datetime

import click
from rich import box
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from sqlalchemy import text

from stepyard.cli.app import cli, get_storage
from stepyard.cli.completions import complete_flows, complete_runs
from stepyard.cli.theme import C_ACCENT, C_ERROR, C_MUTED, C_PRIMARY, C_WARN, C_WHITE
from stepyard.cli.ui import console, print_cli_hint, print_error, status_badge

# ─────────────────────────────────────────────────────────────────────────────
#  status
# ─────────────────────────────────────────────────────────────────────────────


@cli.command()
def status():
    """Show the overall status of all available workflows and their most recent run result."""
    import os

    from stepyard.api.service import StepyardService
    from stepyard.core.flow import Flow

    storage = get_storage()
    svc = StepyardService.from_cwd()
    scheduler_running = svc.scheduler_status().is_running

    flows_dir = "flows"
    flows_map = {}
    has_cron = False

    if os.path.exists(flows_dir):
        for f in os.listdir(flows_dir):
            if f.endswith(".yaml"):
                path = os.path.join(flows_dir, f)
                try:
                    flow = Flow.from_file(path)
                    flows_map[flow.model.name] = flow
                    if flow.model.trigger and flow.model.trigger.uses == "cron":
                        has_cron = True
                except Exception:
                    pass

    # Fetch last run for all flows
    with storage.get_connection() as conn:
        last_runs_raw = (
            conn.execute(
                text("""
            SELECT id, flow_name, MAX(start_time) as last_run, status
            FROM runs GROUP BY flow_name
        """)
            )
            .mappings()
            .fetchall()
        )

    last_runs = {r["flow_name"]: r for r in last_runs_raw}

    if not flows_map and not last_runs:
        console.print()
        console.print(
            Panel(
                f"[bold {C_MUTED}]No flow definitions or runs found.[/bold {C_MUTED}]\n\n"
                f"  Get started: [bold {C_ACCENT}]stepyard init[/bold {C_ACCENT}]",
                title=f"[bold {C_PRIMARY}]Flow Status[/bold {C_PRIMARY}]",
                border_style=C_MUTED,
                padding=(1, 3),
                box=box.ROUNDED,
            )
        )
        console.print()
        return

    if has_cron and not scheduler_running:
        console.print(
            Panel(
                f"The background scheduler daemon is currently [bold {C_ERROR}]stopped[/bold {C_ERROR}].\n"
                f"Cron triggers will [bold]not[/bold] execute.\n"
                f"Run [bold]stepyard service start[/bold] to enable background scheduling.",
                title=f"[bold {C_WARN}]Background Scheduler Stopped[/bold {C_WARN}]",
                border_style=C_WARN,
                padding=(0, 2),
                box=box.ROUNDED,
            )
        )
        console.print()

    table = Table(
        title="[bold]Stepyard · Flow Status[/bold]",
        title_style=f"bold {C_WHITE}",
        box=box.ROUNDED,
        border_style=C_MUTED,
        header_style=f"bold {C_PRIMARY}",
        padding=(0, 2),
        show_lines=False,
    )
    table.add_column("Flow", style=f"bold {C_ACCENT}", no_wrap=True)
    table.add_column("Description", style=C_MUTED)
    table.add_column("Last Run", style=C_MUTED)
    table.add_column("Run ID", style=C_MUTED)
    table.add_column("Status")

    all_flow_names = sorted(set(flows_map.keys()) | set(last_runs.keys()))

    for flow_name in all_flow_names:
        flow = flows_map.get(flow_name)
        run = last_runs.get(flow_name)

        desc = "-"
        is_cron = False
        if flow:
            desc = flow.model.description or "-"
            if flow.model.trigger and flow.model.trigger.uses == "cron":
                is_cron = True

        run_id_str = "-"
        formatted_dt = "-"

        if run:
            run_id_str = run["id"]
            try:
                dt = datetime.fromisoformat(run["last_run"])
                formatted_dt = dt.strftime("%Y-%m-%d  %H:%M:%S")
            except Exception:
                formatted_dt = run["last_run"]

        # Determine real status
        run_status = run["status"] if run else None

        if run_status in ["queued", "running", "running_teardown"]:
            final_status = status_badge(run_status)
        elif is_cron:
            if not scheduler_running:
                final_status = (
                    f"[bold {C_ERROR}]● inactive[/bold {C_ERROR}] [dim](scheduler off)[/dim]"
                )
            else:
                final_status = f"[{C_PRIMARY}]● scheduled[/{C_PRIMARY}] [dim](cron)[/dim]"
        elif run_status:
            final_status = status_badge(run_status)
        else:
            final_status = "[dim]● ready[/dim]"

        table.add_row(flow_name, desc, formatted_dt, run_id_str, final_status)

    console.print()
    console.print(table)
    console.print()
    print_cli_hint("stepyard show <run_id>", "to inspect details of a specific run")


# ─────────────────────────────────────────────────────────────────────────────
#  show
# ─────────────────────────────────────────────────────────────────────────────


@cli.command()
@click.argument("run_id", shell_complete=complete_runs)
def show(run_id: str):
    """Show detailed history, steps, and results of a single flow execution run."""
    storage = get_storage()
    run = storage.get_run(run_id)

    if not run:
        print_error(f"Run '{run_id}' not found.", hint=_recent_runs_hint(storage))
        return

    # Run details panel
    details = Text()
    details.append("Run ID    ", style=C_MUTED)
    details.append(f"{run['id']}\n", style=f"bold {C_ACCENT}")
    details.append("Flow      ", style=C_MUTED)
    details.append(f"{run['flow_name']}\n", style=f"bold {C_WHITE}")
    details.append("Status    ", style=C_MUTED)
    details.append_text(status_badge(run["status"]))
    details.append("\nTrigger   ", style=C_MUTED)
    details.append(f"{run['trigger_type']}\n", style=C_WHITE)
    details.append("Created   ", style=C_MUTED)
    details.append(f"{run['start_time']}\n", style=C_MUTED)

    if run["error"]:
        details.append("\nError     ", style=C_MUTED)
        details.append(f"{run['error']}", style=f"bold {C_ERROR}")

    console.print()
    console.print(
        Panel(
            details,
            title=f"[bold {C_PRIMARY}]Run Details[/bold {C_PRIMARY}]",
            border_style=C_PRIMARY,
            padding=(1, 3),
            box=box.ROUNDED,
        )
    )

    # Steps table
    step_runs = storage.get_step_runs(run_id)
    table = Table(
        title="[bold]Steps Executed[/bold]",
        title_style=f"bold {C_WHITE}",
        box=box.ROUNDED,
        border_style=C_MUTED,
        header_style=f"bold {C_PRIMARY}",
        padding=(0, 2),
    )
    table.add_column("Step", style=f"bold {C_WHITE}", no_wrap=True)
    table.add_column("Status")
    table.add_column("Attempt", style=C_MUTED, justify="center")
    table.add_column("Output / Error", style=C_MUTED, max_width=60)

    for sr in step_runs:
        val = sr["output"] if sr["output"] else sr["error"]
        table.add_row(
            sr["step_id"],
            status_badge(sr["status"]),
            str(sr["attempt"]),
            str(val)[:60] if val else "-",
        )

    console.print(table)
    console.print()
    print_cli_hint(f"stepyard logs {run_id}", "to view full execution logs for this run")


# ─────────────────────────────────────────────────────────────────────────────
#  inspect
# ─────────────────────────────────────────────────────────────────────────────


@cli.command()
@click.argument("flow_name", shell_complete=complete_flows)
def inspect(flow_name: str):
    """Inspect the YAML definition of a flow."""
    import os

    from rich.syntax import Syntax

    flow_path = os.path.join("flows", f"{flow_name}.yaml")
    if not os.path.exists(flow_path):
        print_error(f"Flow '{flow_name}' not found.", hint=f"Checked path: {flow_path}")
        return

    try:
        with open(flow_path, encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        print_error(f"Failed to read flow '{flow_name}': {e}")
        return

    console.print()
    console.print(
        Panel(
            Syntax(content, "yaml", theme="monokai", line_numbers=True, word_wrap=True),
            title=f"[bold {C_PRIMARY}]Flow Definition: {flow_name}[/bold {C_PRIMARY}]",
            border_style=C_PRIMARY,
            padding=(1, 2),
            box=box.ROUNDED,
        )
    )
    console.print()


# ─────────────────────────────────────────────────────────────────────────────
#  Private helpers
# ─────────────────────────────────────────────────────────────────────────────


def _recent_runs_hint(storage) -> str:
    """Build a hint string listing recent run IDs."""
    try:
        with storage.get_connection() as conn:
            rows = (
                conn.execute(
                    text("SELECT id, flow_name FROM runs ORDER BY start_time DESC LIMIT 5")
                )
                .mappings()
                .fetchall()
            )
        if rows:
            listing = ", ".join(f"{r['id']} ({r['flow_name']})" for r in rows)
            return f"Recent runs: {listing}"
    except Exception:
        pass
    return "Run 'stepyard status' to see available runs."

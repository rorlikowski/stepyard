"""
Stepyard CLI - ``run`` and ``replay`` commands.

Handles local flow execution with live step-by-step progress,
duration tracking, and a polished summary panel.
"""

from __future__ import annotations

import asyncio
import json
import os

import click
from rich import box
from rich.panel import Panel

from stepyard.cli.app import cli, get_storage
from stepyard.cli.completions import complete_flows, complete_runs
from stepyard.cli.run.inputs import (
    flow_needs_runtime_human_input as _flow_needs_runtime_human_input,  # noqa: F401 - re-exported for tests
)
from stepyard.cli.run.session import RunCommandContext, RunSession
from stepyard.cli.theme import C_ACCENT, C_MUTED, C_PRIMARY, C_WHITE
from stepyard.cli.ui import console, print_error, print_success
from stepyard.core.flow import Flow
from stepyard.core.service import Scheduler

# ─────────────────────────────────────────────────────────────────────────────
#  Helpers - used by run/replay commands and tested directly
# ─────────────────────────────────────────────────────────────────────────────


def _parse_run_vars(var: tuple[str, ...], env_file: str | None) -> dict:
    vars_dict = {}
    if env_file:
        try:
            with open(env_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        vars_dict[k.strip()] = v.strip().strip('"').strip("'")
        except Exception as e:
            print_error(f"Failed to load env-file '{env_file}': {e}")
            raise click.exceptions.Exit(1) from None

    for v in var:
        if "=" in v:
            k, val = v.split("=", 1)
            vars_dict[k] = val
        else:
            vars_dict[v] = True
    return vars_dict


def _load_flow_for_run(flow_name: str, storage) -> tuple[str, Flow]:
    scheduler = Scheduler(storage)
    flow_file = scheduler.find_flow_file(flow_name)

    if not flow_file:
        available = _list_available_flows(storage)
        hint = "Make sure your project is registered and the flow YAML exists in flows/."
        if available:
            hint += f"\n\nAvailable flows: {', '.join(available)}"
        print_error(f"Flow '{flow_name}' not found.", hint=hint)
        raise click.exceptions.Exit(1)

    try:
        return flow_file, Flow.from_file(flow_file)
    except Exception as e:
        print_error(f"Failed to parse flow spec: {e}")
        raise click.exceptions.Exit(1) from None


def _list_available_flows(storage) -> list[str]:
    """Scan the project flows/ directory for available flow files."""
    flows: list[str] = []
    flows_dir = os.path.join(storage.project_dir, "flows")
    if os.path.isdir(flows_dir):
        for fn in os.listdir(flows_dir):
            if fn.endswith((".yaml", ".yml")):
                flows.append(fn.rsplit(".", 1)[0])
    return sorted(set(flows))


def _iter_flow_steps_flat(steps, parent_id=None):
    """Yield (step_id, step) tuples for all steps including nested groups."""
    for step in steps:
        step_id = f"{parent_id}.{step.id}" if parent_id else step.id
        yield step_id, step
        if getattr(step, "steps", None):
            yield from _iter_flow_steps_flat(step.steps, step_id)


# ─────────────────────────────────────────────────────────────────────────────
#  run
# ─────────────────────────────────────────────────────────────────────────────


@cli.command()
@click.argument("flow_name", shell_complete=complete_flows)
@click.option("--var", multiple=True, help="Set variables (e.g., --var key=value)")
@click.option("--env-file", type=click.Path(exists=True), help="Load variables from a .env file")
@click.option("--verbose", "-v", is_flag=True, help="Print detailed step outputs at the end")
@click.option(
    "--no-logs",
    is_flag=True,
    help="Hide the live log panel during execution (use stepyard logs to inspect later)",
)
@click.option("--dry-run", is_flag=True, help="Preview the execution plan without running anything")
def run(
    flow_name: str,
    var: tuple[str, ...],
    env_file: str | None,
    verbose: bool,
    no_logs: bool,
    dry_run: bool,
) -> None:
    """Run a specified workflow locally, showing real-time progress and logs."""
    if dry_run:
        _print_dry_run(flow_name, var, env_file)
        return

    ctx = RunCommandContext.build(
        flow_name,
        var,
        env_file,
        verbose,
        show_live_logs=not no_logs,
        parse_run_vars=_parse_run_vars,
        load_flow_for_run=_load_flow_for_run,
        get_storage=get_storage,
    )
    asyncio.run(RunSession(ctx).run_and_report())


# ─────────────────────────────────────────────────────────────────────────────
#  replay
# ─────────────────────────────────────────────────────────────────────────────


@cli.command()
@click.argument("run_id", shell_complete=complete_runs)
@click.option("--from-step", "from_step", required=True, help="Step ID to resume execution from")
def replay(run_id: str, from_step: str):
    """Replay a previously failed or stopped execution, resuming from a specific step."""
    storage = get_storage()
    run_record = storage.get_run(run_id)

    if not run_record:
        print_error(f"Run '{run_id}' not found.")
        return

    scheduler = Scheduler(storage)
    flow_file = scheduler.find_flow_file(run_record["flow_name"])

    if not flow_file:
        print_error(f"Flow file '{run_record['flow_name']}' not found.")
        return

    flow = Flow.from_file(flow_file)
    import datetime
    import uuid

    new_run_id = (
        f"run-replay-{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}-{uuid.uuid4().hex[:6]}"
    )
    storage.create_run(new_run_id, flow.model.name, trigger_type="replay")

    step_runs = storage.get_step_runs(run_id)
    step_outputs: dict[str, object] = {}
    for sr in step_runs:
        if sr["status"] == "completed":
            try:
                step_outputs[sr["step_id"]] = json.loads(sr["output"])
            except Exception:  # noqa: BLE001 - output may be plain string
                step_outputs[sr["step_id"]] = sr["output"]

    console.print()
    console.print(
        Panel(
            f"[bold {C_WHITE}]{flow.model.name}[/bold {C_WHITE}]\n"
            f"[{C_MUTED}]Resuming from step:[/{C_MUTED}] [bold {C_ACCENT}]{from_step}[/bold {C_ACCENT}]\n"
            f"[{C_MUTED}]New run ID:[/{C_MUTED}]          [bold {C_ACCENT}]{new_run_id}[/bold {C_ACCENT}]",
            title=f"[bold {C_PRIMARY}]↺ Replaying Flow[/bold {C_PRIMARY}]",
            border_style=C_PRIMARY,
            padding=(0, 3),
            box=box.ROUNDED,
        )
    )
    console.print()

    from stepyard.core.service import Engine

    engine = Engine(storage)

    async def _run_replay():
        for step_id, out in step_outputs.items():
            if step_id == from_step:
                break
            storage.create_step_run(new_run_id, step_id, status="completed", inputs={})
            storage.update_step_run(new_run_id, step_id, status="completed", output=out)

        all_steps = flow.model.steps
        start_idx = 0
        for i, s in enumerate(all_steps):
            if s.id == from_step:
                start_idx = i
                break
        flow.model.steps = all_steps[start_idx:]

        await engine.execute_run(new_run_id, flow)
        console.print()
        print_success("Replay completed.", subtitle=f"New run ID: {new_run_id}")

    asyncio.run(_run_replay())


# ─────────────────────────────────────────────────────────────────────────────
#  Dry-run rendering
# ─────────────────────────────────────────────────────────────────────────────


def _print_dry_run(
    flow_name: str,
    var: tuple[str, ...],
    env_file: str | None,
) -> None:
    """Print an execution plan without running anything."""
    storage = get_storage()
    vars_dict = _parse_run_vars(var, env_file)
    flow_file, flow = _load_flow_for_run(flow_name, storage)

    from rich import box as rbox  # noqa: PLC0415
    from rich.table import Table  # noqa: PLC0415

    console.print()
    console.print(
        Panel(
            f"[bold {C_WHITE}]{flow.model.name}[/bold {C_WHITE}]\n"
            + (
                f"[{C_MUTED}]{flow.model.description}[/{C_MUTED}]" if flow.model.description else ""
            ),
            title=f"[bold {C_PRIMARY}]Dry-run plan[/bold {C_PRIMARY}]",
            border_style=C_PRIMARY,
            padding=(0, 3),
            box=rbox.ROUNDED,
        )
    )
    console.print()

    table = Table(box=rbox.SIMPLE, show_header=True, header_style=f"bold {C_WHITE}")
    table.add_column("#", style=C_MUTED, width=3)
    table.add_column("Step ID", style=f"bold {C_ACCENT}")
    table.add_column("Uses", style=C_WHITE)
    table.add_column("Conditions", style=C_MUTED)

    for idx, step in enumerate(_iter_flow_steps_flat(flow.model.steps), start=1):
        step_id, step_obj = step
        conditions = []
        if getattr(step_obj, "if_cond", None):
            conditions.append(f"if: {step_obj.if_cond}")
        if getattr(step_obj, "loop", None):
            conditions.append(f"loop: {step_obj.loop}")
        if getattr(step_obj, "while_cond", None):
            conditions.append(f"while: {step_obj.while_cond}")
        if getattr(step_obj, "approval", False):
            conditions.append("[yellow]⏸ approval[/yellow]")
        if getattr(step_obj, "timeout", None):
            conditions.append(f"timeout: {step_obj.timeout}")

        uses = getattr(step_obj, "uses", None) or "[dim]group[/dim]"
        table.add_row(str(idx), step_id, uses, "  ".join(conditions) or "-")

    console.print(table)

    if vars_dict:
        console.print(f"  [{C_MUTED}]Variables:[/{C_MUTED}]", end=" ")
        console.print(", ".join(f"{k}={v!r}" for k, v in vars_dict.items()))
    console.print()

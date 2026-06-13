"""
Stepyard CLI - ``approvals`` command.

Interactive commands that require user prompts via questionary.
"""

from __future__ import annotations

import click
import questionary
from rich import box
from rich.panel import Panel

from stepyard.cli.app import cli, get_storage
from stepyard.cli.theme import C_ACCENT, C_MUTED, C_SUCCESS, C_WARN, C_WHITE, PROMPT_STYLE
from stepyard.cli.ui import console, print_section, print_success, print_warning

# ─────────────────────────────────────────────────────────────────────────────
#  approvals
# ─────────────────────────────────────────────────────────────────────────────


@cli.command()
def approvals():
    """List and manage pending manual approvals for paused workflows."""
    storage = get_storage()
    while True:
        click.clear()
        print_section("Pending Approvals")

        # Use Storage.list_pending_approvals() - no raw SQL in CLI.
        # We need the step-level view so we join through get_step_runs.
        pending_runs = storage.list_pending_approvals()
        pending = []
        for run in pending_runs:
            for step in storage.get_step_runs(run["id"]):
                if step["status"] == "pending":
                    pending.append({**step, "flow_name": run["flow_name"]})

        if not pending:
            console.print()
            console.print(
                Panel(
                    f"[bold {C_SUCCESS}]✓  No pending approvals[/bold {C_SUCCESS}]\n"
                    f"[{C_MUTED}]All steps are either completed or not yet reached.[/{C_MUTED}]",
                    border_style=C_SUCCESS,
                    padding=(0, 3),
                    box=box.ROUNDED,
                )
            )
            break

        max_flow_name_len = max([len(p["flow_name"]) for p in pending] + [15])
        max_run_id_len = max([len(p["run_id"]) for p in pending] + [18])
        max_step_id_len = max([len(p["step_id"]) for p in pending] + [15])

        choices_data = []
        for p in pending:
            display_title = f" Flow: {p['flow_name']:<{max_flow_name_len}} │ Run: {p['run_id']:<{max_run_id_len}} │ Step: {p['step_id']:<{max_step_id_len}}"
            choices_data.append((display_title, p))

        max_choice_len = max([len(t) for t, _ in choices_data] + [50])

        choices = []
        for title, val in choices_data:
            choices.append(questionary.Choice(title, value=val))

        choices.append(questionary.Separator("─" * max_choice_len))
        choices.append(questionary.Choice("◀  Back", value="back"))

        selected = questionary.select(
            "Select an approval to process  [💡 CLI: stepyard approvals]:",
            choices=choices,
            style=PROMPT_STYLE,
        ).ask()

        if selected == "back" or selected is None:
            break

        import json

        inputs_str = "{}"
        try:
            if selected["inputs"]:
                inputs_dict = json.loads(selected["inputs"])
                inputs_str = json.dumps(inputs_dict, indent=2)
        except Exception:
            inputs_str = str(selected["inputs"])

        console.print(
            Panel(
                f"[bold {C_WHITE}]Flow Name:[/] {selected['flow_name']}\n"
                f"[bold {C_WHITE}]Run ID:[/] {selected['run_id']}\n"
                f"[bold {C_WHITE}]Step ID:[/] {selected['step_id']}\n"
                f"[bold {C_WHITE}]Created At:[/] {selected.get('start_time', 'Unknown')}\n\n"
                f"[bold {C_ACCENT}]Inputs:[/\n{inputs_str}",
                title=f"[{C_WARN}]Approval Required[/{C_WARN}]",
                border_style=C_WARN,
                padding=(1, 2),
                box=box.ROUNDED,
            )
        )

        action = questionary.select(
            f"Action for Step '{selected['step_id']}' in Run '{selected['run_id']}':",
            choices=[
                questionary.Choice("✓  Approve", value="approve"),
                questionary.Choice("✗  Reject", value="reject"),
                questionary.Choice("◀  Cancel", value="cancel"),
            ],
            style=PROMPT_STYLE,
        ).ask()

        if action == "approve":
            storage.update_step_run(
                selected["run_id"],
                selected["step_id"],
                status="completed",
                output="Approved by operator",
            )
            storage.update_run_status(selected["run_id"], "queued")
            print_success(f"Step '{selected['step_id']}' approved. Run re-queued.")
            questionary.press_any_key_to_continue().ask()
        elif action == "reject":
            storage.update_step_run(
                selected["run_id"],
                selected["step_id"],
                status="failed",
                error="Rejected by operator",
            )
            storage.update_run_status(
                selected["run_id"], "failed", error="Step rejected by operator"
            )
            print_warning(f"Step '{selected['step_id']}' rejected. Run marked as failed.")
            questionary.press_any_key_to_continue().ask()

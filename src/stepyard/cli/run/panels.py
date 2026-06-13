"""
Stepyard CLI - waiting/approval panel renderers for the run command.
"""

from __future__ import annotations

from rich import box
from rich.panel import Panel

from stepyard.cli.theme import C_MUTED, C_WARN, C_WHITE
from stepyard.cli.ui import console


def build_waiting_panel(
    flow_name: str,
    run_id: str,
    pending_step_id: str,
    inputs_dict: dict,
    waiting_for_input: bool,
) -> Panel:
    """Return a Rich Panel describing a paused flow awaiting input or approval."""
    from rich.console import Group
    from rich.table import Table

    details = Table.grid(padding=(0, 1))
    details.add_column(style=f"bold {C_WHITE}", no_wrap=True)
    details.add_column(style=C_MUTED)

    prompt = str(inputs_dict.get("prompt") or f"Input for {pending_step_id}")
    default = str(inputs_dict.get("default") or "")
    required = bool(inputs_dict.get("required", True))
    secret = bool(inputs_dict.get("secret", False))
    choices = inputs_dict.get("choices") or []

    details.add_row("Prompt", prompt)
    if default:
        details.add_row("Default", default)
    details.add_row("Required", "yes" if required else "no")
    details.add_row("Secret", "yes" if secret else "no")
    if choices:
        details.add_row("Choices", ", ".join(str(c) for c in choices))

    action_hint = (
        "Type a value and press Enter."
        if waiting_for_input
        else "Use the interactive approval prompt below."
    )
    title = (
        f"[{C_WARN}]⏸  Waiting for input - Step '{pending_step_id}'[/{C_WARN}]"
        if waiting_for_input
        else f"[{C_WARN}]⏸  Flow paused - Step '{pending_step_id}' requires manual approval[/{C_WARN}]"
    )
    content = Group(
        f"[bold {C_WHITE}]Flow Name:[/] {flow_name}",
        f"[bold {C_WHITE}]Run ID:[/] {run_id}",
        f"[bold {C_WHITE}]Step ID:[/] {pending_step_id}",
        "",
        details,
        "",
        f"[{C_MUTED}]{action_hint}[/{C_MUTED}]",
    )
    return Panel(content, title=title, border_style=C_WARN, padding=(1, 2), box=box.ROUNDED)


def redraw_screen() -> None:
    """Clear the terminal and move cursor to the top-left (no-op when not a TTY)."""
    if not console.is_terminal:
        return
    console.file.write("\x1b[2J\x1b[H")
    console.file.flush()

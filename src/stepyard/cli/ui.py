"""
Stepyard CLI - UI rendering helpers.

Provides the shared Rich console instance and every reusable
output helper used by CLI commands.
"""

from __future__ import annotations

import json as _json

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text
from rich.traceback import install

from stepyard.cli.theme import (
    C_ACCENT,
    C_ERROR,
    C_HINT,
    C_MUTED,
    C_PRIMARY,
    C_SUCCESS,
    C_WARN,
    C_WHITE,
    LOGO,
    VERSION,
)

# ─── Rich traceback ──────────────────────────────────────────────────────────
install(show_locals=False)

# ─── Shared console instance ─────────────────────────────────────────────────
console = Console()


# ─────────────────────────────────────────────────────────────────────────────
#  Formatting utilities
# ─────────────────────────────────────────────────────────────────────────────


def format_duration(seconds: float) -> str:
    """Return a human-friendly duration string.

    Examples:
        0.3   → "0.3s"
        62.1  → "1m 2s"
        3661  → "1h 1m 1s"
    """
    if seconds < 0:
        return "-"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m {secs}s"


# ─────────────────────────────────────────────────────────────────────────────
#  Banners & panels
# ─────────────────────────────────────────────────────────────────────────────


def print_banner() -> None:
    """Display the Stepyard logo banner."""
    logo_text = Text(LOGO, style=f"bold {C_PRIMARY}", justify="center")
    tagline = Text(
        "  Effortless automation launcher · Python-powered plugins",
        style=f"italic {C_MUTED}",
        justify="center",
    )
    version_text = Text(f"  v{VERSION}", style=f"bold {C_ACCENT}", justify="center")
    console.print()
    console.print(logo_text)
    console.print(tagline)
    console.print(version_text)
    console.print()


def print_error(message: str, hint: str = "") -> None:
    """Print a styled error panel."""
    content = Text(message, style=f"bold {C_ERROR}")
    if hint:
        content.append(f"\n\n{hint}", style=f"{C_MUTED}")
    console.print(
        Panel(
            content,
            title=f"[{C_ERROR}]✗ Error[/{C_ERROR}]",
            border_style=C_ERROR,
            padding=(0, 2),
            box=box.ROUNDED,
        )
    )


def print_success(message: str, subtitle: str = "") -> None:
    """Print a styled success panel."""
    content = Text(f"✓ {message}", style=f"bold {C_SUCCESS}")
    if subtitle:
        content.append(f"\n{subtitle}", style=C_MUTED)
    console.print(Panel(content, border_style=C_SUCCESS, padding=(0, 2), box=box.ROUNDED))


def print_warning(message: str) -> None:
    """Print a styled warning."""
    console.print(f"[{C_WARN}]⚠  {message}[/{C_WARN}]")


def print_section(title: str) -> None:
    """Print a section separator."""
    console.print()
    console.print(Rule(f"[bold {C_PRIMARY}]{title}[/bold {C_PRIMARY}]", style=C_MUTED))
    console.print()


# ─────────────────────────────────────────────────────────────────────────────
#  Step / status rendering
# ─────────────────────────────────────────────────────────────────────────────


def status_badge(status: str) -> Text:
    """Return a colored status badge text."""
    badges = {
        "completed": (C_SUCCESS, "● completed"),
        "failed": (C_ERROR, "● failed"),
        "waiting_for_approval": (C_WARN, "● waiting"),
        "waiting_for_input": (C_WARN, "● input"),
        "running": (C_PRIMARY, "● running"),
        "queued": (C_MUTED, "● queued"),
    }
    color, label = badges.get(status, (C_MUTED, f"● {status}"))
    return Text(label, style=f"bold {color}")


def format_step_line(
    step_id: str,
    status: str,
    error: str | None = None,
    duration: float | None = None,
    step_num: int | None = None,
    total_steps: int | None = None,
) -> Text:
    """Build a single step-result line (eliminates old DRY violation).

    Used by both the live-loop and the final-drain in the ``run`` command.
    """
    icon_map = {
        "completed": ("✓ ", f"bold {C_SUCCESS}"),
        "skipped": ("○ ", f"bold {C_WARN}"),
        "failed": ("✗ ", f"bold {C_ERROR}"),
    }
    icon_char, icon_style = icon_map.get(status, ("· ", C_MUTED))

    line = Text()
    if step_num is not None and total_steps is not None:
        line.append(f"[{step_num}/{total_steps}] ", style=C_MUTED)
    else:
        line.append("  ")

    line.append(icon_char, style=icon_style)
    line.append(f"{step_id:<20}", style=f"bold {C_WHITE}")
    line.append(status, style=C_MUTED)

    if duration is not None:
        line.append(f"     {format_duration(duration)}", style=C_MUTED)

    if status == "failed" and error:
        line.append(f"  {error}", style=C_ERROR)

    return line


def print_step_output(step_run: dict) -> None:
    """Print step output nicely formatted."""
    from rich.json import JSON
    from rich.padding import Padding
    from rich.panel import Panel
    from rich.syntax import Syntax
    from rich.tree import Tree

    raw = step_run.get("output")
    if not raw:
        return

    try:
        data = _json.loads(raw)
    except (_json.JSONDecodeError, TypeError):
        data = raw

    if isinstance(data, dict):
        # Filter out empty elements for cleaner display
        data = {k: v for k, v in data.items() if v not in (None, "", [], {})}
        if not data:
            return

        stdout = data.pop("stdout", None)
        stderr = data.pop("stderr", None)
        code = data.pop("code", None)

        if stdout:
            console.print(
                Padding(
                    Panel(
                        Syntax(
                            str(stdout).strip(),
                            "text",
                            theme="monokai",
                            word_wrap=True,
                            background_color="default",
                        ),
                        title=f"[bold {C_PRIMARY}]stdout[/]",
                        border_style=C_PRIMARY,
                        padding=(0, 2),
                        box=box.ROUNDED,
                    ),
                    (0, 0, 0, 4),
                )
            )

        if stderr:
            console.print(
                Padding(
                    Panel(
                        Syntax(
                            str(stderr).strip(),
                            "text",
                            theme="monokai",
                            word_wrap=True,
                            background_color="default",
                        ),
                        title=f"[bold {C_ERROR}]stderr[/]",
                        border_style=C_ERROR,
                        padding=(0, 2),
                        box=box.ROUNDED,
                    ),
                    (0, 0, 0, 4),
                )
            )

        if code is not None:
            color = C_SUCCESS if code == 0 else C_ERROR
            console.print(
                Padding(f"  [bold {C_MUTED}]Exit Code:[/] [bold {color}]{code}[/]", (0, 0, 1, 4))
            )

        if data:
            tree = Tree(f"[{C_MUTED}]Other Outputs[/{C_MUTED}]")
            for key, val in data.items():
                if isinstance(val, (dict, list)):
                    val_json = _json.dumps(val, indent=2)
                    tree.add(f"[{C_WHITE}]{key}[/{C_WHITE}]:").add(JSON(val_json))
                else:
                    val_str = str(val)
                    if "\n" in val_str:
                        tree.add(f"[{C_WHITE}]{key}[/{C_WHITE}]:").add(
                            Syntax(val_str, "text", theme="monokai", word_wrap=True)
                        )
                    else:
                        tree.add(f"[{C_WHITE}]{key}[/{C_WHITE}]: {val_str}")
            console.print(Padding(tree, (0, 0, 0, 4)))

    elif isinstance(data, list):
        if not data:
            return
        for idx, item in enumerate(data):
            console.print(Padding(f"[{C_ACCENT}]● Iteration {idx + 1}[/]", (0, 0, 0, 4)))
            print_step_output({"output": item})

    else:
        val_str = str(data).strip()
        if val_str:
            if "\n" in val_str:
                console.print(
                    Padding(
                        Syntax(
                            val_str,
                            "text",
                            theme="monokai",
                            word_wrap=True,
                            background_color="default",
                        ),
                        (0, 0, 1, 4),
                    )
                )
            else:
                console.print(Padding(f"[{C_WHITE}]{val_str}[/{C_WHITE}]", (0, 0, 1, 4)))


def print_cli_hint(command: str, description: str | None = None) -> None:
    """Print a styled CLI equivalent hint."""
    if command.startswith("stepyard "):
        command = command[8:]

    hint_text = Text()
    hint_text.append("💡 Hint: ", style=f"bold {C_HINT}")
    hint_text.append(command, style=f"bold {C_ACCENT}")
    if description:
        hint_text.append(f" - {description}", style=C_MUTED)
    console.print(hint_text)
    console.print()

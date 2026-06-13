"""
Stepyard CLI - ``doctor`` command.

Verifies environment health: database, virtualenv, registered projects,
and plugin discovery.
"""

from __future__ import annotations

import os

from rich.markup import escape
from rich.text import Text
from sqlalchemy import text

from stepyard.cli.app import cli, get_storage
from stepyard.cli.theme import C_ERROR, C_MUTED, C_SUCCESS, C_WARN, C_WHITE
from stepyard.cli.ui import console, print_section, print_success, print_warning
from stepyard.plugin import PluginHost, PluginManager


@cli.command()
def doctor():
    """Verify environment health, database connections, and plugin virtualenvs."""
    print_section("System Diagnostics")
    storage = get_storage()

    checks: list[tuple[bool | None, str, str]] = []

    try:
        with storage.get_connection() as conn:
            conn.execute(text("SELECT 1")).fetchone()
        checks.append((True, "Database", "SQLite WAL connection OK"))
    except Exception as e:
        checks.append((False, "Database", f"Connection failed: {e}"))

    pm = PluginManager(storage.project_dir)
    if os.path.exists(pm.venv_python):
        checks.append((True, "Environment", f"Isolated VirtualEnv found at {pm.env_dir}"))
    else:
        checks.append(
            (None, "Environment", "VirtualEnv missing (run any plugin command to initialize)")
        )

    with storage.get_connection() as conn:
        projects = conn.execute(text("SELECT * FROM projects")).fetchall()
    checks.append((True, "Projects", f"{len(projects)} registered project(s) found"))

    plugin_errors: list[str] = []
    try:
        report = PluginHost(storage.project_dir).discover()
        node_count = len(report.registry.nodes)
        trigger_count = len(report.registry.triggers)
        if report.has_errors:
            checks.append(
                (
                    False,
                    "Plugins",
                    f"{node_count} nodes, {trigger_count} triggers loaded; "
                    f"{len(report.errors)} plugin(s) failed",
                )
            )
            for err in report.errors:
                plugin_errors.append(
                    f"  [bold {C_ERROR}]✗[/bold {C_ERROR}] [{C_WARN}]{err.name}[/{C_WARN}] "
                    f"([{C_MUTED}]{err.value}[/{C_MUTED}])\n"
                    f"    [{C_ERROR}]{escape(err.error)}[/{C_ERROR}]"
                )
        else:
            checks.append((True, "Plugins", f"{node_count} nodes, {trigger_count} triggers loaded"))
    except Exception as exc:
        checks.append((False, "Plugins", f"Discovery failed: {exc}"))

    for ok, label, msg in checks:
        if ok is True:
            icon = Text("✓ ", style=f"bold {C_SUCCESS}")
        elif ok is False:
            icon = Text("✗ ", style=f"bold {C_ERROR}")
        else:
            icon = Text("⚠ ", style=f"bold {C_WARN}")

        line = Text()
        line.append_text(icon)
        line.append(f"{label:<14}", style=f"bold {C_WHITE}")
        line.append(msg, style=C_MUTED)
        console.print("  ", line)

    if plugin_errors:
        console.print()
        console.print(f"  [{C_WARN}]Failed plugin details:[/{C_WARN}]")
        for err_line in plugin_errors:
            console.print(err_line)

    all_ok = all(ok is not False for ok, _, _ in checks)
    console.print()
    if all_ok:
        print_success("All diagnostics passed.")
    else:
        print_warning("Some checks failed - see details above.")

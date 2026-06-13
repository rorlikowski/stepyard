"""
Stepyard CLI - ``plugin`` command group.

Manages installed plugin packages in the project's isolated virtualenv.
"""

from __future__ import annotations

import os

import click
from rich.progress import Progress, SpinnerColumn, TextColumn

from stepyard.cli.app import SubRichGroup, cli, get_storage
from stepyard.cli.completions import complete_installed_plugins
from stepyard.cli.theme import C_ACCENT, C_PRIMARY, C_WHITE
from stepyard.cli.ui import console, print_error, print_success, print_warning
from stepyard.plugin import PluginManager


@click.group(name="plugin", cls=SubRichGroup)
def plugin_group():
    """Manage installed plugin packages, versions, and sync status."""


def _run_plugin_operation(
    *,
    task_name: str,
    progress_text: str,
    operation,
    error_prefix: str,
    error_hint: str | None = None,
) -> None:
    with Progress(
        SpinnerColumn(spinner_name="dots", style=f"bold {C_PRIMARY}"),
        TextColumn(progress_text),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task(task_name, total=None)
        try:
            operation()
        except Exception as e:
            console.print()
            print_error(f"{error_prefix}: {e}", hint=error_hint)
            raise click.exceptions.Exit(1) from None


@plugin_group.command(name="add")
@click.argument("package")
def plugin_add(package: str):
    """Install a plugin package from PyPI, Git, or a local directory.

    \b
    Examples:
      stepyard plugin add stepyard-plugin-s3                 (from PyPI)
      stepyard plugin add git+https://github.com/org/plugin    (from Git)
      stepyard plugin add ./plugins/my-plugin               (from local folder)
    """
    storage = get_storage()
    pm = PluginManager(storage.project_dir)

    _run_plugin_operation(
        task_name="install",
        progress_text=(
            f"[bold {C_WHITE}]Installing[/bold {C_WHITE}] "
            f"[bold {C_ACCENT}]{package}[/bold {C_ACCENT}]..."
        ),
        operation=lambda: pm.add_plugin(package),
        error_prefix="Installation failed",
        error_hint="Check that the package name is correct and PyPI is reachable.",
    )

    print_success(f"Plugin package installed: {package}")


@plugin_group.command(name="remove")
@click.argument("package", shell_complete=complete_installed_plugins)
def plugin_remove(package: str):
    """Uninstall a plugin package from the project environment.

    \b
    Examples:
      stepyard plugin remove stepyard-plugin-sample
    """
    storage = get_storage()
    pm = PluginManager(storage.project_dir)

    _run_plugin_operation(
        task_name="uninstall",
        progress_text=(
            f"[bold {C_WHITE}]Uninstalling[/bold {C_WHITE}] "
            f"[bold {C_ACCENT}]{package}[/bold {C_ACCENT}]..."
        ),
        operation=lambda: pm.remove_plugin(package),
        error_prefix="Uninstallation failed",
    )

    print_success(f"Plugin package uninstalled: {package}")


@plugin_group.command(name="list")
@click.option(
    "--plain", is_flag=True, help="Print a static catalog instead of the interactive browser."
)
def list_plugins(plain: bool):
    """List all installed plugin packages and their versions."""
    from stepyard.cli.commands.tools import (
        _browse_plugins,
        _discover_plugin_infos,
        _print_plugin_catalog,
    )

    storage = get_storage()
    pm = PluginManager(storage.project_dir)
    sp = pm.get_site_packages()

    if not os.path.exists(sp):
        print_warning("Plugin environment not initialized yet.")
        return

    plugins_found = _discover_plugin_infos(pm)
    if not plugins_found:
        print_warning("No plugin packages installed.")
        return

    if plain or not console.is_terminal:
        _print_plugin_catalog(plugins_found)
        return

    _browse_plugins(plugins_found)


@plugin_group.command(name="sync")
def plugin_sync():
    """Restore and synchronize the plugin environment from stepyard.lock."""
    storage = get_storage()
    pm = PluginManager(storage.project_dir)

    if not os.path.exists(pm.lockfile_path):
        print_warning("No stepyard.lock file found in project directory.")
        return

    try:
        with open(pm.lockfile_path, encoding="utf-8") as f:
            specs = [line.strip() for line in f if line.strip()]
    except Exception:  # noqa: BLE001 - treat any read failure as empty
        specs = []

    if not specs:
        print_warning("stepyard.lock is empty.")
        return

    console.print(
        f"[bold {C_WHITE}]Found {len(specs)} plugin package(s) in stepyard.lock:[/bold {C_WHITE}]"
    )
    for spec in specs:
        console.print(f"  • [bold {C_ACCENT}]{spec}[/bold {C_ACCENT}]")
    console.print()

    _run_plugin_operation(
        task_name="sync",
        progress_text=f"[bold {C_WHITE}]Synchronizing plugin environment...[/bold {C_WHITE}]",
        operation=pm.sync_plugins,
        error_prefix="Synchronization failed",
    )

    print_success("Plugin environment synchronized successfully.")


@plugin_group.command(name="init")
@click.argument("plugin_name", metavar="<plugin_name>")
@click.argument("dest_dir", required=False, metavar="[dest_dir]")
def plugin_init(plugin_name: str, dest_dir: str | None):
    """Initialize a new Stepyard plugin project from a template.

    Generates a complete boilerplate structure for a new plugin, including the
    package directory, pyproject.toml configuration, entry points, and a
    sample node implementation ready for development.

    \b
    Arguments:
      <plugin_name>  The name of your new plugin (e.g., stepyard-plugin-aws)
      \\[dest_dir]    Optional path where the plugin should be created.
                     If omitted, creates a directory named after the plugin.

    \b
    Examples:
      stepyard plugin init my-awesome-plugin
      stepyard plugin init my-plugin ./custom/path
    """
    if not dest_dir:
        dest_dir = f"./{plugin_name}"

    storage = get_storage()
    pm = PluginManager(storage.project_dir)

    try:
        pm.init_plugin_template(plugin_name, dest_dir)
    except Exception as e:
        console.print()
        print_error(f"Failed to create plugin template: {e}")
        raise click.exceptions.Exit(1) from None

    console.print()
    print_success(
        f"Plugin boilerplate created at: {os.path.abspath(dest_dir)}",
        subtitle=f"You can now install it: stepyard plugin add {dest_dir}",
    )


cli.add_command(plugin_group)

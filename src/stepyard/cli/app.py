"""
Stepyard CLI - Application entry point.

Defines the top-level Click group with a custom Rich help formatter
and provides project-root / storage helpers used by every command.
"""

from __future__ import annotations

import os

import click
from rich import box
from rich.table import Table

from stepyard.cli.theme import C_ACCENT, C_MUTED, C_PRIMARY, C_WHITE, VERSION
from stepyard.cli.ui import console, print_banner
from stepyard.storage.facade import Storage

# ─────────────────────────────────────────────────────────────────────────────
#  Project helpers
# ─────────────────────────────────────────────────────────────────────────────


def get_project_root() -> str:
    """Find the nearest project directory containing ``.stepyard/``, or cwd."""
    curr = os.getcwd()
    while True:
        if os.path.isdir(os.path.join(curr, ".stepyard")):
            return curr
        parent = os.path.dirname(curr)
        if parent == curr:
            break
        curr = parent
    return os.getcwd()


def get_storage() -> Storage:
    """Return a :class:`Storage` instance bound to the current project root."""
    return Storage(get_project_root())


def get_service_pid_file() -> str:
    path = os.path.join(get_project_root(), ".stepyard")
    os.makedirs(path, exist_ok=True)
    return os.path.join(path, "scheduler.pid")


def is_service_running() -> bool:
    pid_file = get_service_pid_file()
    if not os.path.exists(pid_file):
        return False
    try:
        with open(pid_file) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
#  Custom Rich Click group for beautiful --help
# ─────────────────────────────────────────────────────────────────────────────


def _options_table(params: list, ctx) -> Table:
    """Build a Rich table listing Click params as Option / Description rows."""
    table = Table(
        show_header=True,
        header_style=f"bold {C_PRIMARY}",
        box=box.ROUNDED,
        border_style=C_MUTED,
        padding=(0, 2),
        title="[bold]Options[/bold]",
        title_style=f"bold {C_WHITE}",
    )
    table.add_column("Option", style=f"bold {C_ACCENT}", no_wrap=True)
    table.add_column("Description", style=C_WHITE)
    for param in params:
        opts = ", ".join(param.opts)
        if getattr(param, "secondary_opts", None):
            opts += " / " + ", ".join(param.secondary_opts)
        help_record = param.get_help_record(ctx)
        table.add_row(f"  {opts}", help_record[-1] if help_record else "")
    return table


def _commands_table(commands: dict, title: str = "Commands") -> Table:
    """Build a Rich table listing Click sub-commands as Command / Description rows."""
    table = Table(
        show_header=True,
        header_style=f"bold {C_PRIMARY}",
        box=box.ROUNDED,
        border_style=C_MUTED,
        padding=(0, 2),
        title=f"[bold]{title}[/bold]",
        title_style=f"bold {C_WHITE}",
    )
    table.add_column("Command", style=f"bold {C_ACCENT}", no_wrap=True)
    table.add_column("Description", style=C_WHITE)
    for cmd_name, cmd in commands.items():
        desc = cmd.short_help or (cmd.help.split("\n")[0] if cmd.help else "")
        table.add_row(f"  {cmd_name}", desc)
    return table


class RichCommand(click.Command):
    def format_help(self, ctx, formatter):
        console.print()
        console.print(
            f"[{C_PRIMARY}]Usage:[/] [bold {C_WHITE}]{ctx.command_path}[/] [{C_MUTED}][OPTIONS][/{C_MUTED}]"
        )
        console.print()
        if self.help:
            console.print(f"  {self.help}")
            console.print()
        params = [p for p in self.get_params(ctx) if not getattr(p, "hidden", False)]
        if params:
            console.print(_options_table(params, ctx))
            console.print()


class SubRichGroup(click.Group):
    command_class = RichCommand

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.group_class = SubRichGroup

    def format_help(self, ctx, formatter):
        console.print()
        console.print(
            f"[{C_PRIMARY}]Usage:[/] [bold {C_WHITE}]{ctx.command_path}[/] [{C_MUTED}][OPTIONS] COMMAND [ARGS]...[/{C_MUTED}]"
        )
        console.print()
        if self.help:
            console.print(f"  {self.help}")
            console.print()
        params = [p for p in self.get_params(ctx) if not getattr(p, "hidden", False)]
        if params:
            console.print(_options_table(params, ctx))
            console.print()
        if self.commands:
            console.print(_commands_table(self.commands))
            console.print()


class RichGroup(SubRichGroup):
    """Click group with a premium Rich-based help screen."""

    def format_help(self, ctx, formatter):  # noqa: ARG002 - formatter unused intentionally
        print_banner()

        table = _commands_table({}, title="Available Commands")
        command_groups = {
            "🚀 Core": ["run", "status", "show", "inspect", "logs", "replay"],
            "📦 Project": ["init", "validate", "schema"],
            "🎮 Interactive": ["approvals"],
            "⚙️  Management": ["service", "clear"],
            "🛠️  Utilities": ["tools", "plugin", "doctor"],
        }

        rendered: set[str] = set()
        for group_name, commands in command_groups.items():
            table.add_section()
            table.add_row(f"[dim]{group_name}[/dim]", "")
            for cmd_name in commands:
                cmd = self.commands.get(cmd_name)
                if cmd:
                    desc = cmd.short_help or (cmd.help.split("\n")[0] if cmd.help else "")
                    table.add_row(f"  {cmd_name}", desc)
                    rendered.add(cmd_name)

        # Safety net: never silently hide a registered command (e.g. one added
        # by a plugin or a newly-introduced built-in) just because it is not in
        # the curated groups above.
        extra = sorted(set(self.commands) - rendered)
        if extra:
            table.add_section()
            table.add_row("[dim]🔌 Other[/dim]", "")
            for cmd_name in extra:
                cmd = self.commands[cmd_name]
                desc = cmd.short_help or (cmd.help.split("\n")[0] if cmd.help else "")
                table.add_row(f"  {cmd_name}", desc)

        console.print(table)
        console.print()
        console.print(
            f"  [dim]Run[/dim] [bold {C_ACCENT}]stepyard COMMAND --help[/bold {C_ACCENT}] "
            f"[dim]for detailed usage.[/dim]"
        )
        console.print()


# ─────────────────────────────────────────────────────────────────────────────
#  Top-level CLI group
# ─────────────────────────────────────────────────────────────────────────────


@click.group(cls=RichGroup, invoke_without_command=True)
@click.version_option(VERSION, "--version", "-V", message=f"stepyard v{VERSION}")
@click.pass_context
def cli(ctx):
    """Stepyard - The effortless, beautifully designed automation launcher."""

    if ctx.invoked_subcommand is None:
        from stepyard.cli.repl import start_repl

        start_repl(ctx)


# ─────────────────────────────────────────────────────────────────────────────
#  Register all command modules
# ─────────────────────────────────────────────────────────────────────────────


def _register_commands() -> None:
    """Import command modules so their decorators register with ``cli``."""
    import importlib.metadata

    try:
        import sys

        from stepyard.plugin import PluginManager

        pm = PluginManager(get_project_root())
        sp = pm.get_site_packages()
        if os.path.exists(sp) and sp not in sys.path:
            sys.path.append(sp)
    except Exception:
        sp = None

    from stepyard.cli.commands import (  # noqa: F401
        doctor,
        dx,
        inspect,
        interactive,
        logs,
        manage,
        plugin,
        run,
        tools,
    )

    if sp and os.path.exists(sp):
        try:
            dists = importlib.metadata.distributions(paths=[sp])
            for dist in dists:
                for ep in dist.entry_points:
                    if ep.group == "stepyard.commands":
                        try:
                            cmd = ep.load()
                            if isinstance(cmd, click.Command):
                                cli.add_command(cmd, name=ep.name)
                        except Exception as exc:
                            import logging

                            logging.warning("Failed to load plugin command %s: %s", ep.name, exc)
        except Exception:
            pass


_register_commands()

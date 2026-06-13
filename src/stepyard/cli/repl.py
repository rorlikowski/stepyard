import asyncio
import os
import shlex
import traceback

import click
import questionary
from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from rich.console import Console
from sqlalchemy import text

from stepyard.cli.app import cli, get_project_root, get_storage
from stepyard.cli.commands.run import _list_available_flows
from stepyard.cli.theme import C_MUTED, C_PRIMARY, C_SUCCESS, C_WHITE, LOGO, PROMPT_STYLE, VERSION

console = Console()

COMMANDS = [
    "run",
    "status",
    "show",
    "inspect",
    "logs",
    "replay",
    "init",
    "validate",
    "schema",
    "approvals",
    "service",
    "clear",
    "tools",
    "plugin",
    "doctor",
    "help",
    "exit",
]

ALIASES = {
    "r": "run",
    "s": "status",
    "l": "logs",
    "q": "exit",
    "quit": "exit",
    "e": "exit",
    "ls": "status",
}


class ClickCompleter(Completer):
    def __init__(self, cli):
        self.cli = cli

    def get_completions(self, document, complete_event):
        try:
            import shlex

            from click.shell_completion import ShellComplete

            text_before_cursor = document.text_before_cursor

            # Handle empty spaces correctly for shlex
            try:
                args = shlex.split(text_before_cursor)
            except ValueError:
                return

            if not text_before_cursor.endswith(" ") and len(args) > 0:
                incomplete = args[-1]
                args = args[:-1]
            else:
                incomplete = ""

            comp = ShellComplete(self.cli, {}, "cli", "")
            completions = comp.get_completions(args, incomplete)

            for c in completions:
                display_meta = getattr(c, "help", None)
                yield Completion(
                    c.value,
                    start_position=-len(incomplete),
                    display=c.value,
                    display_meta=display_meta,
                )
        except Exception:  # noqa: BLE001 - completion errors must not crash the REPL
            pass


def _create_completer():
    return ClickCompleter(cli)


def _prompt_for_flow():
    """Interactive fallback to ask for a flow when not provided."""
    try:
        storage = get_storage()
        flows = _list_available_flows(storage)
    except Exception:  # noqa: BLE001 - project may be uninitialized in interactive mode
        flows = []

    if not flows:
        console.print("[bold red]No available flows found.[/bold red]")
        return None

    from stepyard.core.flow import Flow
    from stepyard.core.service import Scheduler

    scheduler = Scheduler(get_storage())

    choices = []
    for flow_name in flows:
        flow_file = scheduler.find_flow_file(flow_name)
        desc = ""
        if flow_file:
            try:
                flow = Flow.from_file(flow_file)
                if flow.model.description:
                    desc = f" - {flow.model.description}"
            except Exception:  # noqa: BLE001 - flow file may be temporarily unreadable
                pass
        choices.append(questionary.Choice(f"{flow_name}{desc}", value=flow_name))

    prompt = questionary.select(
        "Which flow would you like to run?", choices=choices, style=PROMPT_STYLE
    )
    # Check if we are inside an event loop (we shouldn't be in this part of REPL, but just in case)
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If there's a running loop, questionary needs to be run differently or we just use .ask() and it might block
            # Actually prompt_toolkit shouldn't have an asyncio loop running around the main prompt loop
            pass
    except RuntimeError:
        pass

    return prompt.ask()


def _prompt_for_run_id(action: str):
    """Interactive fallback to ask for a run_id."""
    try:
        storage = get_storage()
        with storage.get_connection() as conn:
            runs = (
                conn.execute(
                    text(
                        "SELECT id, flow_name, start_time as created_at, status FROM runs ORDER BY start_time DESC LIMIT 20"
                    )
                )
                .mappings()
                .fetchall()
            )
    except Exception:
        runs = []

    if not runs:
        console.print("[bold red]No recent runs found.[/bold red]")
        return None

    choices = []
    for r in runs:
        choices.append(
            questionary.Choice(f"{r['id']} ({r['flow_name']} - {r['status']})", value=r["id"])
        )

    prompt = questionary.select(
        f"Which run would you like to {action}?", choices=choices, style=PROMPT_STYLE
    )
    return prompt.ask()


def start_repl(ctx: click.Context):
    """Start the Stepyard interactive REPL."""
    style = Style.from_dict(
        {
            "prompt": "bold #dddddd",
            "rprompt": "#888888",
            "bottom-toolbar": "bg:#222222 #ffffff",
            "bottom-toolbar.text": "#aaaaaa",
        }
    )

    # Auto-start scheduler daemon if not running
    try:
        from stepyard.api.service import StepyardService

        svc = StepyardService(get_project_root())
        if not svc.scheduler_status().is_running:
            svc.start_scheduler(foreground=False)
            console.print(f"[{C_MUTED}]Auto-started background daemon...[/{C_MUTED}]")
    except Exception:  # noqa: BLE001 - daemon auto-start is best-effort in interactive mode
        pass

    def get_bottom_toolbar():
        try:
            project_name = os.path.basename(get_project_root())
        except OSError:
            project_name = "unknown"
        return HTML(
            f" <b>Project:</b> {project_name} | <b>[Tab]</b> Autocomplete | <b>[↑/↓]</b> History | <b>Type</b> help"
        )

    def get_rprompt():
        return HTML(f"v{VERSION}")

    session = PromptSession(
        history=FileHistory(".stepyard_history"),
        completer=_create_completer(),
        auto_suggest=AutoSuggestFromHistory(),
        style=style,
        bottom_toolbar=get_bottom_toolbar,
        rprompt=get_rprompt,
        complete_while_typing=True,
    )

    console.print(LOGO)
    console.print(
        f"[{C_MUTED}]Welcome to [bold {C_PRIMARY}]Stepyard[/bold {C_PRIMARY}] interactive mode.[/{C_MUTED}]\n"
    )

    try:
        storage = get_storage()
        flows = _list_available_flows(storage)
        num_flows = len(flows)
    except Exception:  # noqa: BLE001 - project may be uninitialized
        num_flows = 0

    try:
        project_path = get_project_root()
    except OSError:
        project_path = "unknown"

    from rich import box
    from rich.panel import Panel

    guide_text = (
        f"[bold {C_PRIMARY}]💡 Quick Start Guide:[/bold {C_PRIMARY}]\n\n"
        f"  • Type [bold {C_SUCCESS}]run[/bold {C_SUCCESS}] or [bold {C_SUCCESS}]r[/bold {C_SUCCESS}] to execute a flow interactively.\n"
        f"  • Type [bold {C_SUCCESS}]status[/bold {C_SUCCESS}] or [bold {C_SUCCESS}]s[/bold {C_SUCCESS}] to view the current status of all flows.\n"
        f"  • Type [bold {C_SUCCESS}]logs[/bold {C_SUCCESS}] or [bold {C_SUCCESS}]l[/bold {C_SUCCESS}] to inspect logs from recent executions.\n"
        f"  • Type [bold {C_SUCCESS}]help[/bold {C_SUCCESS}] for a complete list of commands.\n\n"
        f"[bold {C_PRIMARY}]📁 Project Context:[/bold {C_PRIMARY}]\n"
        f"  • Directory: [bold {C_WHITE}]{project_path}[/bold {C_WHITE}]\n"
        f"  • Available flows: [bold {C_WHITE}]{num_flows}[/bold {C_WHITE}]\n\n"
        f"[{C_MUTED}]Press \\[Tab] for autocompletion. Enjoy building your flows![/]"
    )
    console.print(
        Panel(
            guide_text,
            border_style=C_PRIMARY,
            title=f"[{C_PRIMARY}]Getting Started[/{C_PRIMARY}]",
            expand=False,
            box=box.ROUNDED,
        )
    )
    console.print()

    while True:
        try:
            text = session.prompt("stepyard ❯ ")
            text = text.strip()

            if not text:
                continue

            # Parse the command
            try:
                args = shlex.split(text)
            except ValueError as e:
                console.print(f"[bold red]Error parsing command:[/bold red] {e}")
                continue

            if not args:
                continue

            # Alias expansion
            cmd_name = args[0]
            if cmd_name in ALIASES:
                cmd_name = ALIASES[cmd_name]
                args[0] = cmd_name

            # Handle built-in exits after alias expansion
            if cmd_name == "exit":
                break

            if cmd_name == "help":
                console.print(cli.get_help(ctx))
                continue

            # Smart fallback for commands needing an argument
            if len(args) == 1:
                if cmd_name == "run":
                    selected = _prompt_for_flow()
                    if not selected:
                        continue
                    args.append(selected)
                elif cmd_name in ("show", "logs", "replay"):
                    selected = _prompt_for_run_id(cmd_name)
                    if not selected:
                        continue
                    args.append(selected)

            # Execute the command
            try:
                cli.main(args=args, standalone_mode=False)
            except click.exceptions.Exit:
                pass
            except click.exceptions.UsageError as e:
                e.show()
            except click.exceptions.Abort:
                console.print(f"\n[{C_MUTED}]Command aborted.[/{C_MUTED}]")
            except Exception as e:
                console.print(f"[bold red]Error executing command:[/bold red] {e}")
                traceback.print_exc()

        except KeyboardInterrupt:
            continue
        except EOFError:
            break

    console.print(f"[{C_MUTED}]Goodbye![/{C_MUTED}]")

"""
Stepyard CLI - Developer Experience commands.

``stepyard init``     - scaffold a new project
``stepyard validate`` - validate flow YAML without running
``stepyard schema``   - export JSON Schema for flow YAML
"""

from __future__ import annotations

import os

import click
from rich import box
from rich.panel import Panel

from stepyard.cli.app import cli
from stepyard.cli.theme import C_ACCENT, C_ERROR, C_MUTED, C_SUCCESS
from stepyard.cli.ui import console, print_success, print_warning

# ── init ─────────────────────────────────────────────────────────────────────


@cli.command(name="init")
@click.argument("directory", default=".", type=click.Path())
@click.option("--force", "-f", is_flag=True, help="Overwrite existing files")
def init(directory: str, force: bool) -> None:
    """Scaffold a new Stepyard project.

    Creates a ``flows/`` directory with an example flow and a ``.gitignore``
    entry for ``.stepyard/``.
    """
    from stepyard.api.service import StepyardService  # noqa: PLC0415

    project_dir = os.path.abspath(directory)
    os.makedirs(project_dir, exist_ok=True)

    svc = StepyardService(project_dir)
    result = svc.init_project(force=force)

    console.print()
    if result["created"]:
        console.print(
            Panel(
                "\n".join(f"  [bold {C_SUCCESS}]✓[/] {f}" for f in result["created"]),
                title=f"[bold {C_SUCCESS}]Project initialised[/bold {C_SUCCESS}]",
                border_style=C_SUCCESS,
                padding=(0, 2),
                box=box.ROUNDED,
            )
        )
    if result["skipped"]:
        for f in result["skipped"]:
            console.print(f"  [{C_MUTED}]skipped (already exists):[/{C_MUTED}] {f}")

    console.print()
    console.print(
        f"  [dim]Next:[/dim] edit [bold {C_ACCENT}]{os.path.join(directory, 'flows', 'hello.yaml')}[/] "
        f"then run [bold {C_ACCENT}]stepyard run hello[/bold {C_ACCENT}]"
    )
    console.print()


# ── validate ─────────────────────────────────────────────────────────────────


@cli.command(name="validate")
@click.argument("flow_files", nargs=-1, type=click.Path(exists=True), required=False)
@click.option(
    "--all",
    "validate_all",
    is_flag=True,
    help="Validate all flows in the project flows/ directory",
)
def validate(flow_files: tuple[str, ...], validate_all: bool) -> None:
    """Validate one or more flow YAML files without executing them.

    Checks schema validity, step IDs, and whether all ``uses`` values are
    registered in the capability registry.
    """
    from stepyard.api.service import StepyardService  # noqa: PLC0415

    svc = StepyardService.from_cwd()

    files_to_check: list[str] = list(flow_files)

    if validate_all or not files_to_check:
        flows_dir = os.path.join(svc.project_dir, "flows")
        if os.path.isdir(flows_dir):
            files_to_check = [
                os.path.join(flows_dir, fn)
                for fn in os.listdir(flows_dir)
                if fn.endswith((".yaml", ".yml"))
            ]

    if not files_to_check:
        print_warning("No flow files found.  Pass a file path or use --all.")
        raise click.exceptions.Exit(0)

    all_ok = True
    for fpath in sorted(files_to_check):
        rel = os.path.relpath(fpath, svc.project_dir)
        errors = svc.validate_flow(fpath)
        if not errors:
            console.print(f"  [bold {C_SUCCESS}]✓[/bold {C_SUCCESS}] {rel}")
        else:
            all_ok = False
            console.print(f"  [bold {C_ERROR}]✗[/bold {C_ERROR}] {rel}")
            for err in errors:
                field = err.get("field", "")
                msg = err.get("message", "")
                hint = err.get("hint", "")
                console.print(
                    f"      [{C_ERROR}]{field}:[/{C_ERROR}] {msg}"
                    + (f"\n      [{C_MUTED}]→ {hint}[/{C_MUTED}]" if hint else "")
                )

    console.print()
    if not all_ok:
        raise click.exceptions.Exit(1)


# ── schema ───────────────────────────────────────────────────────────────────


@cli.command(name="schema")
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default=None,
    help="Output path (default: .stepyard/flow.schema.json)",
)
def schema(output: str | None) -> None:
    """Export a JSON Schema for flow YAML to enable editor autocompletion.

    After running this command, add the following modeline to your flow YAML
    to get autocompletion and inline validation in VS Code / Cursor:

    \\b
        # yaml-language-server: $schema=.stepyard/flow.schema.json
    """
    from stepyard.api.service import StepyardService  # noqa: PLC0415

    svc = StepyardService.from_cwd()
    out_path = svc.export_flow_schema(output_path=output)

    rel = os.path.relpath(out_path, svc.project_dir)
    print_success(
        f"JSON Schema written to {rel}",
        subtitle=(
            "Add this modeline to your flow YAML for editor autocompletion:\n"
            f"  # yaml-language-server: $schema={rel}"
        ),
    )

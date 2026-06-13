"""
Stepyard CLI - ``tools`` command group.

Provides node and trigger discovery via ``stepyard tools list``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import click
from rich import box
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from stepyard.cli.app import SubRichGroup, cli, get_storage
from stepyard.cli.theme import (
    C_ACCENT,
    C_DIM,
    C_HINT,
    C_MUTED,
    C_PRIMARY,
    C_SUCCESS,
    C_WHITE,
)
from stepyard.cli.ui import console, print_warning
from stepyard.plugin import CapabilityRegistry, PluginManager


@click.group(name="tools", cls=SubRichGroup)
def tools_group():
    """Discover and manage extensions and nodes."""


def parse_docstring(doc: str) -> tuple[str, list[str], list[str]]:
    if not doc:
        return "No description available.", [], []

    lines = doc.strip().split("\n")
    desc = lines[0].strip()

    args = []
    outputs = []
    current_section = None

    for line in lines[1:]:
        line_stripped = line.strip()
        if not line_stripped:
            continue
        if line_stripped == "Args:":
            current_section = "args"
            continue
        elif line_stripped == "Outputs:":
            current_section = "outputs"
            continue

        if current_section == "args":
            args.append(line_stripped)
        elif current_section == "outputs":
            outputs.append(line_stripped)

    return desc, args, outputs


def _capability_source(
    registry: CapabilityRegistry, name: str, func, kind: str = "node"
) -> tuple[str, str, str]:
    info = registry.get_node_info(name) if kind == "node" else registry.get_trigger_info(name)
    source = info.source if info else (getattr(func, "__module__", "") or "unknown")
    source_kind = "built-in" if "-> stepyard_builtin." in source else "plugin"
    color = C_SUCCESS if source_kind == "built-in" else C_ACCENT
    return source_kind, source, color


def _source_group_label(kind: str, source: str) -> str:
    if kind == "built-in":
        module = source.split("->", 1)[-1].strip()
        return f"{module.rsplit('.', 1)[-1]} (built-in)"
    if "->" in source:
        return source.split("->", 1)[-1].strip().split(".", 1)[0]
    return source.split(".", 1)[0]


def _source_display_name(kind: str, source: str) -> str:
    return kind


def _node_summary(func) -> str:
    doc = getattr(func, "__doc__", "") or ""
    desc, _, _ = parse_docstring(doc)
    return desc


def _object_origin(func) -> str:
    return getattr(func, "__module__", "") or "unknown"


def _format_inputs(func) -> str:
    import inspect as py_inspect

    try:
        params = py_inspect.signature(func).parameters
    except Exception:
        return "unknown"

    items: list[str] = []
    for name, param in params.items():
        if name in ("ctx", "context"):
            continue
        required = param.default == py_inspect.Parameter.empty
        items.append(f"{name}" if required else f"{name}?")
    return ", ".join(items) if items else "none"


def _format_output(func) -> str:
    import inspect as py_inspect
    from typing import get_args, get_origin

    try:
        annotation = py_inspect.signature(func).return_annotation
    except Exception:
        annotation = py_inspect.Parameter.empty

    if annotation != py_inspect.Parameter.empty:
        origin = get_origin(annotation)
        if origin is not None:
            args = ", ".join(_type_name(arg) for arg in get_args(annotation))
            return f"{_type_name(origin)}[{args}]"
        return _type_name(annotation)

    _, _, doc_outputs = parse_docstring(getattr(func, "__doc__", "") or "")
    if doc_outputs:
        return doc_outputs[0].split(":", 1)[0].strip()
    return "unknown"


def _format_output_contract(func) -> str:
    output_type = _format_output(func)
    _, _, doc_outputs = parse_docstring(getattr(func, "__doc__", "") or "")
    if not doc_outputs:
        return f"output ({output_type})"

    keyed_outputs: list[str] = []
    return_outputs: list[str] = []
    for item in doc_outputs:
        if ":" in item and not item.lower().startswith("returns"):
            key, desc = item.split(":", 1)
            key = key.strip()
            desc = desc.strip()
            keyed_outputs.append(f"output.{key}: {desc}" if desc else f"output.{key}")
        else:
            return_outputs.append(item.strip())

    if keyed_outputs:
        return "\n".join(keyed_outputs)

    if return_outputs:
        return f"output ({output_type}): {' '.join(return_outputs)}"
    return f"output ({output_type})"


def _type_name(annotation) -> str:
    if annotation is None:
        return "None"
    if isinstance(annotation, str):
        return annotation
    name = getattr(annotation, "__name__", None)
    if name:
        return name
    return str(annotation).replace("typing.", "")


def _render_node_catalog(nodes: list[tuple[str, object]], registry: CapabilityRegistry) -> None:
    grouped: dict[tuple[str, str, str], list[tuple[str, object]]] = {}
    for name, func in nodes:
        grouped.setdefault(_capability_source(registry, name, func), []).append((name, func))

    total_plugins = len(
        {source.split(".", 1)[0] for kind, source, _ in grouped if kind == "plugin"}
    )
    console.print()
    console.print(
        Panel(
            f"[bold {C_WHITE}]{len(nodes)} nodes discovered[/bold {C_WHITE}]\n"
            f"[{C_MUTED}]Grouped by source. Inputs ending with '?' are optional.[/{C_MUTED}]\n"
            f"[{C_MUTED}]Plugin sources: {total_plugins}[/{C_MUTED}]",
            title=f"[bold {C_PRIMARY}]Node Catalog[/bold {C_PRIMARY}]",
            border_style=C_PRIMARY,
            padding=(1, 2),
            box=box.ROUNDED,
        )
    )

    for (kind, source, color), source_nodes in sorted(grouped.items(), key=lambda item: item[0][1]):
        source_label = _source_group_label(kind, source)
        table = Table(
            title=f"[bold {color}]{escape(source_label)}[/bold {color}]",
            title_justify="left",
            show_header=True,
            header_style=f"bold {C_PRIMARY}",
            box=box.SIMPLE_HEAVY,
            border_style=C_DIM,
            padding=(0, 1),
            expand=True,
        )
        table.add_column("Node", style=f"bold {C_WHITE}", no_wrap=True, ratio=2)
        table.add_column("Source", style=C_ACCENT if kind == "plugin" else C_SUCCESS, ratio=2)
        table.add_column("Inputs", style=C_HINT, ratio=3)
        table.add_column("Output", style=C_WHITE, ratio=4)
        table.add_column("Description", style=C_MUTED, ratio=4)

        for name, func in sorted(source_nodes, key=lambda item: item[0]):
            table.add_row(
                escape(name),
                escape(_source_display_name(kind, source)),
                escape(_format_inputs(func)),
                escape(_format_output_contract(func)),
                escape(_node_summary(func)),
            )
        console.print(table)
        console.print()


@dataclass(frozen=True)
class PluginInfo:
    name: str
    version: str
    location: str
    entry_points: tuple[tuple[str, str, str], ...]
    lock_spec: str | None = None

    @property
    def nodes(self) -> tuple[str, ...]:
        return tuple(name for group, name, _ in self.entry_points if group == "stepyard.plugins")

    @property
    def triggers(self) -> tuple[str, ...]:
        return tuple(name for group, name, _ in self.entry_points if group == "stepyard.triggers")

    @property
    def commands(self) -> tuple[str, ...]:
        return tuple(name for group, name, _ in self.entry_points if group == "stepyard.commands")


def _read_lock_specs(pm: PluginManager) -> list[str]:
    if not os.path.exists(pm.lockfile_path):
        return []
    try:
        with open(pm.lockfile_path, encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    except Exception:
        return []


def _local_spec_for_package(name: str, specs: list[str]) -> str | None:
    for spec in specs:
        if not os.path.exists(spec):
            continue
        pyproject = os.path.join(spec, "pyproject.toml")
        if not os.path.exists(pyproject):
            continue
        try:
            import tomllib

            with open(pyproject, "rb") as f_in:
                data = tomllib.load(f_in)
            if data.get("project", {}).get("name") == name:
                return spec
        except Exception:
            continue
    return None


def _discover_plugin_infos(pm: PluginManager) -> list[PluginInfo]:
    import importlib.metadata

    sp = pm.get_site_packages()
    if not os.path.exists(sp):
        return []

    lock_specs = _read_lock_specs(pm)
    plugins: list[PluginInfo] = []
    for dist in importlib.metadata.distributions(paths=[sp]):
        entries = tuple(
            (ep.group, ep.name, ep.value)
            for ep in dist.entry_points
            if ep.group in ("stepyard.plugins", "stepyard.triggers", "stepyard.commands")
        )
        if not entries:
            continue

        name = dist.metadata["Name"]
        local_spec = _local_spec_for_package(name, lock_specs)
        location = f"local ({local_spec})" if local_spec else "site-packages"
        plugins.append(
            PluginInfo(
                name=name,
                version=dist.version,
                location=location,
                entry_points=entries,
                lock_spec=local_spec,
            )
        )

    return sorted(plugins, key=lambda p: p.name.lower())


def _plugin_detail_lines(plugin: PluginInfo) -> list[str]:
    lines = [
        plugin.name,
        f"Version:  {plugin.version}",
        f"Location: {plugin.location}",
        "",
        f"Nodes:    {', '.join(plugin.nodes) if plugin.nodes else 'none'}",
        f"Triggers: {', '.join(plugin.triggers) if plugin.triggers else 'none'}",
        f"Commands: {', '.join(plugin.commands) if plugin.commands else 'none'}",
        "",
        "Entry points:",
    ]
    for group, name, value in plugin.entry_points:
        lines.append(f"  {group:<16} {name:<18} {value}")
    return lines


def _print_plugin_catalog(plugins: list[PluginInfo]) -> None:
    table = Table(
        title="[bold]Installed Plugins[/bold]",
        title_style=f"bold {C_WHITE}",
        box=box.SIMPLE_HEAVY,
        border_style=C_DIM,
        header_style=f"bold {C_PRIMARY}",
        padding=(0, 1),
        expand=True,
    )
    table.add_column("Package", style=f"bold {C_ACCENT}", no_wrap=True)
    table.add_column("Version", style=C_WHITE, no_wrap=True)
    table.add_column("Capabilities", style=C_HINT)
    table.add_column("Origin", style=C_MUTED)

    for plugin in plugins:
        caps = []
        if plugin.nodes:
            caps.append(f"{len(plugin.nodes)} node entry")
        if plugin.triggers:
            caps.append(f"{len(plugin.triggers)} trigger entry")
        if plugin.commands:
            caps.append(f"{len(plugin.commands)} command entry")
        table.add_row(
            escape(plugin.name),
            escape(plugin.version),
            escape(", ".join(caps) or "metadata only"),
            escape(plugin.location),
        )

    console.print()
    console.print(table)
    console.print()

    for plugin in plugins:
        console.print(
            Panel(
                "\n".join(escape(line) for line in _plugin_detail_lines(plugin)),
                title=f"[bold {C_WHITE}]{escape(plugin.name)}[/bold {C_WHITE}]",
                title_align="left",
                border_style=C_ACCENT if plugin.location.startswith("local") else C_DIM,
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )


def _browse_plugins(plugins: list[PluginInfo]) -> None:
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import HSplit, VSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style

    selected = 0
    kb = KeyBindings()

    def list_fragments():
        fragments = [("class:hint", " Installed plugins\n\n")]
        width = max(24, min(38, max(len(p.name) for p in plugins) + 4))
        for idx, plugin in enumerate(plugins):
            style = "class:selected" if idx == selected else "class:item"
            marker = ">" if idx == selected else " "
            fragments.append((style, f" {marker} {plugin.name:<{width}} {plugin.version}\n"))
        fragments.append(("class:hint", "\n Up/Down select  Enter/Esc close"))
        return fragments

    def detail_fragments():
        plugin = plugins[selected]
        fragments = [
            ("class:title", f"{plugin.name}\n"),
            ("class:muted", f"version  {plugin.version}\n"),
            ("class:muted", f"{plugin.location}\n\n"),
            ("class:label", "Capabilities\n"),
            ("class:text", f"  nodes     {', '.join(plugin.nodes) if plugin.nodes else 'none'}\n"),
            (
                "class:text",
                f"  triggers  {', '.join(plugin.triggers) if plugin.triggers else 'none'}\n",
            ),
            (
                "class:text",
                f"  commands  {', '.join(plugin.commands) if plugin.commands else 'none'}\n\n",
            ),
            ("class:label", "Entry points\n"),
        ]
        for group, name, value in plugin.entry_points:
            fragments.append(("class:muted", f"  {group:<16} "))
            fragments.append(("class:accent", f"{name:<18} "))
            fragments.append(("class:text", f"{value}\n"))
        return fragments

    @kb.add("up")
    def _up(event):
        nonlocal selected
        selected = (selected - 1) % len(plugins)
        event.app.invalidate()

    @kb.add("down")
    def _down(event):
        nonlocal selected
        selected = (selected + 1) % len(plugins)
        event.app.invalidate()

    @kb.add("enter")
    @kb.add("escape")
    @kb.add("c-c")
    @kb.add("q")
    def _close(event):
        event.app.exit()

    root = VSplit(
        [
            Window(FormattedTextControl(list_fragments), width=46, wrap_lines=False),
            Window(width=1, char=" ", style="class:gutter"),
            Window(FormattedTextControl(detail_fragments), wrap_lines=True),
        ]
    )

    app = Application(
        layout=Layout(HSplit([root])),
        key_bindings=kb,
        full_screen=True,
        style=Style.from_dict(
            {
                "item": "#cbd5e1",
                "selected": "bold #f8fafc bg:#1e293b",
                "title": "bold #f8fafc",
                "label": "bold #38bdf8",
                "accent": "bold #a78bfa",
                "text": "#e2e8f0",
                "muted": "#94a3b8",
                "hint": "#64748b",
                "gutter": "bg:#0f172a",
            }
        ),
    )
    app.run()


@tools_group.command(name="list")
def list_nodes():
    """List all available built-in nodes and discovered plugins."""
    from stepyard.plugin import discover_capabilities

    storage = get_storage()
    registry = discover_capabilities(storage.project_dir)

    if not registry.nodes:
        print_warning("No nodes discovered.")
        return

    sorted_nodes = sorted(registry.nodes.items(), key=lambda x: x[0])
    _render_node_catalog(sorted_nodes, registry)

    console.print()

    # --- Render Triggers Table ---
    if registry.triggers:
        sorted_triggers = sorted(registry.triggers.items(), key=lambda x: x[0])
        table = Table(
            title=f"[bold {C_PRIMARY}]Trigger Catalog[/bold {C_PRIMARY}]",
            title_justify="left",
            show_header=True,
            header_style=f"bold {C_PRIMARY}",
            box=box.SIMPLE_HEAVY,
            border_style=C_DIM,
            padding=(0, 1),
            expand=True,
        )
        table.add_column("Trigger", style=f"bold {C_WHITE}", no_wrap=True, ratio=2)
        table.add_column("Source", style=C_ACCENT, ratio=2)
        table.add_column("Inputs", style=C_HINT, ratio=3)
        table.add_column("Description", style=C_MUTED, ratio=5)

        for name, func in sorted_triggers:
            kind, source, _ = _capability_source(registry, name, func, kind="trigger")
            table.add_row(
                escape(name),
                escape(_source_display_name(kind, source)),
                escape(_format_inputs(func)),
                escape(_node_summary(func)),
            )
        console.print(table)
        console.print()


cli.add_command(tools_group)

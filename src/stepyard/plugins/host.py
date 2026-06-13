"""Plugin host and capability registry.

This is the single discovery path used by the engine, scheduler and CLI.
Capabilities are loaded from entry points in the current environment and from
the project-local ``.stepyard/env`` environment.
"""

from __future__ import annotations

import importlib.metadata
import inspect
import logging
import os
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any, Protocol

from stepyard.plugins.manager import PluginManager

logger = logging.getLogger("stepyard.plugins")


PLUGIN_GROUPS = (
    "stepyard.plugins",
    "stepyard.triggers",
    "stepyard.hooks",
    "stepyard.input_collectors",
    "stepyard.commands",
)


@dataclass(frozen=True)
class CapabilityInfo:
    """Metadata for one discovered capability."""

    kind: str
    name: str
    source: str
    obj: Any
    isolated: bool = False
    python_executable: str | None = None


@dataclass
class DiscoveryError:
    """One plugin entry-point that failed to load during discovery."""

    group: str
    name: str
    value: str
    error: str
    traceback: str = ""

    def __str__(self) -> str:
        return f"{self.group}:{self.name} -> {self.value}: {self.error}"


@dataclass
class DiscoveryReport:
    """Result of ``PluginHost.discover()`` including any load failures.

    The CLI commands ``stepyard doctor`` and ``stepyard tools list`` use this
    report to surface broken plugins with actionable hints.
    """

    registry: CapabilityRegistry
    errors: list[DiscoveryError] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)


class CapabilityProvider(Protocol):
    nodes: dict[str, Callable[..., Any]]
    triggers: dict[str, Callable[..., Any]]
    hooks: list[Any]
    input_collectors: dict[str, Callable[..., Any]]
    commands: dict[str, Any]

    def get_node(self, name: str) -> Callable[..., Any] | None: ...

    def get_node_info(self, name: str) -> CapabilityInfo | None: ...

    def get_trigger(self, name: str) -> Callable[..., Any] | None: ...

    def get_input_collector(self, name: str) -> Callable[..., Any] | None: ...


class CapabilityRegistry:
    """In-memory lookup table for all plugin capabilities."""

    def __init__(self) -> None:
        self.nodes: dict[str, Callable[..., Any]] = {}
        self.triggers: dict[str, Callable[..., Any]] = {}
        self.hooks: list[Any] = []
        self.input_collectors: dict[str, Callable[..., Any]] = {}
        self.commands: dict[str, Any] = {}
        self.metadata: list[CapabilityInfo] = []
        self._node_info: dict[str, CapabilityInfo] = {}
        self._trigger_info: dict[str, CapabilityInfo] = {}

    def register_node(
        self,
        name: str,
        func: Callable[..., Any],
        source: str,
        *,
        isolated: bool = False,
        python_executable: str | None = None,
    ) -> None:
        self._check_conflict("node", name, self.nodes.get(name), func)
        self.nodes[name] = func
        info = self._record("node", name, source, func, isolated, python_executable)
        self._node_info[name] = info

    def register_trigger(
        self,
        name: str,
        func: Callable[..., Any],
        source: str,
        *,
        isolated: bool = False,
        python_executable: str | None = None,
    ) -> None:
        self._check_conflict("trigger", name, self.triggers.get(name), func)
        self.triggers[name] = func
        info = self._record("trigger", name, source, func, isolated, python_executable)
        self._trigger_info[name] = info

    def register_hook(
        self,
        hook: Any,
        source: str,
        *,
        isolated: bool = False,
        python_executable: str | None = None,
    ) -> None:
        if hook not in self.hooks:
            self.hooks.append(hook)
            self._record("hook", hook.__class__.__name__, source, hook, isolated, python_executable)

    def register_input_collector(
        self,
        name: str,
        collector: Callable[..., Any],
        source: str,
        *,
        isolated: bool = False,
        python_executable: str | None = None,
    ) -> None:
        self._check_conflict("input_collector", name, self.input_collectors.get(name), collector)
        self.input_collectors[name] = collector
        self._record("input_collector", name, source, collector, isolated, python_executable)

    def register_command(
        self,
        name: str,
        command: Any,
        source: str,
        *,
        isolated: bool = False,
        python_executable: str | None = None,
    ) -> None:
        self._check_conflict("command", name, self.commands.get(name), command)
        self.commands[name] = command
        self._record("command", name, source, command, isolated, python_executable)

    def get_node(self, name: str) -> Callable[..., Any] | None:
        return self.nodes.get(name)

    def get_node_info(self, name: str) -> CapabilityInfo | None:
        return self._node_info.get(name)

    def get_trigger(self, name: str) -> Callable[..., Any] | None:
        return self.triggers.get(name)

    def get_trigger_info(self, name: str) -> CapabilityInfo | None:
        return self._trigger_info.get(name)

    def get_input_collector(self, name: str) -> Callable[..., Any] | None:
        return self.input_collectors.get(name)

    def _record(
        self,
        kind: str,
        name: str,
        source: str,
        obj: Any,
        isolated: bool,
        python_executable: str | None,
    ) -> CapabilityInfo:
        existing = next(
            (
                item
                for item in self.metadata
                if item.kind == kind and item.name == name and item.obj is obj
            ),
            None,
        )
        if existing is not None:
            return existing

        info = CapabilityInfo(
            kind=kind,
            name=name,
            source=source,
            obj=obj,
            isolated=isolated,
            python_executable=python_executable,
        )
        self.metadata.append(info)
        return info

    @staticmethod
    def _check_conflict(kind: str, name: str, current: Any, incoming: Any) -> None:
        if current is not None and current is not incoming:
            from stepyard.core.errors import PluginError  # noqa: PLC0415

            current_source = _object_source(current)
            incoming_source = _object_source(incoming)
            raise PluginError(
                f"Duplicate {kind} capability '{name}' from {incoming_source}; "
                f"already registered by {current_source}.",
                plugin_name=incoming_source,
            )


@dataclass(frozen=True)
class _EntryPointSource:
    entry_point: importlib.metadata.EntryPoint
    isolated: bool
    python_executable: str | None


class PluginHost:
    """Loads system and installed plugin capabilities for one project."""

    def __init__(self, project_dir: str) -> None:
        self.project_dir = os.path.abspath(project_dir)
        self.plugin_manager = PluginManager(self.project_dir)

    def discover(self) -> DiscoveryReport:
        """Discover all capabilities and return a :class:`DiscoveryReport`.

        Errors are collected into the report rather than only being logged so
        that callers can surface broken plugins to users.
        """
        import traceback as _tb  # noqa: PLC0415

        registry = CapabilityRegistry()
        errors: list[DiscoveryError] = []

        for source in self._iter_entry_points():
            entry_point = source.entry_point
            module_name = _entry_point_module(entry_point)
            try:
                loaded = entry_point.load()
            except Exception as exc:
                tb_str = _tb.format_exc()
                error = DiscoveryError(
                    group=entry_point.group,
                    name=entry_point.name,
                    value=entry_point.value,
                    error=str(exc),
                    traceback=tb_str,
                )
                errors.append(error)
                logger.error("Failed to load plugin %s: %s", error, exc)
                continue

            self._register_loaded_object(registry, loaded, entry_point, source, module_name)

        return DiscoveryReport(registry=registry, errors=errors)

    def _iter_entry_points(self) -> Iterable[_EntryPointSource]:
        seen: set[tuple[str, str, str, bool]] = set()

        for entry_point in _current_environment_entry_points():
            key = (entry_point.group, entry_point.name, entry_point.value, False)
            if key not in seen:
                seen.add(key)
                yield _EntryPointSource(entry_point, isolated=False, python_executable=None)

        site_packages = self.plugin_manager.get_site_packages()
        if not os.path.exists(site_packages):
            return

        _ensure_sys_path(site_packages)
        try:
            distributions = importlib.metadata.distributions(paths=[site_packages])
            for dist in distributions:
                for entry_point in dist.entry_points:
                    if entry_point.group not in PLUGIN_GROUPS:
                        continue
                    key = (entry_point.group, entry_point.name, entry_point.value, True)
                    if key in seen:
                        continue
                    seen.add(key)
                    yield _EntryPointSource(
                        entry_point,
                        isolated=True,
                        python_executable=self.plugin_manager.venv_python,
                    )
        except Exception as exc:
            logger.error("Error discovering plugins in %s: %s", site_packages, exc)

    def _register_loaded_object(
        self,
        registry: CapabilityRegistry,
        loaded: Any,
        entry_point: importlib.metadata.EntryPoint,
        source: _EntryPointSource,
        module_name: str,
    ) -> None:
        objects = list(_iter_public_objects(loaded))
        if loaded not in objects:
            objects.append(loaded)

        for obj in objects:
            self._register_object(registry, obj, entry_point, source, module_name)

    def _register_object(
        self,
        registry: CapabilityRegistry,
        obj: Any,
        entry_point: importlib.metadata.EntryPoint,
        source: _EntryPointSource,
        module_name: str,
    ) -> None:
        source_name = _entry_point_source(entry_point)

        node_name = (
            getattr(obj, "__stepyard_name__", None)
            if getattr(obj, "__stepyard_node__", False)
            else None
        )
        if node_name and _belongs_to_module(obj, module_name):
            registry.register_node(
                node_name,
                obj,
                source_name,
                isolated=source.isolated,
                python_executable=source.python_executable,
            )
            return

        trigger_name = (
            getattr(obj, "__stepyard_name__", None)
            if getattr(obj, "__stepyard_trigger__", False)
            else None
        )
        if trigger_name and _belongs_to_module(obj, module_name):
            registry.register_trigger(
                trigger_name,
                obj,
                source_name,
                isolated=source.isolated,
                python_executable=source.python_executable,
            )
            return

        collector_name = getattr(obj, "__stepyard_input_collector__", None)
        if collector_name and _belongs_to_module(obj, module_name):
            registry.register_input_collector(
                collector_name,
                obj,
                source_name,
                isolated=source.isolated,
                python_executable=source.python_executable,
            )
            return

        if _is_hook_instance(obj) and _belongs_to_module(obj, module_name):
            registry.register_hook(
                obj,
                source_name,
                isolated=source.isolated,
                python_executable=source.python_executable,
            )
            return

        if entry_point.group == "stepyard.commands":
            registry.register_command(
                entry_point.name,
                obj,
                source_name,
                isolated=source.isolated,
                python_executable=source.python_executable,
            )


def discover_capabilities(project_dir: str) -> CapabilityRegistry:
    """Discover capabilities and return the registry (backward-compatible API).

    Use :meth:`PluginHost.discover` directly when you need the full
    :class:`DiscoveryReport` including any load errors.
    """
    return PluginHost(project_dir).discover().registry


def _current_environment_entry_points() -> Iterable[importlib.metadata.EntryPoint]:
    try:
        entry_points = importlib.metadata.entry_points()
        if hasattr(entry_points, "select"):
            result: list[importlib.metadata.EntryPoint] = []
            for group in PLUGIN_GROUPS:
                result.extend(entry_points.select(group=group))
            return result
        return [
            ep
            for group, entries in entry_points.items()
            if group in PLUGIN_GROUPS
            for ep in entries
        ]
    except Exception as exc:
        logger.error("Error reading current environment entry points: %s", exc)
        return []


def _ensure_sys_path(path: str) -> None:
    if path not in sys.path:
        sys.path.append(path)


def _entry_point_module(entry_point: importlib.metadata.EntryPoint) -> str:
    return entry_point.value.split(":", 1)[0].strip()


def _entry_point_source(entry_point: importlib.metadata.EntryPoint) -> str:
    return f"{entry_point.group}:{entry_point.name} -> {entry_point.value}"


def _iter_public_objects(loaded: Any) -> Iterable[Any]:
    if isinstance(loaded, ModuleType):
        for name, value in vars(loaded).items():
            if name.startswith("_"):
                continue
            if isinstance(value, ModuleType):
                continue
            yield from _iter_public_objects(value)
        return
    if isinstance(loaded, dict):
        for value in loaded.values():
            yield from _iter_public_objects(value)
        return
    if isinstance(loaded, (list, tuple, set, frozenset)):
        for value in loaded:
            yield from _iter_public_objects(value)
        return
    yield loaded


def _is_hook_instance(obj: Any) -> bool:
    return (
        not inspect.isclass(obj)
        and callable(getattr(obj, "before_execute", None))
        and callable(getattr(obj, "after_execute", None))
    )


def _belongs_to_module(obj: Any, module_name: str) -> bool:
    obj_module = _object_source(obj)
    return obj_module == module_name or obj_module.startswith(f"{module_name}.")


def _object_source(obj: Any) -> str:
    module = getattr(obj, "__module__", "")
    if module:
        return module
    cls = getattr(obj, "__class__", None)
    return getattr(cls, "__module__", "unknown")

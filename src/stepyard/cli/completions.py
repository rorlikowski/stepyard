from __future__ import annotations

import os

from click import Context, Parameter
from click.shell_completion import CompletionItem


def _get_storage():
    """Helper to lazily import get_storage to avoid circular dependencies."""
    from stepyard.cli.app import get_storage

    return get_storage()


def complete_flows(ctx: Context, param: Parameter, incomplete: str) -> list[CompletionItem]:
    """Provide shell completion for available flow names."""
    from stepyard.cli.commands.run import _list_available_flows

    try:
        storage = _get_storage()
        flows = _list_available_flows(storage)
    except Exception:  # noqa: BLE001 - completions must never crash the shell
        flows = []

    return [CompletionItem(flow) for flow in flows if incomplete in flow]


def complete_runs(ctx: Context, param: Parameter, incomplete: str) -> list[CompletionItem]:
    """Provide shell completion for recent Run IDs."""
    try:
        storage = _get_storage()
        with storage.get_connection() as conn:
            from sqlalchemy import text

            runs = (
                conn.execute(
                    text("SELECT id, flow_name, status FROM runs ORDER BY start_time DESC LIMIT 50")
                )
                .mappings()
                .fetchall()
            )
    except Exception:  # noqa: BLE001 - completions must never crash the shell
        runs = []

    results = []
    for r in runs:
        run_id = r["id"]
        if incomplete in run_id:
            help_text = f"{r['flow_name']} ({r['status']})"
            results.append(CompletionItem(run_id, help=help_text))

    return results


def complete_runs_or_flows(ctx: Context, param: Parameter, incomplete: str) -> list[CompletionItem]:
    """Provide shell completion for both flows and recent Run IDs."""
    flows = complete_flows(ctx, param, incomplete)
    runs = complete_runs(ctx, param, incomplete)
    return flows + runs


def complete_installed_plugins(
    ctx: Context, param: Parameter, incomplete: str
) -> list[CompletionItem]:
    """Provide shell completion for installed stepyard plugins."""
    import importlib.metadata

    from stepyard.plugin import PluginManager

    try:
        storage = _get_storage()
        pm = PluginManager(storage.project_dir)
        sp = pm.get_site_packages()
        if not os.path.exists(sp):
            return []

        dists = list(importlib.metadata.distributions(paths=[sp]))
        plugins_found = []
        for dist in dists:
            for ep in dist.entry_points:
                if ep.group == "stepyard.plugins":
                    name = dist.metadata["Name"]
                    if incomplete in name:
                        plugins_found.append(CompletionItem(name))
                    break
        return plugins_found
    except Exception:  # noqa: BLE001 - completions must never crash the shell
        return []

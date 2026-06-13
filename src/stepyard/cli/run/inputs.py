"""
Pre-run input collection helpers.

These functions are invoked in the CLI process *before* the flow runner
subprocess is spawned, because the runner subprocess has stdin detached.
"""

from __future__ import annotations

import getpass
import os
from typing import TYPE_CHECKING

import click

from stepyard.cli.theme import C_MUTED, C_WARN, C_WHITE
from stepyard.cli.ui import console, print_error

if TYPE_CHECKING:
    from stepyard.core.flow import Flow


def iter_flow_steps(steps: list, parent_id: str | None = None):
    """Yield (step_id, step) pairs for all steps including nested groups."""
    for step in steps:
        step_id = f"{parent_id}.{step.id}" if parent_id else step.id
        yield step_id, step
        if getattr(step, "steps", None):
            yield from iter_flow_steps(step.steps, step_id)


def collect_pre_run_inputs(
    flow: Flow,
    project_dir: str,
    trigger_payload: dict | None,
    vars_dict: dict,
    non_interactive: bool,
    registry=None,
) -> dict[str, str]:
    """Collect plugin-declared pre-run inputs in the CLI process.

    Returns a mapping of ``env_key → value`` that the runner subprocess
    receives as environment variables.
    """
    if non_interactive:
        return {}

    env_values: dict[str, str] = {}
    context = {
        "steps": {},
        "trigger": {"payload": trigger_payload or {}},
        "vars": vars_dict,
        "env": dict(os.environ),
    }

    from stepyard.core.expressions import resolve_variables  # noqa: PLC0415
    from stepyard.sdk.inputs import InputRequest  # noqa: PLC0415

    if registry is None:
        from stepyard.plugin import discover_capabilities  # noqa: PLC0415

        registry = discover_capabilities(project_dir)

    for step_id, step in iter_flow_steps(flow.model.steps):
        if not step.uses:
            continue

        collector = registry.get_input_collector(step.uses)
        if collector is None:
            continue

        try:
            cfg = resolve_variables(step.with_config, context)
        except Exception as exc:
            print_error(
                f"Failed to prepare pre-run input for step '{step_id}': {exc}",
                hint=(
                    "Pre-run input prompts are collected before the runner subprocess starts. "
                    "Keep prompt/default/choices static or based only on vars, env, or trigger payload."
                ),
            )
            raise click.exceptions.Exit(1) from None

        requests = collector(step_id, step, cfg, context)
        if requests is None:
            continue
        if isinstance(requests, InputRequest):
            requests = [requests]

        for request in requests:
            value = ask_input_request(request)
            if value is None:
                print_error("Aborted by user")
                raise click.exceptions.Exit(1)
            if request.required and not str(value):
                print_error(f"Input for step '{request.step_id}' is required.")
                raise click.exceptions.Exit(1)

            env_values[request.env_key] = str(value)

    return env_values


def ask_input_request(request) -> str | None:
    """Prompt the user for a single :class:`~stepyard.sdk.inputs.InputRequest`."""
    try:
        if request.choices:
            return ask_choice_input(request)
        if request.secret:
            value = getpass.getpass(prompt_label(request.prompt, request.default))
            return value or request.default
        return (
            console.input(prompt_label(request.prompt, request.default, rich=True))
            or request.default
        )
    except (EOFError, KeyboardInterrupt):
        return None


def prompt_label(prompt: str, default: str = "", rich: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    if rich:
        return f"[bold {C_WHITE}]{prompt}[/bold {C_WHITE}][{C_MUTED}]{suffix}[/{C_MUTED}]: "
    return f"{prompt}{suffix}: "


def ask_choice_input(request) -> str | None:
    choices = [str(c) for c in request.choices]
    console.print(f"[bold {C_WHITE}]{request.prompt}[/bold {C_WHITE}]")
    for idx, choice in enumerate(choices, start=1):
        console.print(f"  [{C_MUTED}]{idx}.[/{C_MUTED}] {choice}")

    while True:
        raw = console.input(prompt_label("Choose", request.default, rich=True)).strip()
        if not raw and request.default:
            raw = request.default
        if not raw and not request.required:
            return ""
        if raw.isdigit() and 1 <= int(raw) <= len(choices):
            return choices[int(raw) - 1]
        if raw in choices:
            return raw
        console.print(
            f"[{C_WARN}]Enter a number from 1 to {len(choices)} or one of the listed values.[/{C_WARN}]"
        )


def input_request_from_step_inputs(step_id: str, inputs: dict) -> object:
    """Build an :class:`~stepyard.sdk.inputs.InputRequest` from raw step inputs dict."""
    from stepyard.sdk.inputs import InputRequest  # noqa: PLC0415

    choices = inputs.get("choices")
    if choices:
        choices = [str(c) for c in choices]

    return InputRequest(
        step_id=step_id,
        env_key="",
        prompt=str(inputs.get("prompt") or f"Input for {step_id}"),
        default=str(inputs.get("default") or ""),
        required=bool(inputs.get("required", True)),
        secret=bool(inputs.get("secret", False)),
        choices=choices,
    )


def flow_needs_runtime_human_input(flow: Flow) -> bool:
    """Return True when `human.input` steps may be visited more than once.

    In that case the CLI must use runtime input mode (STEPYARD_RUNTIME_HUMAN_INPUT=1)
    instead of pre-collecting inputs before the subprocess starts.
    """
    steps = list(flow.model.steps)
    human_step_ids = {step.id for step in steps if step.uses == "human.input"}
    if not human_step_ids:
        return False

    index_by_id = {step.id: idx for idx, step in enumerate(steps)}
    for idx, step in enumerate(steps):
        if step.uses == "human.input" and (
            getattr(step, "loop", None) is not None
            or getattr(step, "while_cond", None) is not None
            or (getattr(step, "max_visits", None) not in (None, 1))
        ):
            return True

        next_spec = getattr(step, "next_step", None)
        if next_spec is None:
            continue
        if isinstance(next_spec, dict):
            return True
        if isinstance(next_spec, str) and "${{" in next_spec:
            return True

        target = str(next_spec).strip()
        if target in human_step_ids and index_by_id[target] <= idx:
            return True

    return False

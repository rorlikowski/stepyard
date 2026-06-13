import os
import re
import sys
from typing import Any

from stepyard.sdk.inputs import InputRequest, input_collector
from stepyard.sdk.node import NodeContext, node


def human_input_env_key(step_id: str) -> str:
    safe_step_id = re.sub(r"[^A-Za-z0-9_]+", "_", step_id).upper()
    return f"STEPYARD_HUMAN_INPUT_{safe_step_id}"


@input_collector("human.input")
def collect_human_input(
    step_id: str, step: Any, config: dict[str, Any], context: dict[str, Any]
) -> InputRequest:
    choices = config.get("choices")
    if choices:
        choices = [str(choice) for choice in choices]

    return InputRequest(
        step_id=step_id,
        env_key=human_input_env_key(step_id),
        prompt=str(config.get("prompt") or f"Input for {step_id}"),
        default=str(config.get("default") or ""),
        required=bool(config.get("required", True)),
        secret=bool(config.get("secret", False)),
        choices=choices,
    )


@node(name="human.approval")
def human_approval(message: str) -> str:
    """Pauses the flow to wait for manual human approval.

    Args:
        message: The message to display to the human operator.

    Outputs:
        Returns a status string indicating the approval state.
    """
    return f"Waiting for approval: {message}"


@node(name="human.input")
def human_input(
    prompt: str,
    default: str = "",
    required: bool = True,
    secret: bool = False,
    choices: list[str] | None = None,
    ctx: NodeContext | None = None,
) -> str:
    """Prompts the operator for text input and returns the entered value.

    Args:
        prompt: The text shown to the operator.
        default: Value returned when the operator submits an empty answer.
        required: If true, an empty answer without a default raises an error.
        secret: If true, hides typed characters while collecting input.
        choices: Optional list of allowed answers.

    Outputs:
        Returns the selected or typed user input as a string.
    """
    if choices:
        choices = [str(choice) for choice in choices]

    env_value = None
    if ctx:
        for candidate_step_id in (ctx.step_id, ctx.step_id.split("#", 1)[0]):
            env_value = os.environ.get(human_input_env_key(candidate_step_id))
            if env_value is not None:
                break
    if env_value is not None:
        value = env_value
    elif not sys.stdin.isatty():
        if default:
            value = default
        elif required:
            raise RuntimeError("human.input requires an interactive terminal or a default value.")
        else:
            value = ""
    else:
        label = prompt
        if default:
            label = f"{label} [{default}]"

        if choices:
            print(label)
            for idx, choice in enumerate(choices, start=1):
                print(f"  {idx}. {choice}")
            raw_value = input("> ").strip()
            if raw_value.isdigit() and 1 <= int(raw_value) <= len(choices):
                value = choices[int(raw_value) - 1]
            else:
                value = raw_value or default
        elif secret:
            import getpass

            value = getpass.getpass(f"{label}: ") or default
        else:
            value = input(f"{label}: ").strip() or default

    if required and not value:
        raise ValueError("human.input received an empty value.")
    if choices and value not in choices:
        raise ValueError(f"human.input expected one of: {', '.join(choices)}")
    return value


@node(name="flow.route")
def flow_route(
    target: str, payload: dict[str, Any] | None = None, reason: str = ""
) -> dict[str, Any]:
    """Builds a routing handoff object pointing to a target step id.

    Args:
        target: Target step identifier, for example `execute_handoff_target`.
        payload: Data to pass to the target in the next step.
        reason: Optional human-readable reason for the handoff.

    Outputs:
        routed: True when the route object was created.
        target: Target step identifier.
        payload: Data to pass to the target.
        reason: Human-readable reason.
    """
    normalized_target = str(target).strip()
    if not normalized_target:
        raise ValueError("flow.route target cannot be empty.")

    return {
        "routed": True,
        "target": normalized_target,
        "payload": payload or {},
        "reason": reason,
    }


@node(name="system.if")
def system_if(
    condition: bool,
    true_value: str = "true",
    false_value: str = "false",
    fail_on_false: bool = False,
) -> str:
    """Evaluates a logical condition.

    Args:
        condition: The condition to evaluate.
        true_value: Value to return if condition is true.
        false_value: Value to return if condition is false.
        fail_on_false: If true, raises an error when the condition is false.

    Outputs:
        Returns the evaluated true_value or false_value.
    """
    if str(condition).lower() in ("true", "1", "yes", "y"):
        condition = True
    elif str(condition).lower() in ("false", "0", "no", "n"):
        condition = False

    if condition:
        return true_value
    if fail_on_false:
        raise ValueError(f"Condition was false. (Value: {false_value})")
    return false_value


__all__ = [
    "collect_human_input",
    "flow_route",
    "human_approval",
    "human_input",
    "human_input_env_key",
    "system_if",
]

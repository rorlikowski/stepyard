"""
Stepyard flow specification - Pydantic models and YAML loading.

This module is intentionally small: it owns only the Pydantic schema for
``flow.yaml`` files and the ``Flow`` loader.  All expression evaluation
logic lives in ``core.expressions`` and can be imported independently.
"""

from __future__ import annotations

import os
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ─── Pydantic schema ──────────────────────────────────────────────────────────


class TriggerModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    uses: str
    with_config: dict[str, Any] = Field(default_factory=dict, alias="with")
    mode: Literal["daemon", "console"] = "daemon"


class RetryModel(BaseModel):
    attempts: int = 3
    backoff_factor: float = 2.0
    initial_delay: float = 1.0


class StepModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    uses: str | None = None
    steps: list[StepModel] | None = None
    with_config: dict[str, Any] = Field(default_factory=dict, alias="with")
    if_cond: str | None = Field(default=None, alias="if")
    loop: str | list[Any] | None = None
    while_cond: str | bool | None = Field(default=None, alias="while")
    next_step: str | dict[str, Any] | None = Field(default=None, alias="next")
    max_visits: int | None = None
    timeout: int | str | None = None
    retry: int | RetryModel | None = None
    continue_on_error: bool = False
    approval: bool = False

    @field_validator("max_visits")
    @classmethod
    def validate_max_visits(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("max_visits must be zero or greater.")
        return value

    @model_validator(mode="after")
    def check_uses_or_steps(self) -> StepModel:
        if self.uses is None and self.steps is None:
            raise ValueError(f"Step '{self.id}' must have either 'uses' or 'steps'")
        if self.uses is not None and self.steps is not None:
            raise ValueError(f"Step '{self.id}' cannot have both 'uses' and 'steps'")
        return self


class FlowModel(BaseModel):
    name: str
    description: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    dotenv: list[str] = Field(default_factory=list)
    trigger: TriggerModel | None = None
    steps: list[StepModel]

    @field_validator("dotenv", mode="before")
    @classmethod
    def normalize_dotenv(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        if isinstance(v, list):
            return [str(x) for x in v]
        raise ValueError("'dotenv' must be a string or a list of strings.")

    @field_validator("env", mode="before")
    @classmethod
    def coerce_env_values(cls, env: Any) -> dict[str, str]:
        if env is None:
            return {}
        if not isinstance(env, dict):
            raise ValueError("'env' must be a mapping of name -> value.")
        out: dict[str, str] = {}
        for k, v in env.items():
            if isinstance(v, (dict, list)):
                raise ValueError(
                    f"env['{k}'] must be a scalar value (string, int, float, or bool)."
                )
            if v is True:
                out[str(k)] = "true"
            elif v is False:
                out[str(k)] = "false"
            else:
                out[str(k)] = str(v)
        return out

    @field_validator("steps")
    @classmethod
    def validate_steps(cls, steps: list[StepModel]) -> list[StepModel]:
        if not steps:
            raise ValueError("Flow must have at least one step.")
        ids = [s.id for s in steps]
        if len(ids) != len(set(ids)):
            raise ValueError("Step IDs must be unique.")
        return steps


# ─── Flow loader ──────────────────────────────────────────────────────────────


class Flow:
    """Parsed and validated representation of a flow YAML file."""

    def __init__(self, model: FlowModel, raw_yaml: str) -> None:
        self.model = model
        self.raw_yaml = raw_yaml

    @classmethod
    def from_yaml(cls, yaml_content: str) -> Flow:
        """Load and validate a Flow from a YAML string."""
        try:
            parsed = yaml.safe_load(yaml_content)
            model = FlowModel.model_validate(parsed)
            return cls(model, yaml_content)
        except Exception as exc:
            raise ValueError(f"Invalid Flow Spec YAML format: {exc}") from exc

    @classmethod
    def from_file(cls, filepath: str) -> Flow:
        """Load a Flow from a YAML file on disk."""
        with open(filepath, encoding="utf-8") as fh:
            return cls.from_yaml(fh.read())


# ─── Flow resolver ────────────────────────────────────────────────────────────


class FlowResolver:
    """Resolves flow names to YAML file paths.

    Single canonical implementation - replaces duplicated logic in
    Scheduler, StepyardService, and SchedulerDaemon.
    """

    def __init__(self, project_dir: str) -> None:
        self.project_dir = os.path.abspath(project_dir)
        env_flows_dir = os.environ.get("STEPYARD_FLOWS_DIR")
        if env_flows_dir:
            self.flows_dir = os.path.abspath(env_flows_dir)
        else:
            self.flows_dir = os.path.join(self.project_dir, "flows")

    def find(self, flow_name: str) -> str | None:
        """Resolve a flow name → YAML file path, or None if not found.

        Pass 1: exact filename match (e.g. ``demo`` → ``flows/demo.yaml``).
        Pass 2: match the ``name:`` field inside each YAML file.
        """
        if not os.path.isdir(self.flows_dir):
            return None

        # Pass 1: exact filename match
        for fn in os.listdir(self.flows_dir):
            if fn.rsplit(".", 1)[0] == flow_name:
                return os.path.join(self.flows_dir, fn)

        # Pass 2: check YAML content for matching name
        for fn in os.listdir(self.flows_dir):
            if fn.endswith((".yaml", ".yml")):
                path = os.path.join(self.flows_dir, fn)
                try:
                    with open(path, encoding="utf-8") as f:
                        data = yaml.safe_load(f)
                    if data and data.get("name") == flow_name:
                        return path
                except Exception:  # noqa: BLE001 - skip malformed YAML files during scan
                    pass

        return None

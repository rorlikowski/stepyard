"""
Tests for the top-level env: block and dotenv: file loading in flow YAML.

Covers:
- FlowModel schema: parsing, string coercion, validation errors, dotenv normalisation
- Engine: expression context (${{ env.X }}), OS env vars visible to
  shell.run subprocesses, OS-env-wins precedence, and os.environ cleanup.
- dotenv: single file, multiple files (first-wins), env: overrides dotenv,
  OS env beats both, missing file logs a warning (run continues).
"""

from __future__ import annotations

import os

import pytest

from stepyard.core.flow import Flow, FlowModel
from stepyard.core.service import Engine
from stepyard.storage.facade import Storage

# ── Schema tests ──────────────────────────────────────────────────────────────


def test_flow_model_env_defaults_to_empty():
    flow = Flow.from_yaml(
        """
        name: no-env
        steps:
          - id: s
            uses: shell.run
            with:
              command: echo hi
        """
    )
    assert flow.model.env == {}


def test_flow_model_env_parsed():
    flow = Flow.from_yaml(
        """
        name: with-env
        env:
          GREETING: hello
          LOG_LEVEL: info
        steps:
          - id: s
            uses: shell.run
            with:
              command: echo hi
        """
    )
    assert flow.model.env == {"GREETING": "hello", "LOG_LEVEL": "info"}


def test_flow_model_env_coerces_int_to_string():
    flow = Flow.from_yaml(
        """
        name: coerce-int
        env:
          RETRIES: 3
          PORT: 8080
        steps:
          - id: s
            uses: shell.run
            with:
              command: echo hi
        """
    )
    assert flow.model.env["RETRIES"] == "3"
    assert flow.model.env["PORT"] == "8080"


def test_flow_model_env_coerces_bool_to_string():
    flow = Flow.from_yaml(
        """
        name: coerce-bool
        env:
          DEBUG: true
          VERBOSE: false
        steps:
          - id: s
            uses: shell.run
            with:
              command: echo hi
        """
    )
    assert flow.model.env["DEBUG"] == "true"
    assert flow.model.env["VERBOSE"] == "false"


def test_flow_model_env_coerces_float_to_string():
    flow = Flow.from_yaml(
        """
        name: coerce-float
        env:
          THRESHOLD: 0.95
        steps:
          - id: s
            uses: shell.run
            with:
              command: echo hi
        """
    )
    assert flow.model.env["THRESHOLD"] == "0.95"


def test_flow_model_env_rejects_nested_dict():
    with pytest.raises(ValueError, match="scalar"):
        FlowModel.model_validate(
            {
                "name": "bad",
                "env": {"NESTED": {"key": "value"}},
                "steps": [{"id": "s", "uses": "shell.run"}],
            }
        )


def test_flow_model_env_rejects_list_value():
    with pytest.raises(ValueError, match="scalar"):
        FlowModel.model_validate(
            {
                "name": "bad",
                "env": {"ITEMS": [1, 2, 3]},
                "steps": [{"id": "s", "uses": "shell.run"}],
            }
        )


def test_flow_model_env_rejects_non_mapping():
    with pytest.raises(ValueError):
        FlowModel.model_validate(
            {
                "name": "bad",
                "env": "not-a-dict",
                "steps": [{"id": "s", "uses": "shell.run"}],
            }
        )


# ── Engine tests ──────────────────────────────────────────────────────────────


@pytest.fixture()
def storage(tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    return Storage(str(project_dir))


@pytest.mark.asyncio
async def test_env_block_visible_in_expression_context(storage):
    """${{ env.NAME }} resolves to the declared value."""
    flow = Flow.from_yaml(
        """
        name: env-expr
        env:
          MY_VAR: hello-from-env
        steps:
          - id: check
            uses: shell.run
            with:
              command: echo ${{ env.MY_VAR }}
        """
    )
    engine = Engine(storage)
    storage.create_run("run-env-expr", flow.model.name)
    await engine.execute_run("run-env-expr", flow)

    run = storage.get_run("run-env-expr")
    assert run["status"] == "completed"

    steps = {s["step_id"]: s for s in storage.get_step_runs("run-env-expr")}
    assert "hello-from-env" in steps["check"]["output"]


@pytest.mark.asyncio
async def test_env_block_visible_as_os_env_in_subprocess(storage):
    """Declared env values are real OS env vars available in shell.run subprocesses.

    Uses `printenv VARNAME` so no shell-expansion is needed - printenv reads
    the value directly from the subprocess environment.
    """
    flow = Flow.from_yaml(
        """
        name: env-subprocess
        env:
          STEPYARD_TEST_GREETING: hi-from-flow
        steps:
          - id: greet
            uses: shell.run
            with:
              command: printenv STEPYARD_TEST_GREETING
        """
    )
    engine = Engine(storage)
    storage.create_run("run-env-sub", flow.model.name)
    await engine.execute_run("run-env-sub", flow)

    run = storage.get_run("run-env-sub")
    assert run["status"] == "completed"

    steps = {s["step_id"]: s for s in storage.get_step_runs("run-env-sub")}
    assert "hi-from-flow" in steps["greet"]["output"]


@pytest.mark.asyncio
async def test_env_block_os_env_wins_over_flow_declaration(storage):
    """An already-set OS env var is NOT overwritten by the flow env: block."""
    key = "STEPYARD_TEST_PRECEDENCE"
    os.environ[key] = "from-os"
    try:
        flow = Flow.from_yaml(
            f"""
            name: env-precedence
            env:
              {key}: from-flow
            steps:
              - id: read
                uses: shell.run
                with:
                  command: printenv {key}
            """
        )
        engine = Engine(storage)
        storage.create_run("run-env-prec", flow.model.name)
        await engine.execute_run("run-env-prec", flow)

        steps = {s["step_id"]: s for s in storage.get_step_runs("run-env-prec")}
        assert "from-os" in steps["read"]["output"]
        assert "from-flow" not in steps["read"]["output"]
    finally:
        os.environ.pop(key, None)


@pytest.mark.asyncio
async def test_env_block_os_environ_restored_after_run(storage):
    """Keys added from flow env: are removed from os.environ after the run."""
    key = "STEPYARD_TEST_CLEANUP"
    assert key not in os.environ, "precondition: key must not already be set"

    flow = Flow.from_yaml(
        f"""
        name: env-cleanup
        env:
          {key}: temporary-value
        steps:
          - id: s
            uses: shell.run
            with:
              command: echo done
        """
    )
    engine = Engine(storage)
    storage.create_run("run-env-cleanup", flow.model.name)
    await engine.execute_run("run-env-cleanup", flow)

    assert key not in os.environ, "flow-declared env key must be cleaned up from os.environ"


@pytest.mark.asyncio
async def test_env_block_used_in_if_condition(storage):
    """${{ env.X }} works inside an if: condition."""
    flow = Flow.from_yaml(
        """
        name: env-if
        env:
          RUN_STEP: "yes"
        steps:
          - id: conditional
            if: "${{ env.RUN_STEP == 'yes' }}"
            uses: shell.run
            with:
              command: echo ran
          - id: always
            uses: shell.run
            with:
              command: echo always
        """
    )
    engine = Engine(storage)
    storage.create_run("run-env-if", flow.model.name)
    await engine.execute_run("run-env-if", flow)

    run = storage.get_run("run-env-if")
    assert run["status"] == "completed"

    steps = {s["step_id"]: s for s in storage.get_step_runs("run-env-if")}
    assert steps["conditional"]["status"] == "completed"
    assert "ran" in steps["conditional"]["output"]


# ── dotenv: schema tests ──────────────────────────────────────────────────────


def test_dotenv_defaults_to_empty_list():
    flow = Flow.from_yaml(
        """
        name: no-dotenv
        steps:
          - id: s
            uses: shell.run
            with:
              command: echo hi
        """
    )
    assert flow.model.dotenv == []


def test_dotenv_string_normalised_to_list():
    flow = Flow.from_yaml(
        """
        name: dotenv-str
        dotenv: .env
        steps:
          - id: s
            uses: shell.run
            with:
              command: echo hi
        """
    )
    assert flow.model.dotenv == [".env"]


def test_dotenv_list_kept_as_list():
    flow = Flow.from_yaml(
        """
        name: dotenv-list
        dotenv:
          - .env.local
          - .env
        steps:
          - id: s
            uses: shell.run
            with:
              command: echo hi
        """
    )
    assert flow.model.dotenv == [".env.local", ".env"]


def test_dotenv_rejects_non_string_non_list():
    with pytest.raises(ValueError):
        FlowModel.model_validate(
            {
                "name": "bad",
                "dotenv": {"file": ".env"},
                "steps": [{"id": "s", "uses": "shell.run"}],
            }
        )


# ── dotenv: engine tests ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dotenv_file_values_visible_in_expression_context(storage, tmp_path):
    """Values from a dotenv file are available as ${{ env.NAME }}."""
    dotenv_file = tmp_path / "project" / ".env.test"
    dotenv_file.write_text("STEPYARD_DOTENV_VAR=loaded-from-file\n")

    flow = Flow.from_yaml(
        """
        name: dotenv-expr
        dotenv: .env.test
        steps:
          - id: check
            uses: shell.run
            with:
              command: echo ${{ env.STEPYARD_DOTENV_VAR }}
        """
    )
    engine = Engine(storage)
    storage.create_run("run-dotenv-expr", flow.model.name)
    await engine.execute_run("run-dotenv-expr", flow)

    run = storage.get_run("run-dotenv-expr")
    assert run["status"] == "completed"

    steps = {s["step_id"]: s for s in storage.get_step_runs("run-dotenv-expr")}
    assert "loaded-from-file" in steps["check"]["output"]


@pytest.mark.asyncio
async def test_dotenv_inline_env_overrides_dotenv_file(storage, tmp_path):
    """Explicit env: values override values from dotenv: files."""
    dotenv_file = tmp_path / "project" / ".env.test"
    dotenv_file.write_text("STEPYARD_OVERRIDE_VAR=from-file\n")

    flow = Flow.from_yaml(
        """
        name: dotenv-override
        dotenv: .env.test
        env:
          STEPYARD_OVERRIDE_VAR: from-inline
        steps:
          - id: check
            uses: shell.run
            with:
              command: echo ${{ env.STEPYARD_OVERRIDE_VAR }}
        """
    )
    engine = Engine(storage)
    storage.create_run("run-dotenv-override", flow.model.name)
    await engine.execute_run("run-dotenv-override", flow)

    steps = {s["step_id"]: s for s in storage.get_step_runs("run-dotenv-override")}
    assert "from-inline" in steps["check"]["output"]
    assert "from-file" not in steps["check"]["output"]


@pytest.mark.asyncio
async def test_dotenv_os_env_wins_over_dotenv_file(storage, tmp_path):
    """An already-set OS env var beats a dotenv file value."""
    key = "STEPYARD_DOTENV_OS_WIN"
    dotenv_file = tmp_path / "project" / ".env.test"
    dotenv_file.write_text(f"{key}=from-file\n")

    os.environ[key] = "from-os"
    try:
        flow = Flow.from_yaml(
            """
            name: dotenv-os-wins
            dotenv: .env.test
            steps:
              - id: check
                uses: shell.run
                with:
                  command: echo ${{ env.STEPYARD_DOTENV_OS_WIN }}
            """
        )
        engine = Engine(storage)
        storage.create_run("run-dotenv-os", flow.model.name)
        await engine.execute_run("run-dotenv-os", flow)

        steps = {s["step_id"]: s for s in storage.get_step_runs("run-dotenv-os")}
        assert "from-os" in steps["check"]["output"]
        assert "from-file" not in steps["check"]["output"]
    finally:
        os.environ.pop(key, None)


@pytest.mark.asyncio
async def test_dotenv_multiple_files_first_file_wins(storage, tmp_path):
    """When the same key appears in multiple dotenv files, first file wins."""
    project_dir = tmp_path / "project"
    (project_dir / ".env.first").write_text("STEPYARD_MULTI_VAR=first\n")
    (project_dir / ".env.second").write_text("STEPYARD_MULTI_VAR=second\n")

    flow = Flow.from_yaml(
        """
        name: dotenv-multi
        dotenv:
          - .env.first
          - .env.second
        steps:
          - id: check
            uses: shell.run
            with:
              command: echo ${{ env.STEPYARD_MULTI_VAR }}
        """
    )
    engine = Engine(storage)
    storage.create_run("run-dotenv-multi", flow.model.name)
    await engine.execute_run("run-dotenv-multi", flow)

    steps = {s["step_id"]: s for s in storage.get_step_runs("run-dotenv-multi")}
    assert "first" in steps["check"]["output"]
    assert "second" not in steps["check"]["output"]


@pytest.mark.asyncio
async def test_dotenv_missing_file_run_continues(storage):
    """A missing dotenv file logs a warning but the run completes normally."""
    flow = Flow.from_yaml(
        """
        name: dotenv-missing
        dotenv: this-file-does-not-exist.env
        steps:
          - id: ok
            uses: shell.run
            with:
              command: echo still-runs
        """
    )
    engine = Engine(storage)
    storage.create_run("run-dotenv-missing", flow.model.name)
    await engine.execute_run("run-dotenv-missing", flow)

    run = storage.get_run("run-dotenv-missing")
    assert run["status"] == "completed"

    steps = {s["step_id"]: s for s in storage.get_step_runs("run-dotenv-missing")}
    assert "still-runs" in steps["ok"]["output"]


@pytest.mark.asyncio
async def test_dotenv_ignores_comments_and_blank_lines(storage, tmp_path):
    """dotenv parser skips comment lines and blank lines."""
    dotenv_file = tmp_path / "project" / ".env.test"
    dotenv_file.write_text(
        "# This is a comment\n\nSTEPYARD_DOTENV_COMMENT_VAR=real-value\n# Another comment\n"
    )

    flow = Flow.from_yaml(
        """
        name: dotenv-comments
        dotenv: .env.test
        steps:
          - id: check
            uses: shell.run
            with:
              command: echo ${{ env.STEPYARD_DOTENV_COMMENT_VAR }}
        """
    )
    engine = Engine(storage)
    storage.create_run("run-dotenv-comments", flow.model.name)
    await engine.execute_run("run-dotenv-comments", flow)

    steps = {s["step_id"]: s for s in storage.get_step_runs("run-dotenv-comments")}
    assert "real-value" in steps["check"]["output"]


@pytest.mark.asyncio
async def test_dotenv_strips_quotes(storage, tmp_path):
    """dotenv parser strips surrounding single and double quotes from values."""
    dotenv_file = tmp_path / "project" / ".env.test"
    dotenv_file.write_text(
        "STEPYARD_QUOTED_DOUBLE=\"double-quoted\"\nSTEPYARD_QUOTED_SINGLE='single-quoted'\n"
    )

    flow = Flow.from_yaml(
        """
        name: dotenv-quotes
        dotenv: .env.test
        steps:
          - id: check
            uses: shell.run
            with:
              command: echo "${{ env.STEPYARD_QUOTED_DOUBLE }} ${{ env.STEPYARD_QUOTED_SINGLE }}"
        """
    )
    engine = Engine(storage)
    storage.create_run("run-dotenv-quotes", flow.model.name)
    await engine.execute_run("run-dotenv-quotes", flow)

    steps = {s["step_id"]: s for s in storage.get_step_runs("run-dotenv-quotes")}
    assert "double-quoted" in steps["check"]["output"]
    assert "single-quoted" in steps["check"]["output"]

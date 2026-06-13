import pytest
from click.testing import CliRunner

from stepyard.cli import cli
from stepyard.cli.commands.run import _flow_needs_runtime_human_input, _parse_run_vars
from stepyard.core.flow import Flow


@pytest.fixture
def clean_project_env(tmp_path, monkeypatch):
    """Sets current working directory and mocks project root to a temporary folder."""
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)
    return project_dir


def test_cli_help():
    runner = CliRunner()
    res = runner.invoke(cli, ["--help"])
    assert res.exit_code == 0
    assert "Effortless automation launcher" in res.output


def test_cli_doctor(clean_project_env):
    runner = CliRunner()
    res = runner.invoke(cli, ["doctor"])
    assert res.exit_code == 0
    # Doctor now shows per-check lines + success/warning summary
    assert "diagnostics passed" in res.output.lower() or "checks failed" in res.output.lower()


def test_runtime_human_input_is_required_for_graph_reentry():
    flow = Flow.from_yaml("""
    name: input-loop
    steps:
      - id: ask
        uses: human.input
        next: send
      - id: send
        uses: shell.run
        next: "${{ 'ask' if visits.send < 2 else 'end' }}"
    """)

    assert _flow_needs_runtime_human_input(flow) is True


def test_single_human_input_can_use_pre_run_collection():
    flow = Flow.from_yaml("""
    name: single-input
    steps:
      - id: ask
        uses: human.input
      - id: send
        uses: shell.run
    """)

    assert _flow_needs_runtime_human_input(flow) is False


def test_parse_run_vars_merges_env_file_and_cli_overrides(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        """
        # ignored
        name = "from-file"
        enabled=true
        """,
        encoding="utf-8",
    )

    vars_dict = _parse_run_vars(("name=from-cli", "flag"), str(env_file))

    assert vars_dict == {
        "name": "from-cli",
        "enabled": "true",
        "flag": True,
    }

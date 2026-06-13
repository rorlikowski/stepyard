"""
CLI integration tests using Click's CliRunner.

These tests invoke CLI commands in-process without a real subprocess, so
they run fast and don't require a running scheduler daemon.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from stepyard.cli import cli


@pytest.fixture()
def project(tmp_path, monkeypatch):
    """Create a minimal project and cd into it."""
    flows_dir = tmp_path / "flows"
    flows_dir.mkdir()
    (flows_dir / "hello.yaml").write_text(
        "name: hello\nsteps:\n  - id: greet\n    uses: shell.run\n    with:\n      command: echo hi\n"
    )
    monkeypatch.chdir(tmp_path)
    # Initialise storage
    from stepyard.storage.facade import Storage

    Storage(str(tmp_path))
    return tmp_path


def invoke(args, **kwargs):
    runner = CliRunner()
    return runner.invoke(cli, args, catch_exceptions=False, **kwargs)


# ── init ─────────────────────────────────────────────────────────────────────


def test_init_creates_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = invoke(["init", str(tmp_path), "--force"])
    assert result.exit_code == 0
    assert (tmp_path / "flows" / "hello.yaml").exists()


def test_init_skips_existing_files(project):
    existing_content = (project / "flows" / "hello.yaml").read_text()
    result = invoke(["init", str(project)])
    assert result.exit_code == 0
    # File should not be overwritten.
    assert (project / "flows" / "hello.yaml").read_text() == existing_content


# ── validate ─────────────────────────────────────────────────────────────────


def test_validate_valid_flow(project):
    flow_file = str(project / "flows" / "hello.yaml")
    result = invoke(["validate", flow_file])
    assert result.exit_code == 0
    assert "✓" in result.output


def test_validate_invalid_flow(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from stepyard.storage.facade import Storage

    Storage(str(tmp_path))
    bad_flow = tmp_path / "flows" / "bad.yaml"
    bad_flow.parent.mkdir(parents=True)
    bad_flow.write_text("name: bad\nsteps: []\n")  # empty steps - invalid

    result = invoke(["validate", str(bad_flow)])
    assert result.exit_code == 1
    assert "✗" in result.output


# ── schema ───────────────────────────────────────────────────────────────────


def test_schema_creates_file(project):
    result = invoke(["schema"])
    assert result.exit_code == 0
    schema_file = project / ".stepyard" / "flow.schema.json"
    assert schema_file.exists()
    import json

    data = json.loads(schema_file.read_text())
    assert "properties" in data


# ── clear ────────────────────────────────────────────────────────────────────


def test_clear_with_force(project):
    from stepyard.storage.facade import Storage

    storage = Storage(str(project))
    storage.create_run("r-001", "hello")

    result = invoke(["clear", "--force"])
    assert result.exit_code == 0
    assert storage.list_recent_runs() == []

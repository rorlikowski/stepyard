import os
import shutil
import sys
from pathlib import Path

import pytest

from stepyard.plugin import PluginManager


@pytest.fixture
def temp_project(tmp_path):
    project_dir = tmp_path / "my_project"
    project_dir.mkdir()
    yield project_dir
    shutil.rmtree(project_dir, ignore_errors=True)


def test_init_plugin_template(temp_project):
    mgr = PluginManager(str(temp_project))
    template_dir = temp_project / "my_plugin"

    mgr.init_plugin_template("my_plugin", str(template_dir))

    assert os.path.exists(template_dir / "pyproject.toml")
    assert os.path.exists(template_dir / "my_plugin" / "nodes.py")
    assert os.path.exists(template_dir / "my_plugin" / "triggers.py")
    assert os.path.exists(template_dir / "my_plugin" / "hooks.py")
    assert os.path.exists(template_dir / "my_plugin" / "inputs.py")
    assert os.path.exists(template_dir / "tests" / "test_nodes.py")

    with open(template_dir / "my_plugin" / "nodes.py", encoding="utf-8") as f:
        content = f.read()
        assert "sample.greet" in content


def test_init_plugin_template_sanitizes_package_name(temp_project):
    mgr = PluginManager(str(temp_project))
    template_dir = temp_project / "stepyard-plugin-sample"

    mgr.init_plugin_template("stepyard-plugin-sample", str(template_dir))

    assert os.path.exists(template_dir / "stepyard_plugin_sample" / "nodes.py")
    assert not os.path.exists(template_dir / "stepyard-plugin-sample" / "nodes.py")

    with open(template_dir / "pyproject.toml", encoding="utf-8") as f:
        content = f.read()
        assert 'stepyard_plugin_sample = "stepyard_plugin_sample.nodes"' in content


def test_discovery_loads_system_plugin(temp_project):
    from stepyard.plugin import discover_capabilities

    registry = discover_capabilities(str(temp_project))

    assert registry.get_node("shell.run") is not None
    assert registry.get_node("human.input") is not None
    assert registry.get_trigger("cron") is not None
    assert registry.get_input_collector("human.input") is not None
    assert registry.hooks


def test_system_capabilities_are_loaded_from_entry_points(temp_project):
    from stepyard.plugin import discover_capabilities

    registry = discover_capabilities(str(temp_project))

    shell_info = registry.get_node_info("shell.run")
    cron_info = registry.get_trigger_info("cron")

    assert shell_info is not None
    assert shell_info.source == "stepyard.plugins:shell -> stepyard_builtin.shell"
    assert shell_info.isolated is False
    assert cron_info is not None
    assert cron_info.source == "stepyard.triggers:builtin -> stepyard_builtin.triggers"


def test_plugin_host_has_no_builtin_special_import():
    import inspect

    import stepyard.plugins.host as host

    source = inspect.getsource(host.PluginHost)

    assert "stepyard.builtin_plugin" not in source
    assert "stepyard.nodes." not in source
    assert "refresh_from_legacy_registries" not in source


def test_legacy_core_public_shims_are_removed():
    repo_root = Path(__file__).resolve().parents[2]

    assert not (repo_root / "src" / "stepyard" / "core" / "registry.py").exists()
    assert not (repo_root / "src" / "stepyard" / "core" / "plugin.py").exists()
    assert not (repo_root / "src" / "stepyard" / "core" / "storage.py").exists()


def test_sdk_decorators_do_not_use_global_registries():
    import inspect

    import stepyard.sdk.inputs as inputs
    import stepyard.sdk.node as node_sdk
    import stepyard.sdk.trigger as trigger_sdk

    combined = "\n".join(
        [
            inspect.getsource(node_sdk),
            inspect.getsource(trigger_sdk),
            inspect.getsource(inputs),
        ]
    )

    assert "_nodes" not in combined
    assert "_triggers" not in combined
    assert "_input_collectors" not in combined


@pytest.mark.asyncio
async def test_external_plugin_node_runs_in_subprocess(temp_project):
    from stepyard.plugin import NodeInvocationService, discover_capabilities
    from stepyard.sdk.node import NodeContext

    mgr = PluginManager(str(temp_project))
    _create_fake_plugin_env(
        mgr,
        package="stepyard_plugin_external",
        dist_name="stepyard-plugin-external",
        body="""
from stepyard.sdk.node import node


@node(name="external.echo")
def echo(value: int):
    return {"value": value + 1}
""",
    )

    registry = discover_capabilities(str(temp_project))
    info = registry.get_node_info("external.echo")

    assert info is not None
    assert info.isolated is True
    assert info.python_executable == mgr.venv_python

    invoker = NodeInvocationService(registry, str(temp_project))
    result = await invoker.invoke(
        "external.echo",
        {"value": "2"},
        "run-subprocess",
        "echo",
        NodeContext(run_id="run-subprocess", step_id="echo"),
    )

    assert result.status == "success"
    assert result.output == {"value": 3}


def test_duplicate_capability_conflict_is_reported(temp_project):
    from stepyard.plugin import discover_capabilities

    mgr = PluginManager(str(temp_project))
    _create_fake_plugin_env(
        mgr,
        package="stepyard_plugin_dup_one",
        dist_name="stepyard-plugin-dup-one",
        entry_name="dup_one",
        body="""
from stepyard.sdk.node import node


@node(name="duplicate.node")
def first():
    return "first"
""",
    )
    _create_fake_plugin_env(
        mgr,
        package="stepyard_plugin_dup_two",
        dist_name="stepyard-plugin-dup-two",
        entry_name="dup_two",
        body="""
from stepyard.sdk.node import node


@node(name="duplicate.node")
def second():
    return "second"
""",
    )

    from stepyard.core.errors import PluginError

    with pytest.raises(PluginError, match="Duplicate node capability 'duplicate.node'"):
        discover_capabilities(str(temp_project))


def test_ensure_env(temp_project):
    mgr = PluginManager(str(temp_project))
    venv_python = mgr.ensure_env()

    assert os.path.exists(venv_python)
    assert os.path.isdir(mgr.env_dir)


def _create_fake_plugin_env(
    mgr: PluginManager,
    *,
    package: str,
    dist_name: str,
    body: str,
    entry_name: str = "external",
) -> None:
    site_packages = mgr.get_site_packages()
    os.makedirs(site_packages, exist_ok=True)
    os.makedirs(os.path.dirname(mgr.venv_python), exist_ok=True)
    with open(os.path.join(mgr.env_dir, "pyvenv.cfg"), "w", encoding="utf-8") as f:
        f.write("include-system-site-packages = false\n")
    if not os.path.exists(mgr.venv_python):
        try:
            os.symlink(sys.executable, mgr.venv_python)
        except OSError:
            shutil.copy(sys.executable, mgr.venv_python)
    repo_src = Path(__file__).resolve().parents[2] / "src"
    with open(os.path.join(site_packages, "stepyard-editable.pth"), "w", encoding="utf-8") as f:
        f.write(str(repo_src) + "\n")
        for entry in sys.path:
            if "site-packages" in entry and os.path.isdir(entry):
                f.write(entry + "\n")

    package_dir = os.path.join(site_packages, package)
    os.makedirs(package_dir, exist_ok=True)
    with open(os.path.join(package_dir, "__init__.py"), "w", encoding="utf-8") as f:
        f.write("")
    with open(os.path.join(package_dir, "nodes.py"), "w", encoding="utf-8") as f:
        f.write(body.strip() + "\n")

    dist_info = os.path.join(site_packages, f"{dist_name}-0.1.0.dist-info")
    os.makedirs(dist_info, exist_ok=True)
    with open(os.path.join(dist_info, "METADATA"), "w", encoding="utf-8") as f:
        f.write(f"Name: {dist_name}\nVersion: 0.1.0\n")
    with open(os.path.join(dist_info, "entry_points.txt"), "w", encoding="utf-8") as f:
        f.write(f"[stepyard.plugins]\n{entry_name} = {package}.nodes\n")

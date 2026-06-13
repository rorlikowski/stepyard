# How to write and test a plugin

This guide covers every aspect of plugin development: scaffolding, writing nodes, testing, async support, and publishing.

For a step-by-step beginner walkthrough, see the [Tutorial: Your First Plugin](../getting-started/first-plugin.md).

---

## Scaffold

```bash
stepyard plugin init my-plugin-name ./my-plugin-name
```

Generates:

```
my-plugin-name/
├── pyproject.toml
├── README.md
├── src/
│   └── my_plugin_name/
│       ├── __init__.py
│       └── nodes.py
└── tests/
    └── test_nodes.py
```

---

## Writing a node

```python
from stepyard.sdk import node, NodeResult


@node(name="myservice.action")
def my_action(
    required_param: str,
    optional_param: int = 10,
    flag: bool = False,
) -> NodeResult:
    """One-line summary.

    Longer description shown in `stepyard tools list`.
    """
    result = do_the_work(required_param, optional_param, flag)

    return NodeResult(
        status="success",
        output={
            "value": result,
            "count": len(result),
        },
    )
```

**Key rules:**

- Return a `NodeResult` (or a plain `dict` - Stepyard wraps it automatically).
- Raise `TransientError` for retriable failures, any other exception for permanent failures.
- Type hints are mandatory - Stepyard generates a Pydantic model from them.

### Async nodes

For I/O-bound work (HTTP calls, database queries), use `async def`:

```python
import httpx
from stepyard.sdk import node, NodeResult


@node(name="myservice.fetch")
async def fetch(url: str, timeout: int = 30) -> NodeResult:
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, timeout=timeout)
        resp.raise_for_status()

    return NodeResult(status="success", output={"body": resp.json()})
```

Stepyard handles the event loop - just write `async def` and return normally.

### Using NodeContext

Inject `NodeContext` as the first parameter to get access to logging, the run ID, and the step ID:

```python
from stepyard.sdk import node, NodeContext, NodeResult


@node(name="myservice.action")
def action_with_context(ctx: NodeContext, param: str) -> NodeResult:
    ctx.log.info("Running %s in run %s", ctx.step_id, ctx.run_id)
    result = do_work(param)
    return NodeResult(status="success", output={"result": result})
```

`ctx.log` is a standard Python `logging.Logger`.

---

## Input types

Stepyard translates type hints to Pydantic field types:

| Python type | Behaviour |
|---|---|
| `str` | Any string |
| `int`, `float` | Numeric, coerced from string |
| `bool` | `true`/`false`/`yes`/`no`/`1`/`0` |
| `list[str]` | List of strings; a YAML list or JSON string |
| `dict` | Arbitrary mapping |
| `Optional[str]` | Optional, defaults to `None` |

---

## Testing

Use `invoke_node` from `stepyard.sdk.testing` - it runs your function through the same validation and context injection as the real engine:

```python
import pytest
from stepyard.sdk.testing import invoke_node, run_node, fake_context
from my_plugin.nodes import my_action


def test_my_action():
    result = run_node(my_action, {"required_param": "hello", "optional_param": 5})
    assert result.output["value"] == "hello:5"


def test_missing_required_param():
    with pytest.raises(Exception, match="required_param"):
        run_node(my_action, {})   # missing required field → validation error


def test_with_custom_context():
    ctx = fake_context(run_id="test-run", step_id="test-step")
    result = run_node(my_action, {"required_param": "hi"}, ctx=ctx)
    assert result.output["count"] > 0


async def test_async_node():
    result = await invoke_node(fetch, {"url": "https://httpbin.org/get"})
    assert result.output["body"]["url"] == "https://httpbin.org/get"
```

---

## Declaring the entry point

```toml title="pyproject.toml"
[project.entry-points."stepyard.plugins"]
my_plugin = "my_plugin_name.nodes"
```

You can also register triggers and hooks:

```toml
[project.entry-points."stepyard.triggers"]
my_plugin = "my_plugin_name.triggers"

[project.entry-points."stepyard.hooks"]
my_plugin = "my_plugin_name.hooks"
```

---

## Install into a project

```bash
cd my-stepyard-project
stepyard plugin add ../my-plugin-name       # local path
stepyard plugin add my-plugin-name          # from PyPI
```

While iterating on a local plugin, re-run `plugin add` after you change the
source - installs into `.stepyard/env` are not editable, so re-installing picks
up your latest code and refreshes the capability registry:

```bash
stepyard plugin add ../my-plugin-name
```

---

## Publishing to PyPI

```bash
cd my-plugin-name
python -m build
twine upload dist/*
```

After publishing, users install it with:

```bash
stepyard plugin add my-plugin-name
```

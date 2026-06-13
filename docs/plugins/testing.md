# Testing Plugins

`stepyard.sdk.testing` provides lightweight helpers that let you test nodes and triggers without starting the full Stepyard engine.

---

## Install

The testing helpers are part of `stepyard` itself - no extra dependency needed:

```bash
pip install stepyard
```

---

## `invoke_node` / `run_node`

Both helpers run a node function through the same Pydantic validation and `NodeContext` injection that the real engine uses.

| Helper | When to use |
|---|---|
| `run_node(func, inputs, *, ctx)` | **Sync tests** - wraps `asyncio.run()` internally |
| `await invoke_node(func, inputs, *, ctx)` | **Async tests** - use in `async def test_*` functions |

```python
from stepyard.sdk.testing import invoke_node, run_node
```

Both accept:
- `func` - the node function decorated with `@node`
- `inputs` - a `dict` of raw inputs (as they would appear in a flow `with:` block)
- `ctx` - optional `NodeContext` (a default `fake_context()` is used when omitted)

Both return a `NodeResult`. Access outputs via `result.output` and status via `result.status`.
Raises `ValidationError` if required inputs are missing or have wrong types.

### Basic test (sync)

```python
from stepyard.sdk.testing import run_node
from my_plugin.nodes import send_email


def test_send_email():
    result = run_node(
        send_email,
        {"to": "user@example.com", "subject": "Hello", "body": "World"},
    )
    assert result.output["delivered"] is True
```

### Basic test (async)

```python
from stepyard.sdk.testing import invoke_node
from my_plugin.nodes import fetch_data


async def test_fetch_data():
    result = await invoke_node(fetch_data, {"url": "https://httpbin.org/get"})
    assert "url" in result.output
```

### Testing validation

```python
import pytest
from stepyard.sdk.testing import run_node
from my_plugin.nodes import send_email


def test_missing_required_field():
    with pytest.raises(Exception, match="to"):
        run_node(send_email, {"subject": "Hello"})  # 'to' is required
```

### Mocking external calls

```python
from unittest.mock import patch, MagicMock
from stepyard.sdk.testing import run_node
from my_plugin.nodes import call_api


def test_call_api_success():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"status": "ok"}
    mock_resp.raise_for_status.return_value = None

    with patch("httpx.get", return_value=mock_resp):
        result = run_node(call_api, {"endpoint": "https://api.example.com"})

    assert result.output["status"] == "ok"


def test_call_api_retryable_error():
    from stepyard.core.errors import TransientError
    import httpx

    with patch("httpx.get", side_effect=httpx.TimeoutException("timeout")):
        with pytest.raises(TransientError):
            run_node(call_api, {"endpoint": "https://api.example.com"})
```

---

## `fake_context`

Creates a `NodeContext` with sensible test defaults. Pass it as the `ctx` keyword when your node uses the context.

```python
from stepyard.sdk.testing import fake_context
```

```python
ctx = fake_context(
    run_id="test-run-001",      # default: "test-run"
    step_id="my_step",          # default: "test-step"
)
```

### Example

```python
from stepyard.sdk.testing import run_node, fake_context
from my_plugin.nodes import process


def test_context_logging(caplog):
    import logging
    ctx = fake_context(step_id="process")

    with caplog.at_level(logging.INFO):
        run_node(process, {"data": {"key": "value"}}, ctx=ctx)

    assert "process" in caplog.text
```

---

## `collect_trigger`

Tests an async trigger generator by collecting `n` events.

```python
from stepyard.sdk.testing import collect_trigger
```

```python
events = await collect_trigger(trigger_func, n=3, **inputs) -> list[dict]
```

### Example

```python
import asyncio
from stepyard.sdk.testing import collect_trigger
from my_plugin.triggers import poll_events


async def test_trigger_emits_events():
    events = await collect_trigger(poll_events, n=2, url="https://api.example.com/stream")
    assert len(events) == 2
    assert "id" in events[0]


# Sync wrapper:
def test_trigger_sync():
    events = asyncio.run(collect_trigger(poll_events, n=1, url="..."))
    assert events[0]["type"] == "message"
```

---

## Recommended test structure

```
my-plugin/
└── tests/
    ├── conftest.py          # shared fixtures (fake_context, mocked HTTP sessions, etc.)
    ├── test_nodes.py        # one test file per node module
    ├── test_triggers.py
    └── test_hooks.py
```

```python title="tests/conftest.py"
import httpx
import pytest
from stepyard.sdk.testing import fake_context


@pytest.fixture()
def ctx():
    return fake_context(run_id="fixture-run", step_id="test")


@pytest.fixture()
def mock_api(respx_mock):  # using 'respx' for httpx mocking
    respx_mock.get("https://api.example.com/data").mock(
        return_value=httpx.Response(200, json={"items": [1, 2, 3]})
    )
    return respx_mock
```

```python title="tests/test_nodes.py"
from stepyard.sdk.testing import run_node
from my_plugin.nodes import fetch_items


def test_fetch_items(ctx, mock_api):
    result = run_node(fetch_items, {"url": "https://api.example.com/data"}, ctx=ctx)
    assert result.output["count"] == 3
    assert result.output["items"] == [1, 2, 3]
```

---

## Coverage

Run tests with coverage using `pytest-cov`:

```bash
pytest tests/ --cov=my_plugin --cov-report=term-missing
```

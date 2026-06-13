# Plugin Quick Start

A plugin is a regular Python package with one extra thing: `setuptools` entry points that tell Stepyard where to find your nodes, triggers, and hooks.

---

## Scaffold

```bash
stepyard plugin init stepyard-plugin-myservice ./stepyard-plugin-myservice
cd stepyard-plugin-myservice
```

Generated structure:

```
stepyard-plugin-myservice/
├── pyproject.toml
├── README.md
├── src/
│   └── stepyard_plugin_myservice/
│       ├── __init__.py
│       └── nodes.py
└── tests/
    └── test_nodes.py
```

---

## Write a node

```python title="src/stepyard_plugin_myservice/nodes.py"
from stepyard.sdk import node, NodeResult


@node(name="myservice.greet")
def greet(name: str, formal: bool = False) -> NodeResult:
    """Greet a person.

    Args:
        name: Person's name.
        formal: Use formal greeting. Default: false.
    """
    greeting = f"Good day, {name}." if formal else f"Hi, {name}!"
    return NodeResult(status="success", output={"message": greeting})
```

## Register the entry point

```toml title="pyproject.toml"
[project.entry-points."stepyard.plugins"]
myservice = "stepyard_plugin_myservice.nodes"
```

## Install and use

```bash
cd ../my-stepyard-project
stepyard plugin add ../stepyard-plugin-myservice
```

```yaml title="flows/hello.yaml"
steps:
  - id: greet
    uses: myservice.greet
    with:
      name: Alice
      formal: true

  - id: print
    uses: shell.run
    with:
      command: echo "${{ steps.greet.output.message }}"
```

```bash
stepyard run hello
# Good day, Alice.
```

---

## Input validation

Stepyard generates a Pydantic model from your type hints. Invalid inputs are rejected before the function is called.

| Python type | Validated as |
|---|---|
| `str` | Any string |
| `int`, `float` | Numeric, coerced from string |
| `bool` | `true`/`false`/`yes`/`no`/`1`/`0` |
| `list[str]` | List of strings |
| `dict` / `Dict[str, Any]` | Arbitrary mapping |
| `Optional[T]` | Optional field, defaults to `None` |

---

## NodeResult

Return a `NodeResult` to provide structured output and status:

```python
from stepyard.sdk import node, NodeResult


@node(name="db.query")
def query(sql: str, connection_string: str) -> NodeResult:
    rows = execute(sql, connection_string)
    return NodeResult(
        status="success",
        output={
            "rows": rows,
            "count": len(rows),
        },
    )
```

You can also return a plain `dict` - Stepyard wraps it in `NodeResult` automatically. Raise any exception to mark the step `failed`.

---

## NodeContext

Inject `NodeContext` as the first parameter to access logging and run metadata:

```python
from stepyard.sdk import node, NodeContext, NodeResult


@node(name="audit.log")
def audit_log(ctx: NodeContext, message: str) -> NodeResult:
    ctx.log.info("[%s] %s", ctx.step_id, message)
    return NodeResult(status="success", output={"logged": True})
```

`NodeContext` fields:

| Field | Type | Description |
|---|---|---|
| `run_id` | `str` | Unique run identifier |
| `step_id` | `str` | Current step id |
| `log` | `Logger` | Standard Python logger |
| `metrics` | `dict` | Mutable dict for passing data to hooks |

---

## Async nodes

For I/O-bound operations, use `async def` - Stepyard handles the event loop:

```python
import httpx
from stepyard.sdk import node, NodeResult


@node(name="github.get_pr")
async def get_pr(repo: str, pr_number: int, token: str) -> NodeResult:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.github.com/repos/{repo}/pulls/{pr_number}",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()

    data = resp.json()
    return NodeResult(
        status="success",
        output={
            "title": data["title"],
            "author": data["user"]["login"],
            "state": data["state"],
            "url": data["html_url"],
        },
    )
```

---

## Error handling

| Exception | Behaviour |
|---|---|
| `TransientError` | Eligible for retry |
| `NodeExecutionError` | Permanent failure, no retry |
| Any other exception | Treated as `NodeExecutionError` |

```python
from stepyard.sdk import node
from stepyard.core.errors import TransientError, NodeExecutionError
import httpx


@node(name="myservice.call")
def call(endpoint: str) -> dict:
    try:
        resp = httpx.get(endpoint, timeout=5)
        resp.raise_for_status()
        return resp.json()
    except httpx.TimeoutException as exc:
        raise TransientError("Request timed out") from exc      # will be retried
    except httpx.HTTPStatusError as exc:
        raise NodeExecutionError(f"HTTP {exc.response.status_code}") from exc  # no retry
```

---

## What's next?

- **[SDK Reference](sdk.md)** - complete API documentation
- **[Testing](testing.md)** - write fast unit tests for your nodes
- **[Triggers & Hooks](triggers_hooks.md)** - go beyond nodes
- **[Examples](examples.md)** - real-world plugin patterns

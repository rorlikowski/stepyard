# SDK Reference

The public API you need to write a plugin. Most symbols live in `stepyard.sdk`; the typed error classes live in `stepyard.core.errors`.

```python
from stepyard.sdk import (
    node,
    trigger,
    NodeResult,
    NodeContext,
    StepExecutionHook,
    InputRequest,
    input_collector,
)
from stepyard.core.errors import TransientError, NodeExecutionError
```

---

## `@node`

```python
@node(name: str)
def my_node(param: str, ...) -> NodeResult | dict | str | None:
    ...
```

Registers a function as a Stepyard node.

**Parameters:**

| Name | Type | Description |
|---|---|---|
| `name` | `str` | Dotted capability name, e.g. `"myservice.action"` |

**Function signature rules:**

- Type hints on all parameters are mandatory - Stepyard generates a Pydantic model from them.
- An optional first parameter typed `NodeContext` receives the execution context.
- Return `NodeResult`, a plain `dict`, or any value. Raise an exception to fail the step.
- `async def` is fully supported.

```python
from stepyard.sdk import node, NodeContext, NodeResult


@node(name="stripe.charge")
async def charge(
    ctx: NodeContext,
    amount: int,           # cents
    currency: str = "usd",
    customer_id: str = "",
) -> NodeResult:
    ctx.log.info("Charging %s %s to %s", amount, currency, customer_id)
    receipt = await stripe_api.charge(amount, currency, customer_id)
    return NodeResult(status="success", output={"receipt_id": receipt.id})
```

---

## `@trigger`

```python
@trigger(name: str)
async def my_trigger(param: str, ...) -> AsyncGenerator[dict, None]:
    ...
    yield {"event": "data"}
```

Registers an async generator as a Stepyard trigger. Each `yield` fires one run.

**Parameters:**

| Name | Type | Description |
|---|---|---|
| `name` | `str` | Dotted capability name, e.g. `"github.push"` |

The trigger function **must** be an `async def` that `yield`s dicts. The yielded dict becomes `trigger.payload` in the flow.

```python
import asyncio
import httpx
from stepyard.sdk import trigger


@trigger(name="shopify.new_order")
async def new_order(shop_domain: str, access_token: str, poll_interval: int = 60):
    """Fire for each new Shopify order."""
    seen_ids: set[int] = set()

    while True:
        resp = httpx.get(
            f"https://{shop_domain}/admin/api/2024-01/orders.json?status=open",
            headers={"X-Shopify-Access-Token": access_token},
        )
        for order in resp.json().get("orders", []):
            if order["id"] not in seen_ids:
                seen_ids.add(order["id"])
                yield {
                    "id": order["id"],
                    "total": order["total_price"],
                    "customer": order["customer"]["email"],
                }

        await asyncio.sleep(poll_interval)
```

---

## `NodeResult`

Structured return type for nodes.

```python
@dataclass
class NodeResult:
    status: str           # "success" or "failed"
    output: dict          # the step's output, accessible via ${{ steps.id.output.field }}
    error: str | None     # error message (optional)
    metrics: dict         # internal metadata (not persisted to user-visible output)
```

You may also return a plain `dict` - Stepyard wraps it automatically:

```python
# These are equivalent:
return {"key": "value"}
return NodeResult(status="success", output={"key": "value"})
```

---

## `NodeContext`

Execution context injected as the first parameter when you name it `ctx: NodeContext`.

| Field | Type | Description |
|---|---|---|
| `run_id` | `str` | Unique run identifier (e.g. `run-20260611_094122-a1b2c3`) |
| `step_id` | `str` | Step id as declared in YAML |
| `log` | `logging.Logger` | Logger that writes to the run's log file |
| `metrics` | `dict` | Mutable dict shared with hooks |

It also provides a `report_progress()` method for emitting progress updates during long-running nodes.

---

## `TransientError`

Raise this for retriable failures (network timeout, rate limit, temporary unavailability):

```python
from stepyard.core.errors import TransientError

raise TransientError("Database connection timed out")
```

The engine retries the step up to `retry.attempts` times.

---

## `NodeExecutionError`

Raise this for permanent, non-retriable failures:

```python
from stepyard.core.errors import NodeExecutionError

raise NodeExecutionError(f"User {user_id} not found")
```

---

## `StepExecutionHook`

Protocol for lifecycle hooks. Implement this class and register it via the `stepyard.hooks` entry point.

```python
from stepyard.sdk import StepExecutionHook, NodeContext, NodeResult


class MyHook(StepExecutionHook):
    async def before_execute(
        self,
        ctx: NodeContext,
        step,
        inputs: dict,
    ) -> NodeResult | None:
        """Called before the node runs.

        Return a NodeResult to skip the node and use this result instead.
        Return None to proceed with normal execution.
        """
        ctx.log.info("Starting %s", ctx.step_id)
        return None

    async def after_execute(
        self,
        ctx: NodeContext,
        step,
        result: NodeResult,
    ) -> NodeResult:
        """Called after the node runs (even on failure).

        Must return a NodeResult.
        """
        ctx.log.info("Finished %s: %s", ctx.step_id, result.status)
        return result


# Entry points must reference an INSTANCE, not the class:
my_hook = MyHook()
```

Register in `pyproject.toml` (point at the instance, not the class):

```toml
[project.entry-points."stepyard.hooks"]
my_plugin = "my_plugin.hooks:my_hook"
```

---

## `InputRequest` and `@input_collector`

Use `@input_collector` to declare that your node needs user input **before** the flow subprocess starts (e.g. a password or environment choice):

```python
from stepyard.sdk import input_collector, InputRequest


@input_collector("myplugin.deploy")
def collect_inputs(step_id, step, config, context):
    return InputRequest(
        step_id=step_id,
        env_key=f"STEPYARD_INPUT_{step_id.upper()}",
        prompt="Deploy to which environment?",
        choices=["staging", "production"],
        required=True,
    )
```

`InputRequest` fields:

| Field | Type | Description |
|---|---|---|
| `step_id` | `str` | Step id |
| `env_key` | `str` | Environment variable the subprocess reads the value from |
| `prompt` | `str` | Prompt shown to the user |
| `default` | `str` | Default value |
| `required` | `bool` | Raise error if empty |
| `secret` | `bool` | Hide typed characters |
| `choices` | `list[str]` | Restrict to these values |

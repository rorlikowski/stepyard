# Triggers & Hooks

Beyond nodes, plugins can register **triggers** (define when a flow runs) and **hooks** (intercept step execution).

---

## Triggers

A trigger is an `async` generator that `yield`s a dict every time an event occurs. Stepyard runs each yield as a separate flow execution.

### Minimal trigger

```python title="my_plugin/triggers.py"
import asyncio
from stepyard.sdk import trigger


@trigger(name="myservice.event")
async def on_event(url: str, poll_interval: int = 30):
    """Poll a URL and fire when the response changes."""
    last = None

    while True:
        import httpx
        data = httpx.get(url).json()

        if data != last:
            last = data
            yield {"data": data, "url": url}

        await asyncio.sleep(poll_interval)
```

### Use in a flow

```yaml
name: watch_prices
trigger:
  uses: myservice.event
  with:
    url: https://api.coindesk.com/v1/bpi/currentprice.json
    poll_interval: 60

steps:
  - id: log_price
    uses: shell.run
    with:
      command: echo "BTC price changed: ${{ trigger.payload.data.bpi.USD.rate }}"
```

### Real example: Redis Pub/Sub

```python title="stepyard_plugin_redis/triggers.py"
import redis.asyncio as aioredis
from stepyard.sdk import trigger


@trigger(name="redis.pubsub")
async def pubsub(channel: str, host: str = "localhost", port: int = 6379):
    """Listen to a Redis Pub/Sub channel and fire on every message."""
    client = aioredis.Redis(host=host, port=port)
    ps = client.pubsub()
    await ps.subscribe(channel)

    async for message in ps.listen():
        if message["type"] == "message":
            yield {
                "channel": channel,
                "data": message["data"].decode(),
            }
```

### Real example: Webhook receiver

```python title="stepyard_plugin_webhook/triggers.py"
import asyncio
from aiohttp import web
from stepyard.sdk import trigger


@trigger(name="webhook.receive")
async def receive(host: str = "0.0.0.0", port: int = 8080, path: str = "/webhook"):
    """Start an HTTP server and fire on every POST to the configured path."""
    queue: asyncio.Queue = asyncio.Queue()

    async def handler(request):
        body = await request.json()
        await queue.put(body)
        return web.Response(text="ok")

    app = web.Application()
    app.router.add_post(path, handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()

    while True:
        payload = await queue.get()
        yield payload
```

---

## Hooks

Hooks intercept step execution across the entire engine. They run for **every step** in every flow - use them for cross-cutting concerns like auditing, caching, or approval gates.

### `StepExecutionHook` protocol

```python
from stepyard.sdk import StepExecutionHook, NodeContext, NodeResult


class MyHook(StepExecutionHook):
    async def before_execute(
        self,
        ctx: NodeContext,
        step,
        inputs: dict,
    ) -> NodeResult | None:
        ...  # return None to proceed, or NodeResult to skip the node

    async def after_execute(
        self,
        ctx: NodeContext,
        step,
        result: NodeResult,
    ) -> NodeResult:
        ...  # must return a NodeResult
```

### Register a hook

Create an instance of your hook and reference that instance from the entry point:

```python title="my_plugin/hooks.py"
my_hook = MyHook()
```

```toml title="pyproject.toml"
[project.entry-points."stepyard.hooks"]
my_plugin = "my_plugin.hooks:my_hook"
```

The entry point must point at a hook **instance**, not the class.

---

### Example: Audit logger

```python title="my_plugin/hooks.py"
import time
from stepyard.sdk import StepExecutionHook, NodeContext, NodeResult


class AuditHook(StepExecutionHook):
    async def before_execute(self, ctx, step, inputs):
        ctx.metrics["_start"] = time.monotonic()
        ctx.log.info("[AUDIT] start %s run=%s", ctx.step_id, ctx.run_id)
        return None

    async def after_execute(self, ctx, step, result):
        duration = time.monotonic() - ctx.metrics.get("_start", time.monotonic())
        ctx.log.info(
            "[AUDIT] end %s run=%s status=%s duration=%.2fs",
            ctx.step_id, ctx.run_id, result.status, duration,
        )
        return result


# Register this instance, e.g. entry point "my_plugin.hooks:audit_hook":
audit_hook = AuditHook()
```

---

### Example: Response cache

```python title="my_plugin/hooks.py"
import hashlib, json
from stepyard.sdk import StepExecutionHook, NodeContext, NodeResult


class CacheHook(StepExecutionHook):
    def __init__(self):
        self._cache: dict[str, dict] = {}

    async def before_execute(self, ctx, step, inputs):
        if getattr(step, "cache", False):
            key = hashlib.md5(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
            ctx.metrics["_cache_key"] = key
            if key in self._cache:
                ctx.log.info("Cache hit for %s", ctx.step_id)
                return NodeResult(status="success", output=self._cache[key])
        return None

    async def after_execute(self, ctx, step, result):
        if getattr(step, "cache", False) and result.status == "success":
            key = ctx.metrics.get("_cache_key")
            if key:
                self._cache[key] = result.output
        return result
```

---

### Example: Metric exporter (Prometheus)

```python title="my_plugin/hooks.py"
import time
from prometheus_client import Counter, Histogram
from stepyard.sdk import StepExecutionHook, NodeContext, NodeResult


STEP_RUNS = Counter("stepyard_step_runs_total", "Total step runs", ["flow", "step", "status"])
STEP_DURATION = Histogram("stepyard_step_duration_seconds", "Step duration", ["flow", "step"])


class PrometheusHook(StepExecutionHook):
    async def before_execute(self, ctx, step, inputs):
        ctx.metrics["_prom_start"] = time.monotonic()
        return None

    async def after_execute(self, ctx, step, result):
        duration = time.monotonic() - ctx.metrics.get("_prom_start", time.monotonic())
        flow_name = ctx.run_id.split("_")[0]  # or extract from context

        STEP_RUNS.labels(flow=flow_name, step=ctx.step_id, status=result.status).inc()
        STEP_DURATION.labels(flow=flow_name, step=ctx.step_id).observe(duration)
        return result
```

---

## `after_execute` on failure

Unlike many hook systems, Stepyard calls `after_execute` even when the node failed. Use this to guarantee cleanup or error reporting:

```python
async def after_execute(self, ctx, step, result):
    if result.status == "failed":
        await notify_oncall(
            f"Step {ctx.step_id} failed in run {ctx.run_id}: {result.error}"
        )
    return result
```

Hook errors are isolated - if a hook raises an exception, it is logged but does not affect the step result.

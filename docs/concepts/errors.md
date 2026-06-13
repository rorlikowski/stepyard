# Error Handling

Stepyard gives you precise control over how errors propagate through a flow.

---

## Default behaviour

By default, **a step that raises an exception or returns a failed node result stops the run immediately**. The run is marked `failed` and no further steps execute.

!!! note "Built-in nodes that do not fail on errors"
    `shell.run` **never** fails on a non-zero exit code - it always succeeds and
    returns `{stdout, stderr, code}`. Branch on `${{ steps.<id>.output.code }}`
    to react to command failure.

    `http.request` **does not** fail on 4xx/5xx responses - it returns
    `{status, body, headers, error?}`. Connection errors and invalid URLs still
    raise and fail the step.

```yaml
steps:
  - id: migrate
    uses: shell.run
    with:
      command: alembic upgrade head
    # exit code is in steps.migrate.output.code - the step itself still succeeds

  - id: restart
    if: ${{ steps.migrate.output.code == 0 }}
    uses: shell.run
    with:
      command: systemctl restart myapp    # skipped when migrate returned non-zero
```

---

## `continue_on_error`

Set `continue_on_error: true` to mark a step `failed` but keep the flow going:

```yaml
  - id: cache_warm
    continue_on_error: true
    uses: shell.run
    with:
      command: ./warm_cache.sh

  - id: deploy
    uses: shell.run    # runs even if cache_warm failed
    with:
      command: ./deploy.sh
```

The step's outputs are still populated (including the non-zero `code`) and available to downstream `if` expressions.

---

## `retry`

Automatically retry a step on failure. Useful for flaky network calls or transient infrastructure errors:

```yaml
  - id: upload
    retry:
      attempts: 5
      initial_delay: 10
      backoff_factor: 2.0
    uses: http.download
    with:
      url: https://cdn.example.com/artifact.zip
      dest: ./artifact.zip

  - id: call_api
    retry:
      attempts: 3
      initial_delay: 2
    uses: http.request
    with:
      url: https://unstable.service.com/api
```

Retries apply when a step **raises an exception** or a plugin node returns
`failed` status. They do **not** re-run `shell.run` based on exit code (the
node always succeeds). For HTTP status codes, branch on
`${{ steps.<id>.output.status }}` instead of relying on `retry`.

Stepyard waits `initial_delay` seconds before the first retry. With `backoff_factor: 2.0`, the wait doubles each attempt (e.g. 2s, 4s, 8s); a factor of `1.0` keeps the delay fixed.

| Field | Default | Description |
|---|---|---|
| `attempts` | `3` | Total attempts |
| `initial_delay` | `1.0` | Seconds to wait before the first retry |
| `backoff_factor` | `2.0` | Delay multiplier per attempt (1.0 = fixed) |

---

## React to errors with `if`

Combine `continue_on_error` with `if` to implement custom error handling:

```yaml
  - id: deploy
    continue_on_error: true
    uses: shell.run
    with:
      command: kubectl apply -f k8s/

  - id: rollback
    if: ${{ steps.deploy.output.code != 0 }}
    uses: shell.run
    with:
      command: kubectl rollout undo deployment/myapp

  - id: alert
    if: ${{ steps.deploy.output.code != 0 }}
    uses: http.request
    with:
      url: ${{ env.SLACK_WEBHOOK }}
      method: POST
      json_body:
        text: "🚨 Deploy failed - rolled back.\n```${{ steps.deploy.output.stdout }}```"
```

---

## `timeout`

Kill a step that runs too long:

```yaml
  - id: slow_etl
    timeout: "10m"
    uses: shell.run
    with:
      command: python etl.py

  - id: quick_check
    timeout: "5s"
    uses: http.request
    with:
      url: https://api.example.com/ping
```

If the timeout is exceeded, the step is cancelled and marked `failed`. The `code` is `-1`.

---

## Error hierarchy (for plugin authors)

When writing a plugin, raise one of these typed exceptions for the best error handling:

| Exception | When to raise |
|---|---|
| `stepyard.core.errors.TransientError` | Temporary failure - eligible for retry (network timeout, rate limit) |
| `stepyard.core.errors.NodeExecutionError` | Permanent failure - do not retry (business logic error, invalid data) |
| Any other exception | Treated as `NodeExecutionError` (permanent) |

```python
from stepyard.sdk import node
from stepyard.core.errors import TransientError, NodeExecutionError
import httpx


@node(name="myservice.call")
def call_api(url: str) -> dict:
    try:
        resp = httpx.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except httpx.TimeoutException as exc:
        raise TransientError(f"Request timed out: {exc}") from exc
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429:
            raise TransientError("Rate limited") from exc
        raise NodeExecutionError(f"HTTP {exc.response.status_code}") from exc
```

---

## Inspecting failed runs

```bash
stepyard status                    # per-flow status overview
stepyard logs <run-id>             # full step-by-step output for one run
stepyard show <run-id>             # structured summary with step status and outputs
```

Replay a failed run from the failed step, keeping outputs of completed steps. Replay executes in-process (not via `engine.runner`):

```bash
stepyard replay <run-id> --from-step upload
```

---

## Validating before running

```bash
stepyard validate flows/deploy.yaml
```

Stepyard checks the YAML schema and reports errors with field names and hints before any code runs:

```
✗  flows/deploy.yaml

  Step "notify" - unknown node "slack.sendd"
  Did you mean: slack.send?
  Available slack nodes: slack.send, slack.send_file
```

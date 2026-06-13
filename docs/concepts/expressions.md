# Expression Engine

Stepyard uses a lightweight expression language embedded inside `${{ }}` delimiters. Any string field in a flow that contains `${{ }}` is evaluated before the step runs.

---

## Syntax

```
${{ <expression> }}
```

Expressions are a safe **subset** of Python (evaluated with `simpleeval`): arithmetic, comparisons, boolean logic, indexing, attribute and method access, list comprehensions, and the small set of conversion functions listed below. Arbitrary function calls and imports are not allowed.

A string can contain multiple expressions:

```yaml
command: echo "Version ${{ vars.version }} on ${{ vars.env }}"
```

An expression that spans the entire value is coerced to its native type (int, bool, list…):

```yaml
json_body:
  retry_count: ${{ steps.prev.output.attempt + 1 }}
  enabled: ${{ steps.check.output.ok }}
```

---

## Context variables

Every expression has access to these top-level variables:

### `steps`

Outputs of previously completed steps.

```yaml
url: https://api.example.com/users/${{ steps.create_user.output.id }}
```

If a step has not run yet, `steps.<id>` is `None`. Accessing a field on `None` (or any other missing/non-existent field) raises an evaluation error and marks the step `failed`.

The `.output` sub-object contains the fields the node returned. For repeated steps (via `loop`, `while`, or `next` jumps), `.output` always refers to the **latest** iteration.

```yaml
# After a loop step "process", access per-iteration outputs:
result_0: ${{ steps.process[0].output }}
result_latest: ${{ steps.process.output }}    # same as last iteration
```

### `env`

Environment variables available to the flow. Read-only. This namespace contains:

- variables declared in the flow's top-level `env:` block
- variables loaded from files listed in the flow's `dotenv:` key
- the project `.env` file (auto-loaded by Stepyard)
- any variable already present in the shell/OS environment when the flow runs

```yaml
headers:
  Authorization: Bearer ${{ env.API_TOKEN }}
```

Declare non-secret defaults directly in the flow YAML with `env:` (see [Flows & Steps - Environment variables](flows.md#environment-variables-env)), and supply secrets from outside (shell env, `.env` file, or a secrets manager).

!!! warning "Secrets"
    Avoid printing secret env vars in `shell.run` commands - they appear in logs. Inject them directly via the `env` field of `shell.run` instead.

### `vars`

Key/value pairs passed with `--var key=value` or `--env-file`. Read-only.

```yaml
command: ./deploy.sh --environment ${{ vars.env }}
```

There is no `secrets` namespace - use `env` or `vars` as described in [How to manage secrets](../how-to/secrets.md).

### `trigger`

Metadata about the trigger that started this run. Available fields:

| Field | Description |
|---|---|
| `trigger.type` | Trigger type (`cron`, `interval`, `manual`, or a plugin name) |
| `trigger.payload` | Data yielded by the trigger function |
| `trigger.run_id` | Unique run identifier |
| `trigger.event_id` | Unique event identifier (for deduplication) |

```yaml
  - id: log_trigger
    uses: shell.run
    with:
      command: echo "Triggered by ${{ trigger.type }} at ${{ trigger.payload.timestamp }}"
```

### `item`

The current element when inside a `loop`:

```yaml
  - id: process
    loop: ${{ ["a", "b", "c"] }}
    uses: shell.run
    with:
      command: echo ${{ item }}
```

### `visits`

Number of times each step has been visited in this run. Used for graph-style flows with backward `next` jumps.

```yaml
  - id: retry_step
    uses: shell.run
    next: ${{ 'retry_step' if visits.retry_step < 3 else 'end' }}
    max_visits: 3
    with:
      command: ./flaky_command.sh
```

---

## Operators and built-ins

Expressions support the safe subset of Python described above. Commonly used patterns:

### Arithmetic

```yaml
retries_left: ${{ 5 - steps.attempt.output.count }}
```

### String formatting

```yaml
tag: ${{ vars.service + ':' + env.GIT_SHA }}
```

### Comparisons

```yaml
if: ${{ steps.check.output.status == 200 }}
if: ${{ steps.check.output.status >= 200 and steps.check.output.status < 300 }}
if: ${{ steps.result.output.count > 0 }}
```

### Ternary

```yaml
command: ${{ "echo ok" if steps.test.output.code == 0 else "echo fail" }}
```

### `None` / empty checks

```yaml
if: ${{ steps.optional.output is not None }}
if: ${{ steps.list_result.output.items }}    # truthy when non-empty list
```

### List operations

```yaml
loop: ${{ steps.fetch.output.body.users }}             # iterate a list from HTTP response
loop: ${{ steps.fetch.output.body.users[:10] }}        # first 10 items
loop: ${{ [u for u in steps.fetch.output.body.users if u['active']] }}
```

### Dict access

```yaml
command: echo ${{ steps.config.output.body['database']['host'] }}
# or with dot notation when key is a valid identifier:
command: echo ${{ steps.config.output.body.database.host }}
```

### String methods

```yaml
command: echo ${{ steps.name.output.upper() }}
path: ${{ env.HOME + '/' + vars.project.replace('-', '_') }}
```

### Built-in functions

The expression engine is intentionally small. Only a few conversion helpers are
available - `int`, `float`, and `str`. There is **no** `len`, `range`, `bool`,
`rand`, or arbitrary function access; do any counting, ranging, or heavier logic
inside a node (e.g. `shell.run` or a Python plugin) instead.

```yaml
threshold: ${{ int(vars.limit) }}
text: "Exit code was ${{ str(steps.build.output.code) }}"
# List comprehensions and method calls work, so you rarely need functions:
loop: ${{ [r["id"] for r in steps.fetch.output.body.rows] }}
```

---

## Truthiness in `if`

The `if` field uses Python truthiness rules:

| Value | Evaluated as |
|---|---|
| `true`, `True`, `"true"`, `"yes"`, `"1"` | truthy |
| `false`, `False`, `"false"`, `"no"`, `"0"`, `""`, `0`, `None` | falsy |
| Non-empty list / dict | truthy |
| Empty list `[]` / empty dict `{}` | falsy |

---

## Escaping `${{`

To include a literal `${{` in a string, double the outer dollar sign:

```yaml
command: echo "Template literal: $${{ not an expression }}"
```

---

## Errors in expressions

If an expression raises an exception (e.g. `KeyError`, `TypeError`), the step is marked `failed` with a message that includes the expression source and the error. Use `stepyard logs <run-id>` to see the full context.

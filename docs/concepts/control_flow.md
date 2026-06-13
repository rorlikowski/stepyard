# Control Flow

By default, steps run top-to-bottom. Use `if`, `loop`, `while`, and `next` to skip, repeat, and branch (bounded by `max_visits` and `STEPYARD_MAX_STEP_VISITS`).

---

## Conditionals - `if`

The `if` field accepts any expression. If the result is falsy, the step (and any nested steps) is **skipped** - it doesn't fail, it just doesn't run.

```yaml
  - id: notify_failure
    if: ${{ steps.test.output.code != 0 }}
    uses: http.request
    with:
      url: ${{ env.SLACK_WEBHOOK }}
      method: POST
      json_body:
        text: "Tests failed: ${{ steps.test.output.stdout }}"
```

### Mutual exclusion - if/else branching

Use complementary conditions to implement if/else logic:

```yaml
  - id: on_success
    if: ${{ steps.deploy.output.code == 0 }}
    uses: shell.run
    with:
      command: echo "Deployed successfully"

  - id: on_failure
    if: ${{ steps.deploy.output.code != 0 }}
    uses: shell.run
    with:
      command: echo "Deployment failed - rolling back"
```

### Nested group under a condition

A step without `uses` groups nested steps. Apply `if` to the group to gate the entire block:

```yaml
  - id: production_steps
    if: ${{ vars.env == "production" }}
    steps:
      - id: run_migrations
        uses: shell.run
        with:
          command: alembic upgrade head

      - id: warm_cache
        uses: shell.run
        with:
          command: python manage.py warm_cache
```

If `vars.env` is not `"production"`, neither `run_migrations` nor `warm_cache` runs.

---

## Loops - `loop`

Iterate over a list. In each iteration, the current element is available as `${{ item }}`.

```yaml
  - id: restart_services
    loop: ${{ ["auth", "billing", "gateway"] }}
    uses: shell.run
    with:
      command: docker restart ${{ item }}
```

### Loop over a dynamic list

```yaml
  - id: fetch_users
    uses: http.request
    with:
      url: https://api.example.com/users

  - id: send_email
    loop: ${{ steps.fetch_users.output.body.users }}
    uses: shell.run
    with:
      command: send-email --to ${{ item.email }} --name "${{ item.name }}"
```

### Loop over a fixed list

The expression engine has no `range()`, so provide the values explicitly (a YAML
list or an inline expression list):

```yaml
  - id: index_loop
    loop: ${{ [0, 1, 2, 3, 4] }}
    uses: shell.run
    with:
      command: echo "Item ${{ item }}"   # prints 0, 1, 2, 3, 4
```

### Nested loop

Use a group step to loop over a 2D structure:

```yaml
  - id: deploy_envs
    loop: ${{ ["staging", "production"] }}
    steps:
      - id: apply
        uses: shell.run
        with:
          command: kubectl apply -f k8s/${{ item }}/ --context ${{ item }}

      - id: verify
        uses: http.request
        with:
          url: https://${{ item }}.myapp.com/healthz
```

### Loop outputs

After a loop completes, access outputs per iteration:

```yaml
  - id: summarise
    uses: shell.run
    with:
      # steps.restart_services.output = output of last iteration
      # steps.restart_services[0].output = output of first iteration
      command: echo "Last restart: ${{ steps.restart_services.output.stdout }}"
```

---

## While loops - `while`

Repeat a step as long as an expression is truthy. Combine with `max_visits` to prevent infinite loops.

```yaml
  - id: wait_for_ready
    while: ${{ steps.wait_for_ready.output.body.status != "ready" }}
    max_visits: 20
    uses: http.request
    with:
      url: https://api.example.com/job/${{ env.JOB_ID }}/status

  - id: process_result
    uses: shell.run
    with:
      command: ./process.sh ${{ env.JOB_ID }}
```

!!! note
    `http.request` sets `output.status` to the **HTTP status code** (an integer, e.g. `200`). To check application-level state, use `output.body` - for a JSON response body, access nested fields like `output.body.status`.

!!! tip "Loop guard"
    The engine enforces a global default of 1 000 step visits per run. Set `max_visits: 0` for a truly unlimited loop, or a specific number for a tighter bound. Reaching the limit marks the step as `failed`.

---

## Graph transitions - `next`

By default, after each step the engine moves to the next item in the YAML list. The `next` field overrides this.

```yaml
steps:
  - id: decide
    uses: shell.run
    next: ${{ "notify_ok" if steps.decide.output.code == 0 else "notify_fail" }}
    with:
      command: ./check.sh

  - id: notify_ok
    uses: shell.run
    next: end            # (1)
    with:
      command: echo "All good"

  - id: notify_fail
    uses: shell.run
    with:
      command: echo "Something failed"
```

1. `end` (also: `stop`, `done`, `$end`, `__end__`) finishes the flow immediately, regardless of remaining YAML steps.

### Valid `next` values

| Value | Behaviour |
|---|---|
| `<step-id>` | Jump to that step (forward or backward) |
| `${{ expr }}` | Evaluate expression, use result as step id |
| `end` / `stop` / `done` | Finish the flow |
| *(empty or omitted)* | Continue to next step in YAML order |

### Backward jumps and `visits`

A step can jump back to an earlier step. Stepyard records each visit separately:
- First visit → stored as `step_id`
- Second visit → stored as `step_id#2`
- Third visit → stored as `step_id#3`

Expressions always use the logical id (`steps.ask.output`), which refers to the **latest** visit.

The `visits` context variable tracks how many times each step has run:

```yaml
steps:
  - id: poll
    uses: http.request
    max_visits: 10
    next: ${{ 'done' if steps.poll.output.body.status == 'complete' else 'poll' }}
    with:
      url: https://api.example.com/job/status

  - id: done
    uses: shell.run
    with:
      command: echo "Job done after ${{ visits.poll }} polls"
```

---

## Routing with `flow.route` and `system.if`

Use `flow.route` when a step should jump to another step id and optionally pass a payload. The built-in node returns `{routed, target, payload, reason}`; pair it with `next` on the same or a later step:

```yaml
  - id: pick_target
    uses: system.if
    with:
      condition: ${{ steps.tests.output.code == 0 }}
      true_value: deploy_prod
      false_value: notify_fail

  - id: route
    uses: flow.route
    next: ${{ steps.route.output.target }}
    with:
      target: ${{ steps.pick_target.output }}
      reason: tests finished

  - id: deploy_prod
    uses: shell.run
    with:
      command: ./deploy.sh production

  - id: notify_fail
    uses: http.request
    with:
      url: ${{ env.SLACK_WEBHOOK }}
      method: POST
      json_body:
        text: Tests failed with code ${{ steps.tests.output.code }}
```

`system.if` evaluates a condition and returns `true_value` or `false_value` as a string output. Set `fail_on_false: true` to fail the step when the condition is falsy instead of returning `false_value`.

---

## `continue_on_error`

By default, a failed step stops the entire flow. Set `continue_on_error: true` to mark it `failed` and continue:

```yaml
  - id: optional_cleanup
    continue_on_error: true
    uses: shell.run
    with:
      command: rm -rf /tmp/workdir
```

The step's `output.code` is still available for downstream `if` conditions.

---

## Retry

Automatically retry a failed step:

```yaml
  - id: upload
    retry:
      attempts: 5
      initial_delay: 10
      backoff_factor: 2.0    # delay multiplier per attempt (1.0 = fixed)
    uses: shell.run
    with:
      command: aws s3 cp dist.tar.gz s3://my-bucket/
```

You can also use the shorthand integer form to set just the number of attempts:

```yaml
    retry: 5
```

| Field | Default | Description |
|---|---|---|
| `attempts` | 3 | Total attempts (including the first) |
| `initial_delay` | 1.0 | Seconds to wait before the first retry |
| `backoff_factor` | 2.0 | Delay multiplier per attempt (1.0 = fixed) |

!!! note "What triggers a retry?"
    Retries run when a step **raises an exception** or a plugin node returns
    `failed` status. `shell.run` always succeeds (even on non-zero exit), so
    retries do not help with command exit codes - branch on
    `${{ steps.<id>.output.code }}` instead. Plugin authors should raise
    `TransientError` for retry-eligible failures.

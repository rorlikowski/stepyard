# Tutorial: Build a CI Pipeline

In this tutorial you will build a complete CI pipeline from scratch. By the end you will know how to:

- Write and run a multi-step flow
- Pass data between steps with `${{ }}` expressions
- Use conditionals to handle failures
- Run the pipeline on a schedule
- Inspect, debug, and replay runs

**Estimated time:** 20 minutes.

---

## 1. Project setup

If you haven't already, install Stepyard and create a project:

```bash
pip install stepyard
stepyard init ci-demo
cd ci-demo
```

---

## 2. Your first flow

Create `flows/ci.yaml`:

```yaml title="flows/ci.yaml"
name: ci
description: Lint, test, and report.

steps:
  - id: lint
    uses: shell.run
    with:
      command: ruff check src/

  - id: test
    uses: shell.run
    with:
      command: pytest tests/ -q
```

Run it:

```bash
stepyard run ci
```

Stepyard prints a live progress bar and the final status of each step. If any step fails, the run stops and you see the full error.

---

## 3. Reading outputs from previous steps

After the tests pass, let's post a summary to a webhook. The `shell.run` node exposes the outputs `stdout`, `stderr`, and `code`. Reference them with `${{ steps.<id>.output.<field> }}`.

!!! note "Non-zero exits don't fail the step"
    `shell.run` does **not** fail a step on a non-zero exit code, and `http.request` does **not** fail on a 4xx/5xx response - both return the result as outputs (`code` / `status`). To react to failures, branch on `${{ steps.<id>.output.code }}` or `${{ steps.<id>.output.status }}`.

```yaml title="flows/ci.yaml" hl_lines="13-20"
name: ci
description: Lint, test, and report.

steps:
  - id: lint
    uses: shell.run
    with:
      command: ruff check src/

  - id: test
    uses: shell.run
    with:
      command: pytest tests/ -q --tb=short

  - id: report
    uses: http.request
    with:
      url: ${{ env.WEBHOOK_URL }}
      method: POST
      json_body:
        passed: ${{ steps.test.output.code == 0 }}
        output: ${{ steps.test.output.stdout }}
```

Try it (omit `WEBHOOK_URL` to skip the notify step via `if`, or set it to a test endpoint):

```bash
WEBHOOK_URL=https://httpbin.org/post stepyard run ci
```

If `WEBHOOK_URL` is set but the host is unreachable, `http.request` raises a connection error and the step fails.

---

## 4. Conditional steps

Right now the flow always posts to the webhook. Let's only send a notification when tests fail.

```yaml title="flows/ci.yaml" hl_lines="11-12"
  - id: test
    uses: shell.run
    continue_on_error: true   # (1)
    with:
      command: pytest tests/ -q

  - id: notify_on_failure
    if: ${{ steps.test.output.code != 0 }}   # (2)
    uses: http.request
    with:
      url: ${{ env.SLACK_WEBHOOK }}
      method: POST
      json_body:
        text: "❌ Tests failed on ${{ env.BRANCH }}:\n${{ steps.test.output.stdout }}"
```

1. `continue_on_error: true` lets the flow keep going even if `pytest` exits non-zero.
2. The `if` expression is evaluated before the step runs. A falsy result skips the step entirely.

---

## 5. Looping over multiple targets

To run the CI against multiple Python versions, use `loop`:

```yaml title="flows/ci.yaml"
  - id: test
    loop: ${{ ["3.10", "3.11", "3.12"] }}
    uses: shell.run
    with:
      command: python${{ item }} -m pytest tests/ -q
```

Each iteration runs as a separate step record (`test[0]`, `test[1]`, `test[2]`). If any iteration fails, the entire loop step is marked failed.

---

## 6. Retries for flaky steps

Network calls fail. Add automatic retries with `retry`:

```yaml
  - id: upload_artifact
    uses: shell.run
    retry:
      attempts: 3
      initial_delay: 5
      backoff_factor: 2.0
    with:
      command: aws s3 cp dist/ s3://${{ env.ARTIFACT_BUCKET }}/ --recursive
```

Stepyard waits `initial_delay` seconds before the first retry (doubling each attempt with `backoff_factor: 2.0`) and marks the step failed only after all attempts are exhausted.

---

## 7. The complete flow

Here is the full `ci.yaml` with everything from this tutorial:

```yaml title="flows/ci.yaml"
name: ci
description: Lint, test, build, and notify.

steps:
  - id: lint
    uses: shell.run
    with:
      command: ruff check src/

  - id: test
    loop: ${{ ["3.10", "3.11", "3.12"] }}
    continue_on_error: true
    uses: shell.run
    with:
      command: python${{ item }} -m pytest tests/ -q --tb=short

  - id: build
    if: ${{ steps.test.output.code == 0 }}
    uses: shell.run
    with:
      command: python -m build

  - id: upload
    if: ${{ steps.build.output.code == 0 }}
    retry:
      attempts: 3
      initial_delay: 10
    uses: shell.run
    with:
      command: twine upload dist/*

  - id: notify_success
    if: ${{ steps.upload.output.code == 0 }}
    uses: http.request
    with:
      url: ${{ env.SLACK_WEBHOOK }}
      method: POST
      json_body:
        text: "✅ Released ${{ env.VERSION }} successfully."

  - id: notify_failure
    if: ${{ steps.test.output.code != 0 }}
    uses: http.request
    with:
      url: ${{ env.SLACK_WEBHOOK }}
      method: POST
      json_body:
        text: "❌ CI failed. See logs: ${{ steps.test.output.stdout }}"
```

---

## 8. Preview without running

Before deploying to a real environment, use `--dry-run` to see the execution plan:

```bash
stepyard run ci --dry-run
```

```
Execution plan - ci
─────────────────────────────────────────
 1  lint              shell.run
 2  test              shell.run          loop × 3
 3  build             shell.run          if: steps.test.output.code == 0
 4  upload            shell.run          if: steps.build.output.code == 0  retry × 3
 5  notify_success    http.request       if: steps.upload.output.code == 0
 6  notify_failure    http.request       if: steps.test.output.code != 0
─────────────────────────────────────────
Missing inputs: SLACK_WEBHOOK, VERSION
```

---

## 9. Scheduling the CI pipeline

To run the pipeline every night at midnight, add a `trigger` block:

```yaml title="flows/ci.yaml"
name: ci
trigger:
  uses: cron
  with:
    schedule: "0 0 * * *"   # midnight UTC

steps:
  # ... same as above
```

Start the scheduler daemon:

```bash
stepyard service start
```

The daemon discovers all flows with triggers and runs them automatically. Check the status at any time:

```bash
stepyard status
```

---

## 10. Debugging a failed run

If a run fails, use `stepyard status` to find the run ID, then `stepyard logs` to see the full output:

```bash
stepyard status               # per-flow status overview
stepyard logs <run-id>        # full output for one run
stepyard logs my-flow         # logs for the latest run of a flow
```

To retry a failed run from a specific step:

```bash
stepyard replay <run-id> --from-step upload
```

This re-uses all previously computed outputs and only re-runs from the failed step onwards.

---

## What's next?

- **[Tutorial: Your First Plugin](first-plugin.md)** - extend Stepyard with a custom Python node
- **[Expression engine](../concepts/expressions.md)** - everything you can do inside `${{ }}`
- **[Control flow reference](../concepts/control_flow.md)** - `while`, `next`, nested steps, `max_visits`

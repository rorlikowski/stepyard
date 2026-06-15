<p align="center">
  <img src="https://raw.githubusercontent.com/rorlikowski/stepyard/main/docs/assets/logo.png" alt="Stepyard" width="200"/>
</p>

<h1 align="center">Stepyard</h1>

<p align="center"><strong>Stepyard is a local-first automation runner for developers who want Git-versioned workflows, Python plugins, and private LLM automations - without running a workflow server.</strong></p>

<p align="center">
  <a href="https://github.com/rorlikowski/stepyard/actions/workflows/ci.yml">
    <img src="https://github.com/rorlikowski/stepyard/actions/workflows/ci.yml/badge.svg" alt="CI"/>
  </a>
  <a href="https://codecov.io/gh/rorlikowski/stepyard">
    <img src="https://codecov.io/gh/rorlikowski/stepyard/branch/main/graph/badge.svg" alt="Coverage"/>
  </a>
  <a href="https://pypi.org/project/stepyard/">
    <img src="https://img.shields.io/pypi/v/stepyard?cacheSeconds=600" alt="PyPI"/>
  </a>
  <a href="https://pypi.org/project/stepyard/">
    <img src="https://img.shields.io/pypi/pyversions/stepyard?cacheSeconds=600" alt="Python"/>
  </a>
  <a href="LICENSE">
    <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"/>
  </a>
  <a href="https://github.com/rorlikowski/stepyard/issues">
    <img src="https://img.shields.io/github/issues/rorlikowski/stepyard" alt="Issues"/>
  </a>
</p>

<p align="center">
  <a href="https://rorlikowski.github.io/stepyard/">
    <img src="https://raw.githubusercontent.com/rorlikowski/stepyard/main/docs/assets/demo.gif" alt="Stepyard demo" width="860"/>
  </a>
</p>

```bash
pip install stepyard
stepyard init my-automations && cd my-automations
stepyard run hello
```

---

## Quick example

Build a container, smoke-test it, summarise the result with an LLM, and post
to Slack. One YAML file, no glue scripts.

```yaml title="flows/deploy.yaml"
name: deploy
description: Build the image, smoke-test it, and post an AI summary to Slack.

steps:
  - id: build
    uses: shell.run
    with:
      command: docker build -t myapp:${{ env.GIT_SHA }} .

  - id: smoke_test
    uses: http.request
    with:
      method: GET
      url: https://staging.myapp.com/healthz

  - id: summary
    uses: llm.generate            # built-in - reads OPENAI_API_KEY from the env
    with:
      model: gpt-4o-mini
      prompt: |
        Write a one-line Slack message about this deploy.
        Build exit code: ${{ steps.build.output.code }}
        Health check HTTP status: ${{ steps.smoke_test.output.status }}

  - id: notify
    uses: http.request
    with:
      method: POST
      url: ${{ env.SLACK_WEBHOOK }}
      json_body:
        text: ${{ steps.summary.output.output }}
```

Run it:

```bash
GIT_SHA=$(git rev-parse --short HEAD) stepyard run deploy
```

```text
✓  build         12.4s
✓  smoke_test     0.3s
✓  summary        0.9s
✓  notify         0.2s

Flow completed in 13.8s
```

> **Reading step outputs.** Each node has a documented output shape, referenced
> as `${{ steps.<id>.output... }}`:
>
> | Node | `output` shape |
> |------|----------------|
> | `shell.run` | `{ stdout, stderr, code }` |
> | `http.request` | `{ status, headers, body }` |
> | `llm.generate` | `{ output, usage, model, provider }` (use `${{ steps.<id>.output.output }}` for text) |
>
> Full reference: [`docs/nodes/builtin.md`](docs/nodes/builtin.md).

---

## Why Stepyard?

- **Flows are YAML files in your repo.** Steps, conditions, loops, and retries
  are plain keys. Version-control them alongside your code; no proprietary DSL
  to learn.
- **Extend with plain Python.** One `@node` decorator turns any function into a
  reusable step. Inputs are type-validated automatically; plugin dependencies
  run in an isolated virtualenv, so they never clash with Stepyard's own.
- **Nothing leaves your machine.** State is stored in a local SQLite database.
  Data only goes out if a step in your flow explicitly sends it.
- **Every run is its own process.** Each flow executes in a dedicated OS
  subprocess, so a crash, timeout, or `sys.exit` in one run cannot take down
  the scheduler or a sibling run. See [Execution model](#execution-model).
- **Built-in scheduler, no hosted service.** Add a `trigger:` block with `cron`,
  `interval`, or `startup`, run `stepyard service start`, and flows execute
  on schedule without a control plane.

---

## Install

```bash
# from PyPI
pip install stepyard

# or, for development, with uv
git clone https://github.com/rorlikowski/stepyard && cd stepyard
uv pip install -e ".[dev,docs]"
uv run stepyard doctor      # verify the install
```

Requires Python 3.10+. Works on macOS, Linux, and Windows (WSL).

---

## The 60-second tour

```bash
stepyard init my-automations   # scaffold flows/ + .gitignore + .stepyard/
cd my-automations

stepyard run hello             # run a flow now (in its own subprocess)
stepyard status               # see every flow and its latest run
stepyard show <run-id>        # drill into the steps of one run
stepyard logs <run-id>        # stream the captured logs
stepyard validate --all       # type-check your YAML without running it
```

Schedule it instead of running by hand - add a trigger and start the daemon:

```yaml title="flows/nightly_backup.yaml"
name: nightly_backup
trigger:
  uses: cron
  with:
    schedule: "0 3 * * *"      # every day at 03:00

steps:
  - id: dump
    uses: shell.run
    with:
      command: pg_dump ${{ env.DATABASE_URL }} | gzip > /tmp/backup.sql.gz
```

```bash
stepyard service start          # run the scheduler in the background
stepyard service status
```

---

## Execution model

Stepyard is deliberately process-isolated:

1. **`stepyard run <flow>` spawns a fresh subprocess** (`python -m
   stepyard.engine.runner`) for that single run. Its stdout/stderr are captured
   to `.stepyard/logs/`.
2. **The scheduler daemon** (`stepyard service start`) runs separately. It
   evaluates triggers, enqueues runs in SQLite, and a worker spawns one
   subprocess per run (bounded by `STEPYARD_MAX_CONCURRENT_FLOWS`, default `4`).
3. **Inside a run**, steps execute sequentially. Built-in nodes run in-process;
   plugin nodes installed into an **isolated virtualenv** run in a *second*
   short-lived subprocess that talks JSON over stdin/stdout - so a plugin's
   dependencies can never clash with Stepyard's own.

The practical upshot: one misbehaving flow or plugin cannot corrupt the
scheduler or sibling runs.

---

## Write your own step

```python
# my_plugin/nodes.py
from stepyard.sdk import node, NodeResult, NodeStatus

@node(name="math.add")
def add(a: int, b: int) -> int:
    return a + b

@node(name="files.archive")
def archive(path: str) -> NodeResult:
    if not path:
        return NodeResult(status=NodeStatus.FAILED, error="path is required")
    # ... do the work ...
    return NodeResult(status=NodeStatus.SUCCESS, output={"archived": path})
```

Register it via an entry point and it becomes available as `uses: math.add` in
every flow. See [`docs/plugins/creating.md`](docs/plugins/creating.md).

---

## Documentation

| Section | What's inside |
|---------|---------------|
| [Getting Started](docs/getting-started/index.md) | Install, quickstart, two tutorials |
| [Core Concepts](docs/concepts/index.md) | Flows, expressions, control flow, triggers, errors |
| [How-to Guides](docs/how-to/index.md) | Scheduling, secrets, approvals, debugging |
| [Built-in Nodes](docs/nodes/builtin.md) | Every node that ships with Stepyard |
| [Plugin Development](docs/plugins/creating.md) | Write, test, and publish plugins |
| [CLI Reference](docs/cli/reference.md) | Every command and flag |

The full documentation is published at **[rorlikowski.github.io/stepyard](https://rorlikowski.github.io/stepyard/)**.

Browse the docs locally with `uv run mkdocs serve`.

---

## License

MIT - see [LICENSE](LICENSE).

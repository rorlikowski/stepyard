# How to dry-run and debug flows

Before running a flow for real - especially against production infrastructure - use Stepyard's built-in tools to validate and preview.

---

## Validate syntax and semantics

`stepyard validate` parses the YAML, validates the schema, and checks semantic rules (unknown node names, broken `next` targets, unparseable expressions) **without running anything**:

```bash
stepyard validate flows/deploy.yaml
```

**Clean flow:**

```
✓  flows/deploy.yaml
```

**Flow with errors:**

```
✗  flows/deploy.yaml

  Step "notify" - unknown node "slack.sendd"
  Did you mean: slack.send?
  Available: slack.send, slack.send_file

  Step "build" - next target "compleet" does not exist
  Existing steps: lint, test, build, deploy, notify
```

Validate all flows at once:

```bash
stepyard validate --all    # validates every file in flows/
stepyard validate          # same when no files are passed
```

---

## Preview the execution plan

`stepyard run <name> --dry-run` prints the complete execution plan without running any steps. Expressions that can be resolved statically (from `vars`, `env`, and `trigger` - but not from step outputs) are evaluated:

```bash
GIT_SHA=a1b2c3d stepyard run deploy --dry-run
```

```
Execution plan - deploy
─────────────────────────────────────────────────────────
 1  build           shell.run
    command:  docker build -t myapp:a1b2c3d .

 2  push            shell.run
    command:  docker push myapp:a1b2c3d
    if:       (always)

 3  smoke_test      http.request
    url:      https://staging.myapp.com/healthz
    method:   GET

 4  notify          llm.generate     [requires: OPENAI_API_KEY]
    model:    gpt-4o-mini

 5  post_to_slack   http.request
    if:       steps.notify.output.output != ""
    ⚠  SLACK_WEBHOOK not set
─────────────────────────────────────────────────────────
Missing env vars: OPENAI_API_KEY, SLACK_WEBHOOK
```

The dry-run output shows:

- Step order and node types
- Resolved input values (where possible)
- `if` conditions
- Missing environment variables

---

## Editor autocompletion

Generate a JSON Schema for your flows and get live validation and autocompletion in VS Code, Cursor, or any editor with the YAML Language Server:

```bash
stepyard schema
```

This writes `.stepyard/flow.schema.json` and prints the modeline to add to your flow files:

```yaml
# yaml-language-server: $schema=../.stepyard/flow.schema.json
```

Add it to the top of each flow file and your editor will validate field names, highlight unknown `uses` values, and complete step IDs in expressions.

---

## Run the doctor

`stepyard doctor` checks your environment for common problems:

```bash
stepyard doctor
```

```
Checking Stepyard environment…

✓  Database: .stepyard/data.db
✓  Plugin virtualenv: .stepyard/env
✓  3 projects registered

All checks passed.
```

If a plugin fails to load, check `stepyard service logs` or run with `--verbose` to see the import traceback:

```bash
stepyard service logs --lines 50
```

---

## Inspect logs for a failed run

```bash
stepyard status            # per-flow status overview
stepyard logs <run-id>     # full output for a specific run
stepyard logs my-flow      # logs for the latest run of a flow
stepyard show <run-id>     # structured step-by-step summary
```

The `show` command is the most detailed - it prints step status, attempt counts, outputs, and error messages for every step:

```bash
stepyard show run-20260611_094122-a1b2c3
```

```
Run run-20260611_094122-a1b2c3 - deploy (FAILED)
Started: 2026-06-11 09:41:22  Duration: 17.1s

 build         ✓  12.4 s
 push          ✓   4.1 s
 smoke_test    ✗   0.3 s
   Error: HTTP 503 - Service Unavailable
   URL:   https://staging.myapp.com/healthz

 notify        -  (skipped)
 post_slack    -  (skipped)
```

---

## Replay from a failed step

After fixing the underlying issue, replay the run from the failed step. Previously computed outputs are preserved. Replay runs **in-process** (unlike `stepyard run`, which spawns `engine.runner`):

```bash
stepyard replay run-20260611_094122-a1b2c3 --from-step smoke_test
```

The replay re-runs `smoke_test`, `notify`, and `post_slack` using the existing `build` and `push` outputs. No code is re-built or re-pushed.

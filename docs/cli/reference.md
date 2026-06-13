# CLI Reference

All commands available in Stepyard. Run `stepyard COMMAND --help` for the full help text of any command.

---

## Global options

| Flag | Description |
|---|---|
| `--version`, `-V` | Print the installed version and exit |
| `--help` | Print the help screen |

Run `stepyard` without a command to enter the interactive REPL.

---

## `stepyard init [DIRECTORY]`

Scaffold a new Stepyard project.

```bash
stepyard init                       # scaffold in current directory
stepyard init my-project            # scaffold in ./my-project/
stepyard init my-project --force    # overwrite existing files
```

Creates:

```
my-project/
├── .gitignore
├── .stepyard/
└── flows/
    └── hello.yaml
```

After scaffolding, `stepyard run hello` works immediately.

---

## `stepyard run FLOW_NAME`

Run a flow by name. `FLOW_NAME` is the stem of the YAML file inside `flows/` (no `.yaml` extension). Only top-level files are resolved - subdirectory paths are not yet supported.

```bash
stepyard run deploy
stepyard run deploy --var env=production --var version=1.2.3
stepyard run deploy --env-file .env.production
stepyard run deploy --verbose
stepyard run deploy --dry-run
```

**Options:**

| Flag | Description |
|---|---|
| `--var KEY=VALUE` | Set a flow variable. Repeatable. |
| `--env-file FILE` | Load variables from a `.env` file |
| `--verbose`, `-v` | Print step outputs as they complete |
| `--dry-run` | Print the execution plan without running |
| `--no-logs` | Do not write run output to `.stepyard/logs/` |

**Exit codes:**

| Code | Meaning |
|---|---|
| `0` | Flow completed successfully |
| `1` | Flow failed or validation error |

---

## `stepyard validate [FLOW_FILES...]`

Validate one or all flow files: YAML schema + semantic checks (unknown nodes, broken `next` targets, unparseable expressions).

```bash
stepyard validate --all                  # validate all files in flows/
stepyard validate                        # same when no files are passed
stepyard validate flows/deploy.yaml      # validate one file
```

**Options:**

| Flag | Description |
|---|---|
| `--all` | Validate every file found in `flows/` |

**Exit code:** `0` if all flows are valid, `1` if any have errors.

Example output:

```
✓  flows/backup.yaml
✗  flows/deploy.yaml

  Step "notify" - unknown node "slack.sendd"
  Did you mean: slack.send?
  Available: slack.send, slack.send_file

✗  flows/weekly.yaml

  Step "build" - next target "compleet" does not exist
  Existing steps: lint, test, build, deploy, notify
```

---

## `stepyard schema`

Generate a JSON Schema for flow YAML files and write it to `.stepyard/flow.schema.json`. Enables live validation and autocompletion in editors with the YAML Language Server.

```bash
stepyard schema
stepyard schema --output /path/to/schema.json   # custom output path
```

**Options:**

| Flag | Description |
|---|---|
| `--output FILE`, `-o FILE` | Output path (default: `.stepyard/flow.schema.json`) |

After running this command, add the modeline printed by the command to the top of your flow files (use `../.stepyard/...` for files inside `flows/`):

```yaml
# yaml-language-server: $schema=../.stepyard/flow.schema.json
```

---

## `stepyard status`

Show the most recent run result for each flow.

```bash
stepyard status
```

Example output:

```
 Flow          Description              Last Run              Run ID                        Status
 deploy        Deploy to production     2026-06-11 09:41:22   run-20260611_094122-a1b2c3   completed
 backup        Nightly database backup    2026-06-11 02:00:05   run-20260611_020005-c3d4e5   completed
 ci            CI pipeline              2026-06-10 18:22:11   run-20260610_182211-f6g7h8   failed
```

Output columns: Flow, Description, Last Run, Run ID, Status.

---

## `stepyard show RUN_ID`

Show a structured summary of one run: step status, attempts, and outputs.

```bash
stepyard show run-20260611_094122-a1b2c3
```

Example output:

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

## `stepyard logs [RUN_ID_OR_FLOW]`

Print the raw log output of a run or follow the scheduler log.

```bash
stepyard logs run-20260611_094122-a1b2c3         # logs for one run
stepyard logs my-flow                             # logs for the latest run of a flow
stepyard logs run-20260611_094122-a1b2c3 --follow # stream live (for running flows)
stepyard logs --scheduler                         # tail the scheduler log
stepyard logs --all                               # interleaved output from all active runs
stepyard logs --all --limit 50                    # limit lines per run
stepyard logs --search "error"                    # filter output by keyword
stepyard logs run-20260611_094122-a1b2c3 --lines 100  # last N lines
```

**Options:**

| Flag | Description |
|---|---|
| `--follow`, `-f` | Stream new log lines as they arrive |
| `--scheduler` | Show the scheduler log instead of a run log |
| `--all` | Show interleaved logs from all active runs |
| `--limit N` | Max lines per run when using `--all` |
| `--search TEXT`, `-s TEXT` | Filter lines containing TEXT |
| `--lines N`, `-n N` | Show only the last N lines |

---

## `stepyard replay RUN_ID --from-step STEP_ID`

Re-run a flow starting from a specific step. All outputs from steps before `--from-step` are reused. Unlike `stepyard run`, replay executes **in-process** via `Engine.execute_run` (no `engine.runner` subprocess).

```bash
stepyard replay run-20260611_094122-a1b2c3 --from-step upload
```

**Options:**

| Flag | Description |
|---|---|
| `--from-step STEP_ID` | **Required.** Start from this step, reuse earlier outputs |

---

## `stepyard approvals`

List and act on pending approvals from a separate interactive session (not during `stepyard run`).

```bash
stepyard approvals          # interactive: Approve / Reject / Cancel
```

During an interactive `stepyard run`, the same decision appears inline with
**Postpone (Exit)** instead of Cancel.

---

## `stepyard inspect FLOW_NAME`

Display the YAML definition of a flow with syntax highlighting. Useful for reviewing a flow without opening the file.

```bash
stepyard inspect deploy
```

Prints the flow YAML from `flows/deploy.yaml` with syntax highlighting.

---

## `stepyard clear`

Delete all run history from the local database.

```bash
stepyard clear              # prompts for confirmation
stepyard clear --force      # skip confirmation
```

Running flows are not affected.

---

## `stepyard service`

Manage the background scheduler daemon.

```bash
stepyard service start                  # start daemon in background
stepyard service start --foreground     # start daemon in foreground (blocks)
stepyard service stop                   # stop daemon gracefully
stepyard service restart                # stop + start
stepyard service status                 # show pid and uptime
stepyard service logs                   # print recent scheduler log lines
stepyard service logs --follow          # stream scheduler log live
stepyard service logs --lines 200       # show last N lines
```

**Options for `service start`:**

| Flag | Description |
|---|---|
| `--foreground` | Run the daemon in the foreground instead of detaching |

---

## `stepyard doctor`

Run diagnostics: database connectivity, plugin virtualenv, and project health.

```bash
stepyard doctor
```

Example output:

```
Checking Stepyard environment…

✓  Database: .stepyard/data.db
✓  Plugin virtualenv: .stepyard/env
✓  3 projects registered

All checks passed.
```

---

## `stepyard tools`

Commands for inspecting the capability registry.

```bash
stepyard tools list                    # list all registered nodes and triggers
```

---

## `stepyard plugin`

Commands for managing installed plugins.

```bash
stepyard plugin add stepyard-plugin-telegram
stepyard plugin add ./my-local-plugin
stepyard plugin add "stepyard-plugin-telegram==1.2.3"
stepyard plugin remove stepyard-plugin-telegram
stepyard plugin list                    # list installed plugins
stepyard plugin list --plain            # machine-readable output
stepyard plugin sync                    # install from stepyard.lock
stepyard plugin init NAME [DIRECTORY]   # scaffold a new plugin package
```

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `STEPYARD_MAX_CONCURRENT_FLOWS` | `4` | Max flows running in parallel |
| `STEPYARD_SCHEDULER_TICK` | `5` | Seconds between scheduler ticks |
| `STEPYARD_EXECUTOR_TICK` | `2` | Seconds between executor ticks |
| `STEPYARD_MAX_STEP_VISITS` | `1000` | Global visit guard per run |
| `STEPYARD_FLOWS_DIR` | `flows/` | Directory to scan for flow YAML files |

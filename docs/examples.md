# Examples

The `examples/` directory in the repository contains ready-to-run flows and a complete example plugin. Copy any flow into your project's `flows/` directory and run it immediately.

## Flows

| File | Run with | What it shows |
|------|----------|---------------|
| [`01_hello.yaml`](https://github.com/rorlikowski/stepyard/blob/main/examples/flows/01_hello.yaml) | `stepyard run 01_hello` | The basics: `shell.run` and reading `output.stdout` |
| [`02_branching.yaml`](https://github.com/rorlikowski/stepyard/blob/main/examples/flows/02_branching.yaml) | `stepyard run 02_branching` | `if:` conditions on `output.code` |
| [`03_loops.yaml`](https://github.com/rorlikowski/stepyard/blob/main/examples/flows/03_loops.yaml) | `stepyard run 03_loops` | `loop:` over a list with `${{ item }}` |
| [`04_http_healthcheck.yaml`](https://github.com/rorlikowski/stepyard/blob/main/examples/flows/04_http_healthcheck.yaml) | `stepyard run 04_http_healthcheck` | `http.request` and branching on `output.status` |
| [`05_scheduled_backup.yaml`](https://github.com/rorlikowski/stepyard/blob/main/examples/flows/05_scheduled_backup.yaml) | `stepyard run 05_scheduled_backup` | A `cron` trigger (needs the daemon running) |
| [`06_approval_gate.yaml`](https://github.com/rorlikowski/stepyard/blob/main/examples/flows/06_approval_gate.yaml) | `stepyard run 06_approval_gate` | Pausing a run with `approval: true` |
| [`07_human_input.yaml`](https://github.com/rorlikowski/stepyard/blob/main/examples/flows/07_human_input.yaml) | `stepyard run 07_human_input` | Prompting an operator with `human.input` |
| [`08_ai_release_notes.yaml`](https://github.com/rorlikowski/stepyard/blob/main/examples/flows/08_ai_release_notes.yaml) | `stepyard run 08_ai_release_notes` | **AI** - git log → LLM → `RELEASE_NOTES.md` |
| [`09_ai_code_review.yaml`](https://github.com/rorlikowski/stepyard/blob/main/examples/flows/09_ai_code_review.yaml) | `stepyard run 09_ai_code_review` | **AI** - review the staged git diff |
| [`10_ai_log_triage.yaml`](https://github.com/rorlikowski/stepyard/blob/main/examples/flows/10_ai_log_triage.yaml) | `stepyard run 10_ai_log_triage` | **AI** - scheduled log triage + Slack alert |
| [`11_event_driven_alert.yaml`](https://github.com/rorlikowski/stepyard/blob/main/examples/flows/11_event_driven_alert.yaml) | `stepyard run 11_event_driven_alert` | Plugin async-generator trigger + custom node (install the example plugin first) |

The AI flows use the built-in `llm.generate` node, which reads `OPENAI_API_KEY` (or `ANTHROPIC_API_KEY`) from the environment:

```bash
export OPENAI_API_KEY=sk-...
stepyard run 08_ai_release_notes
```

## Output shapes quick-reference

| Node | `${{ steps.<id>.output }}` |
|------|----------------------------|
| `shell.run` | `{ stdout, stderr, code }` |
| `http.request` | `{ status, headers, body }` |
| `llm.generate` | `{ output, usage, model, provider }` - read text via `.output.output`, structured fields via `.output.output.<field>` |
| `human.input` | a plain string |
| `file.read` | the file contents (string) |

## Example plugin

`examples/plugin/stepyard-example-plugin/` is a complete, installable plugin that demonstrates:

- A custom node with Pydantic-validated inputs
- Two trigger types: a schedule trigger and an event-stream trigger
- A `StepExecutionHook` for timing instrumentation

Install it into a project:

```bash
stepyard plugin add ./examples/plugin/stepyard-example-plugin
stepyard tools list    # verify the new node and triggers appear
```

See the plugin's own [README](https://github.com/rorlikowski/stepyard/blob/main/examples/plugin/stepyard-example-plugin/README.md) for the full walkthrough.

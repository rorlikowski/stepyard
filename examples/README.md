# Stepyard examples

Copy any of these flows into your project's `flows/` directory (or point
`STEPYARD_FLOWS_DIR` at `examples/flows`) and run them with `stepyard run <name>`.

## Flows

| File | Run with | What it shows |
|------|----------|---------------|
| `flows/01_hello.yaml` | `stepyard run 01_hello` | The basics: `shell.run` and reading `output.stdout` |
| `flows/02_branching.yaml` | `stepyard run 02_branching` | `if:` conditions on `output.code` |
| `flows/03_loops.yaml` | `stepyard run 03_loops` | `loop:` over a list with `${{ item }}` |
| `flows/04_http_healthcheck.yaml` | `stepyard run 04_http_healthcheck` | `http.request` and branching on `output.status` |
| `flows/05_scheduled_backup.yaml` | `stepyard run 05_scheduled_backup` | A `cron` trigger (needs the daemon) |
| `flows/06_approval_gate.yaml` | `stepyard run 06_approval_gate` | Pausing a run with `approval: true` |
| `flows/07_human_input.yaml` | `stepyard run 07_human_input` | Prompting an operator with `human.input` |
| `flows/08_ai_release_notes.yaml` | `stepyard run 08_ai_release_notes` | **AI** - git log → LLM → `RELEASE_NOTES.md` |
| `flows/09_ai_code_review.yaml` | `stepyard run 09_ai_code_review` | **AI** - review the staged git diff |
| `flows/10_ai_log_triage.yaml` | `stepyard run 10_ai_log_triage` | **AI** - scheduled log triage + Slack alert |
| `flows/11_event_driven_alert.yaml` | `stepyard run 11_event_driven_alert` | Custom event trigger + custom node (example plugin) |

The AI flows use the built-in `llm.generate` node, which reads `OPENAI_API_KEY`
(or `ANTHROPIC_API_KEY`) from the environment and returns a dict with generated
text in `output.output` plus token usage in `usage`.

```bash
export OPENAI_API_KEY=sk-...
stepyard run 08_ai_release_notes
```

## Plugin

`plugin/stepyard-example-plugin/` is a complete, installable plugin that adds a
custom node, two kinds of triggers (a schedule and an event stream), and a
timing hook. See its [README](plugin/stepyard-example-plugin/README.md).

## Output shapes cheat-sheet

| Node | `${{ steps.<id>.output }}` |
|------|----------------------------|
| `shell.run` | `{ stdout, stderr, code }` |
| `http.request` | `{ status, headers, body }` |
| `llm.generate` | `{ output, usage, model, provider }` |
| `human.input` | a plain string |
| `file.read` | the file contents (string) |

# Core Concepts

Start here if you already ran `stepyard init` and want the mental model before writing flows.

| Page | What you'll learn |
|---|---|
| [Flows & Steps](flows.md) | YAML anatomy, step fields, outputs |
| [Execution Model](execution-model.md) | Run subprocesses, scheduler/worker, plugin isolation |
| [Expression Engine](expressions.md) | `${{ steps.build.output.code }}` and other context variables |
| [Control Flow](control_flow.md) | `if`, `loop`, `while`, `next`, nested steps, `max_visits` |
| [Triggers & Scheduling](triggers.md) | Built-in `cron` / `interval` / `startup` plus plugin event triggers |
| [Error Handling](errors.md) | `continue_on_error`, `retry`, error hierarchy |

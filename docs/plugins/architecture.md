# Plugin Architecture

This page explains how Stepyard discovers, isolates, and invokes plugins.

---

## Discovery

Stepyard uses `setuptools` entry points for plugin discovery. When you call `stepyard tools list` (or when the engine starts), it calls `importlib.metadata.entry_points()` and loads every group that Stepyard understands:

| Entry-point group | What it registers |
|---|---|
| `stepyard.plugins` | Modules containing node functions decorated with `@node` |
| `stepyard.triggers` | Trigger functions decorated with `@trigger` |
| `stepyard.hooks` | A hook **instance** implementing `StepExecutionHook` |
| `stepyard.commands` | Click command objects added to the top-level CLI |

For each loaded module, Stepyard collects all decorated objects and stores them in a `CapabilityRegistry`.

### `DiscoveryReport`

If a plugin fails to import (missing dependency, syntax error), the error is captured in a `DiscoveryReport` rather than crashing the engine. Check `stepyard doctor` for environment health, and review the scheduler log (`.stepyard/logs/scheduler.log`) or run with `--verbose` to see import tracebacks.

---

## Isolation

Plugins are installed in a project-local virtualenv at `.stepyard/env`. This keeps plugin dependencies isolated from your system Python and from each other. Stepyard adds `.stepyard/env/lib/python*/site-packages` to `sys.path` at startup.

```
my-project/
└── .stepyard/
    └── env/                       # isolated virtualenv
        └── lib/python3.12/
            └── site-packages/
                ├── stepyard_plugin_telegram/
                └── stepyard_plugin_aws/
```

---

## Invocation pipeline

When a step runs, the engine goes through the following steps:

```
YAML step
   │
   ▼
ConditionEvaluator.evaluate_if()     ← skip if `if` is falsy
   │
   ▼
NodeInvoker.invoke()
   │
   ├─ In-process?  ──► plugins/execution.py::invoke_node()
   │                        │
   │                        ├─ Pydantic validation
   │                        ├─ NodeContext injection
   │                        └─ call @node function (sync or async)
   │
   └─ Subprocess?  ──► spawn `python -m stepyard.core.node_executor`
                            │
                            └─ same invoke_node() path
   │
   ▼
StepRecorder.complete() / .fail()   ← persist result to SQLite
   │
   ▼
HookManager.after_execute()         ← call all registered hooks
```

### In-process vs subprocess

By default, nodes run **in-process** in the flow runner subprocess. This is fast but means a crashing node (e.g. a C extension that segfaults) can kill the flow.

Nodes provided by plugins installed in the isolated `.stepyard/env` virtualenv run in a **separate subprocess** instead. The invoker checks the capability's `info.isolated` flag (set during discovery for entry points loaded from the plugin virtualenv) and, when set, spawns `python -m stepyard.core.node_executor` using the virtualenv's interpreter. This both isolates plugin dependencies and contains crashes - if the subprocess dies, the step is marked `failed`.

---

## Capability naming

Node names use a `namespace.action` convention:

- `namespace` - usually the plugin or service name (`slack`, `aws`, `redis`)
- `action` - the verb (`send`, `upload`, `query`)

Names must be globally unique within a project. If two plugins register the same name, `PluginHost.discover()` raises a `PluginError` listing both packages.

---

## Lockfile

`stepyard.lock` records the exact version of every installed plugin in pip-requirements format. Commit it to version control so every developer and CI environment uses identical plugins:

```
stepyard-plugin-telegram==1.0.0
stepyard-plugin-aws==0.3.2
```

Sync from the lockfile:

```bash
stepyard plugin sync
```

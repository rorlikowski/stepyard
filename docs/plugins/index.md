# Plugin Development

Plugins are Python packages that register new nodes, triggers, and hooks with Stepyard. They are distributed via PyPI, installed into a project-local virtualenv, and discovered automatically through `setuptools` entry points.

## Pages in this section

| Page | What you'll find |
|---|---|
| [Quick Start](creating.md) | Scaffold, write, install, and use a plugin in 5 minutes |
| [Triggers & Hooks](triggers_hooks.md) | Build event-driven triggers and lifecycle hooks |
| [SDK Reference](sdk.md) | Complete API: `@node`, `@trigger`, `StepExecutionHook`, `NodeResult`, `NodeContext` |
| [Testing](testing.md) | Test helpers: `invoke_node`, `fake_context`, `collect_trigger` |
| [Real-world Examples](examples.md) | OpenAI, Postgres, ETL, AWS, and Slack plugin patterns |
| [Architecture](architecture.md) | How discovery, isolation, and the invocation pipeline work |
| [FAQ](faq.md) | Common questions and troubleshooting |

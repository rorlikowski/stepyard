# stepyard-example-plugin

A complete, minimal example of a Stepyard plugin. It ships:

| Kind | Name | File |
|------|------|------|
| Node | `text.wordcount` | `stepyard_example_plugin/nodes.py` |
| Node | `slack.notify` | `stepyard_example_plugin/nodes.py` |
| Trigger (schedule) | `schedule.weekdays` | `stepyard_example_plugin/triggers.py` |
| Trigger (event) | `watch.file` | `stepyard_example_plugin/triggers.py` |
| Hook | `TimingHook` | `stepyard_example_plugin/hooks.py` |

## Install it into a project

From the root of a Stepyard project:

```bash
stepyard plugin add ./examples/plugin/stepyard-example-plugin
stepyard tools list          # confirm the new nodes/triggers appear
```

While developing a local plugin, re-run `plugin add` after you change the source
- installs are not editable, so this is how Stepyard picks up your latest code.

## Use it

```yaml title="flows/standup.yaml"
name: standup
trigger:
  uses: schedule.weekdays      # every weekday at 09:00 UTC
  with:
    at: "09:00"
steps:
  - id: ping
    uses: slack.notify
    with:
      text: "Good morning! Daily standup in 15 minutes."
```

```yaml title="flows/wordcount.yaml"
name: wordcount
steps:
  - id: count
    uses: text.wordcount
    with:
      text: "the quick brown fox"
  - id: show
    uses: shell.run
    with:
      command: "echo 'words=${{ steps.count.output.words }} chars=${{ steps.count.output.chars }}'"
```

## How registration works

Stepyard discovers plugins through Python entry points (see `pyproject.toml`):

- `stepyard.plugins` → module(s) containing `@node` functions
- `stepyard.triggers` → module(s) containing `@trigger` functions
- `stepyard.hooks` → a hook **instance** (e.g. `...hooks:timing_hook`)

Nodes and triggers are matched by the `name=` you pass to the decorator, so the
entry-point key can be anything unique.

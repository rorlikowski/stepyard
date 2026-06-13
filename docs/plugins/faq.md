# Plugin FAQ & Troubleshooting

---

## My node isn't showing up in `stepyard tools list`

**Check 1 - entry point group:**

```toml title="pyproject.toml"
[project.entry-points."stepyard.plugins"]   # group is "stepyard.plugins" (triggers use "stepyard.triggers", hooks "stepyard.hooks")
my_plugin = "my_plugin.nodes"
```

**Check 2 - installed in the right env:**

```bash
stepyard plugin add ./my-plugin-dir
# re-run after source edits (installs are not editable)
```

**Check 3 - run doctor:**

```bash
stepyard doctor
```

Broken plugins (import errors, missing dependencies) appear here with full tracebacks.

---

## My node gets a `ValidationError` before it runs

This means the inputs from your YAML don't match the Python type hints.

Common causes:

- Passing a string `"42"` where `int` is expected - usually fine, Pydantic coerces it, but `"not-a-number"` fails.
- Missing a required parameter in the `with:` block.
- Passing a YAML object where a `list` is expected.

Run `stepyard validate flows/my_flow.yaml` to see validation errors before running.

---

## How do I pass a Python `dict` from one step to another?

`http.request` and other nodes return the response body as a parsed dict. Access nested fields with dot notation or bracket notation:

```yaml
command: echo "${{ steps.fetch.output.body.user.email }}"
command: echo "${{ steps.fetch.output.body['user']['email'] }}"
```

If the field name contains a hyphen or space, use brackets:

```yaml
value: ${{ steps.fetch.output.body['content-type'] }}
```

---

## My async node isn't running concurrently with other steps

Steps in Stepyard run **sequentially by default** - one after another in YAML order. Async nodes are useful for I/O-bound work within a single step (e.g. making multiple HTTP calls inside one node), not for parallelising steps.

To run multiple flows concurrently, run them as separate flows and use the scheduler.

---

## Can I import from my plugin's own package inside a node?

Yes. The plugin package is installed in `.stepyard/env`. Stepyard adds the site-packages to `sys.path` before invoking nodes.

```python
from my_plugin.utils import helper_function   # fine
```

---

## How do I pass a large binary payload between steps?

Store it in a temporary file and pass the path. The `file.read` and `file.write` nodes are designed for this:

```yaml
  - id: download
    uses: http.download
    with:
      url: https://example.com/large-file.bin
      dest: /tmp/large-file.bin

  - id: process
    uses: shell.run
    with:
      command: ./process-binary /tmp/large-file.bin
```

---

## My hook runs for every step - how do I limit it to specific nodes?

Hooks receive the `step` object with the `uses` field:

```python
async def before_execute(self, ctx, step, inputs):
    if getattr(step, "uses", "") != "myservice.sensitive_action":
        return None  # skip for all other nodes
    # ... hook logic
```

---

## How do I see what a plugin registered?

```bash
stepyard tools list                   # all registered nodes and triggers
stepyard doctor                       # overall environment health (DB, virtualenv, projects)
```

---

## Can a plugin add new CLI commands?

Yes. Register a Click command under the `stepyard.commands` entry-point group:

```python title="my_plugin/cli.py"
import click

@click.command("mycommand")
@click.argument("arg")
def mycommand(arg):
    """My custom command."""
    click.echo(f"Hello {arg}")
```

```toml title="pyproject.toml"
[project.entry-points."stepyard.commands"]
mycommand = "my_plugin.cli:mycommand"
```

After installing the plugin, `stepyard mycommand` is available.

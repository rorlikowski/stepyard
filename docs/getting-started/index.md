# Getting Started

Install Stepyard, scaffold a project, and run your first flow in under five minutes:

```bash
pip install stepyard
stepyard init my-project && cd my-project
stepyard run hello
```

## Step-by-step path

1. **[Installation](installation.md)** - install with `pip` or `uv`, initialise a project directory, and run your first flow.
2. **[Tutorial: Build a CI Pipeline](tutorial.md)** - write a multi-step flow from scratch, using expressions, conditionals, loops, retries, and the scheduler.
3. **[Tutorial: Your First Plugin](first-plugin.md)** - extend Stepyard with a custom Python node and learn the full plugin lifecycle.

## Already know the basics?

Jump to what you need:

- **[Expression engine](../concepts/expressions.md)** - how `${{ }}` expressions work and what context variables are available
- **[Control flow](../concepts/control_flow.md)** - `if`, `loop`, `while`, `next`
- **[Built-in nodes reference](../nodes/builtin.md)** - every node that ships with Stepyard
- **[CLI reference](../cli/reference.md)** - every command and flag

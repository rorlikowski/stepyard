# Installation

## Requirements

- Python 3.10 or newer
- pip or [uv](https://github.com/astral-sh/uv) (recommended)

## Install

=== "uv (recommended)"

    ```bash
    uv pip install stepyard
    ```

=== "pip"

    ```bash
    pip install stepyard
    ```

=== "from source"

    ```bash
    git clone https://github.com/rorlikowski/stepyard
    cd stepyard
    pip install -e .
    ```

Verify the installation:

```bash
stepyard --version
# stepyard 0.1.dev1+g<hash>
```

## Initialise a project

The `stepyard init` command creates a project directory with everything Stepyard needs:

```bash
stepyard init my-project
cd my-project
```

This creates:

```
my-project/
├── .stepyard/          # runtime data (database, logs, plugin env)
├── .gitignore         # pre-configured to ignore .stepyard/
└── flows/
    └── hello.yaml     # a working example flow
```

Run the example immediately:

```bash
stepyard run hello
```

```
✓  greet    0.1 s

Flow completed in 0.1 s
```

## Editor support (optional)

Generate a JSON Schema for your flows so editors can validate them inline:

```bash
stepyard schema
```

This writes `.stepyard/flow.schema.json`. Add the modeline at the top of each flow file (paths are relative to the file location - use `../` for files inside `flows/`):

```yaml
# yaml-language-server: $schema=../.stepyard/flow.schema.json
```

## What's next?

Follow the **[Tutorial: Build a CI Pipeline](tutorial.md)** to write a real multi-step flow from scratch.

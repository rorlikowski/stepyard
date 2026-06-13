# Contributing to Stepyard

Thank you for your interest in contributing! This document explains how to set up the development environment, run the tests, and submit changes.

---

## Development setup

**Requirements:** Python 3.10+, [uv](https://github.com/astral-sh/uv) (recommended) or pip.

```bash
git clone https://github.com/rorlikowski/stepyard
cd stepyard

# Install all dependencies (including dev and docs extras)
uv pip install -e ".[dev,docs]"

# Verify the install
uv run stepyard doctor
```

---

## Running the tests

```bash
# All unit tests
pytest

# With coverage report
pytest --cov=src/stepyard --cov=src/stepyard_builtin --cov-report=term-missing

# Single file
pytest tests/unit/test_flow.py -v
```

---

## Linting and formatting

```bash
# Lint
ruff check src/ tests/

# Type-check
mypy src/stepyard src/stepyard_builtin

# Format
ruff format src/ tests/
```

All checks run automatically in CI on every pull request.

---

## Docs

```bash
# Preview locally
uv run mkdocs serve

# Build static site
uv run mkdocs build
```

---

## Submitting a pull request

1. Fork the repository and create a branch from `main`.
2. Make your changes, add tests, and ensure all checks pass.
3. Open a pull request against `main` with a clear description of what you changed and why.
4. A maintainer will review and merge it.

---

## Reporting bugs

Open an issue on GitHub with:
- The `stepyard --version` output
- The flow YAML (redact any secrets)
- The full error output or `stepyard logs <run-id>` output

---

## Coding conventions

- Python 3.10+, type-annotated, `ruff`-formatted.
- New nodes go in `src/stepyard_builtin/` and must be registered in `pyproject.toml`.
- New CLI commands use `click` and go under `src/stepyard/cli/commands/`.
- Write tests for every new feature under `tests/unit/` or `tests/integration/`.

# How to manage installed plugins

Stepyard installs plugins into an isolated virtualenv at `.stepyard/env`, separate from your system Python. The lockfile `stepyard.lock` in the project root records every installed package so your team can reproduce the exact environment.

---

## Install a plugin

```bash
stepyard plugin add stepyard-plugin-telegram
```

Install a specific version:

```bash
stepyard plugin add "stepyard-plugin-telegram==1.2.3"
```

Install from a local path (during development):

```bash
stepyard plugin add ./my-plugin-dir
```

Install from a Git repository:

```bash
stepyard plugin add "git+https://github.com/my-org/stepyard-plugin-telegram"
```

After installation, the `stepyard.lock` file is updated automatically.

---

## List installed plugins

`stepyard tools list` shows every registered **node and trigger** (built-in plus plugins). `stepyard plugin list` shows installed **packages**:

```bash
stepyard tools list
```

```
Node                      Version    Source
──────────────────────────────────────────────────────────
shell.run                 builtin    builtin
http.request              builtin    builtin
llm.generate              builtin    builtin
human.input               builtin    builtin
human.approval            builtin    builtin
telegram.send_message     1.0.0      stepyard-plugin-telegram
aws.fetch_secret          0.3.2      stepyard-plugin-aws
aws.s3_upload             0.3.2      stepyard-plugin-aws
```

```bash
stepyard plugin list --plain
```

```
Package                    Version    Capabilities                         Origin
stepyard-plugin-telegram   1.0.0      telegram.send_message                pypi
stepyard-plugin-aws        0.3.2      aws.fetch_secret, aws.s3_upload      pypi
```

---

## Remove a plugin

```bash
stepyard plugin remove stepyard-plugin-telegram
```

This uninstalls the package from `.stepyard/env` and removes it from `stepyard.lock`.

---

## Sync from lockfile

When you clone a project or pull new changes, sync the plugin environment from the lockfile:

```bash
stepyard plugin sync
```

This installs all packages listed in `stepyard.lock` in one step - equivalent to `pip install -r requirements.txt` for plugins.

---

## Iterating on a local plugin

Plugins are installed into `.stepyard/env` as regular (non-editable) packages, so
after editing a local plugin's source, re-run `plugin add` to pick up the
changes and re-discover its capabilities:

```bash
stepyard plugin add ../my-plugin-dir
```

---

## Run `doctor` to check for broken plugins

```bash
stepyard doctor
```

Lists plugins that failed to load (with full tracebacks) and suggests fixes.

---

## The lockfile

`stepyard.lock` lives in the project root and lists one pip package spec per line
(local paths, PyPI names, or Git URLs):

```text title="stepyard.lock"
stepyard-plugin-telegram==1.0.0
./plugins/my-local-plugin
```

Commit it to version control so every developer and CI environment uses the same plugins.

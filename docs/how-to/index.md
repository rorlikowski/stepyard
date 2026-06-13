# How-to Guides

Task-focused recipes. Each page includes copy-paste YAML or CLI commands.

| Guide | What you'll do |
|---|---|
| [Schedule flows](scheduling.md) | `stepyard service start` + `cron` / `interval` triggers |
| [Manage secrets](secrets.md) | `${{ env.TOKEN }}` vs `${{ vars.TOKEN }}` without hardcoding |
| [Human approvals](approvals.md) | `approval: true` + `stepyard approvals` |
| [Dry-run & debugging](dry-run.md) | `stepyard validate`, `--dry-run`, `show`, `replay` |
| [Write & test a plugin](writing-plugins.md) | `@node`, tests with `run_node` |
| [Manage installed plugins](plugin-management.md) | `stepyard plugin add` / `sync` / `stepyard.lock` |

# Stepyard

**YAML pipelines. Python plugins. Runs on your machine - no server to set up, no cloud account needed.**

Stepyard is an automation runner for developers. Pipelines live as YAML files in your repo. You extend them with plain Python functions. Everything runs from the CLI or a local daemon - on your machine or a server you own.

<div align="center">
  <img src="assets/demo.gif" alt="Stepyard demo - status, run, logs" style="border-radius:8px;max-width:100%;"/>
</div>

```bash
pip install stepyard
stepyard init my-project && cd my-project
stepyard run hello
```

---

A deploy pipeline: build and push a container, run a smoke test, and post the result to Slack. One YAML file, no supporting scripts.

```yaml title="flows/deploy.yaml"
name: deploy
description: Build, push, and verify the production container.

steps:
  - id: build
    uses: shell.run
    with:
      command: docker build -t myapp:${{ env.GIT_SHA }} .

  - id: push
    uses: shell.run
    with:
      command: docker push myapp:${{ env.GIT_SHA }}

  - id: smoke_test
    uses: http.request
    with:
      url: https://staging.myapp.com/healthz
      method: GET

  - id: notify
    uses: llm.generate               # built-in - no plugin needed
    with:
      model: gpt-4o-mini
      prompt: |
        Summarise this deploy result in one sentence for Slack:
        HTTP status: ${{ steps.smoke_test.output.status }}
        SHA: ${{ env.GIT_SHA }}

  - id: post_to_slack
    uses: http.request
    with:
      url: ${{ env.SLACK_WEBHOOK }}
      method: POST
      json_body:
        text: ${{ steps.notify.output.output }}
```

Run it:

```bash
GIT_SHA=$(git rev-parse --short HEAD) stepyard run deploy
```

```
✓  build          12.4 s
✓  push            4.1 s
✓  smoke_test      0.3 s
✓  notify          0.9 s
✓  post_to_slack   0.2 s

Flow completed in 18.0 s
```

---

## Why Stepyard?

<div class="grid cards" markdown>

-   **Flows are files in your repo**

    Steps, conditions, loops, and retries are plain YAML keys - no proprietary DSL. Version-control them alongside your code and validate them with `stepyard validate`.

-   **Extend with plain Python**

    One `@node` decorator turns any function into a reusable step. Inputs are type-validated automatically; plugin dependencies are isolated so they never conflict with Stepyard's own.

-   **Nothing leaves your machine**

    State is stored in a local SQLite database. Data goes out only if a step in your flow explicitly sends it.

-   **Scheduled and on-demand execution**

    `cron`, `interval`, and `startup` triggers. Run `stepyard service start` and your flows execute on schedule - no external service or cloud account needed.

</div>

---

## Real-world examples

### Daily database backup

```yaml title="flows/pg_backup.yaml"
name: pg_backup
trigger:
  uses: cron
  with:
    schedule: "0 3 * * *"   # every day at 03:00

steps:
  - id: dump
    uses: shell.run
    with:
      command: pg_dump ${{ env.DATABASE_URL }} | gzip > /tmp/backup.sql.gz

  - id: upload
    uses: shell.run
    with:
      command: |
        aws s3 cp /tmp/backup.sql.gz \
          s3://${{ env.BACKUP_BUCKET }}/db/$(date +%Y-%m-%d).sql.gz

  - id: cleanup
    uses: shell.run
    with:
      command: rm -f /tmp/backup.sql.gz
```

### Automated code review on every PR

Fetch the diff via the GitHub API, review it with an LLM, and post a comment back - all with built-in nodes, no additional service.

```yaml title="flows/pr_review.yaml"
name: pr_review
description: Review a PR diff with an LLM and post a comment if issues are found.
# Run: PR=42 GITHUB_REPO=my-org/my-repo stepyard run pr_review

steps:
  - id: diff
    uses: http.request
    with:
      url: https://api.github.com/repos/${{ env.GITHUB_REPO }}/pulls/${{ env.PR }}/files
      headers:
        Authorization: Bearer ${{ env.GITHUB_TOKEN }}
        Accept: application/vnd.github+json

  - id: review
    uses: llm.generate
    with:
      model: gpt-4o
      system_prompt: |
        You are a senior engineer doing a code review.
        Be concise. If everything looks good reply with exactly: LGTM
      prompt: |
        Review this pull request for bugs, security issues, and obvious mistakes:

        ${{ steps.diff.output.body }}

  - id: post_comment
    if: ${{ steps.review.output.output != "LGTM" }}
    uses: http.request
    with:
      url: https://api.github.com/repos/${{ env.GITHUB_REPO }}/issues/${{ env.PR }}/comments
      method: POST
      headers:
        Authorization: Bearer ${{ env.GITHUB_TOKEN }}
        Accept: application/vnd.github+json
      json_body:
        body: ${{ steps.review.output.output }}
```

### Multi-environment deployment with rollback

```yaml title="flows/deploy_multi.yaml"
name: deploy_multi

steps:
  - id: deploy_staging
    uses: shell.run
    with:
      command: kubectl apply -f k8s/staging/

  - id: integration_tests
    uses: shell.run
    continue_on_error: true
    with:
      command: pytest tests/integration/ -q

  - id: deploy_production
    if: ${{ steps.integration_tests.output.code == 0 }}
    uses: shell.run
    with:
      command: kubectl apply -f k8s/production/

  - id: rollback
    if: ${{ steps.integration_tests.output.code != 0 }}
    uses: shell.run
    with:
      command: kubectl rollout undo deployment/myapp -n staging
```

---

## Documentation overview

| Section | What you'll find |
|---|---|
| [Getting Started](getting-started/index.md) | Installation and two full tutorials |
| [Core Concepts](concepts/index.md) | Flows, expressions, control flow, triggers, error handling |
| [How-to Guides](how-to/index.md) | Practical recipes - scheduling, secrets, approvals, debugging |
| [Built-in Nodes](nodes/builtin.md) | Complete reference for all nodes that ship with Stepyard |
| [Plugin Development](plugins/creating.md) | Write, test, package and publish your own plugins |
| [CLI Reference](cli/reference.md) | Every command, flag, and exit code |

---

## Compatibility

| | |
|---|---|
| Python | 3.10 · 3.11 · 3.12 · 3.13 |
| OS | macOS · Linux · Windows (WSL) |
| Storage | SQLite (default) |
| License | MIT |

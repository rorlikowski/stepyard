# Built-in Nodes Reference

All nodes listed here ship with Stepyard - no extra plugin required.

---

## Shell & System

### `shell.run`

Executes a command in the system shell and captures the output.

**Parameters:**

| Name | Type | Default | Description |
|---|---|---|---|
| `command` | `string` | required | The command to run |
| `cwd` | `string` | project dir | Working directory. Must be inside the project dir unless `allow_outside_project: true` |
| `env` | `mapping` | `{}` | Extra environment variables to inject |
| `shell` | `bool` | `false` | Run through a shell interpreter (allows `&&`, `|`, etc.) |
| `allow_outside_project` | `bool` | `false` | Allow `cwd` outside project root |

**Outputs:**

| Name | Type | Description |
|---|---|---|
| `stdout` | `string` | Combined stdout and stderr |
| `stderr` | `string` | Always `""` (stderr is merged into `stdout`) |
| `code` | `int` | Exit code (0 = success) |

**Examples:**

=== "Simple command"

    ```yaml
      - id: whoami
        uses: shell.run
        with:
          command: whoami
    ```

=== "With working directory"

    ```yaml
      - id: install
        uses: shell.run
        with:
          command: npm install
          cwd: frontend/
    ```

=== "With injected secrets"

    ```yaml
      - id: migrate
        uses: shell.run
        with:
          command: alembic upgrade head
          env:
            DATABASE_URL: ${{ env.DATABASE_URL }}
    ```

=== "Shell pipeline"

    ```yaml
      - id: top_errors
        uses: shell.run
        with:
          command: cat /var/log/app.log | grep ERROR | tail -20
          shell: true
    ```

=== "Check exit code"

    ```yaml
      - id: test
        uses: shell.run
        continue_on_error: true
        with:
          command: pytest tests/ -q

      - id: on_fail
        if: ${{ steps.test.output.code != 0 }}
        uses: shell.run
        with:
          command: echo "Tests failed!"
    ```

!!! warning "Security: `shell: true`"
    When `shell: true` is set, the command is passed to `/bin/sh -c`. This enables shell metacharacters (`&&`, `|`, `$(...)`) but also opens the door to command injection if the command contains untrusted user input. Prefer `shell: false` (the default) and pass arguments as separate tokens.

---

## HTTP & Network

### `http.request`

Makes an HTTP request and returns the response.

**Parameters:**

| Name | Type | Default | Description |
|---|---|---|---|
| `url` | `string` | required | Target URL (`http://` or `https://` only) |
| `method` | `string` | `GET` | HTTP method |
| `headers` | `mapping` | `{}` | Request headers |
| `json_body` | `mapping` | `null` | JSON payload (sets `Content-Type: application/json`) |
| `data` | `mapping` | `null` | Form data (sets `Content-Type: application/x-www-form-urlencoded`) |

**Outputs:**

| Name | Type | Description |
|---|---|---|
| `status` | `int` | HTTP status code |
| `body` | `any` | Parsed JSON object or raw string |
| `headers` | `mapping` | Response headers |
| `error` | `string` | Error message on HTTP error (4xx/5xx) |

**Examples:**

=== "GET request"

    ```yaml
      - id: fetch
        uses: http.request
        with:
          url: https://api.github.com/repos/my-org/my-repo
          headers:
            Accept: application/vnd.github+json
            Authorization: Bearer ${{ env.GITHUB_TOKEN }}
    ```

=== "POST with JSON body"

    ```yaml
      - id: create_issue
        uses: http.request
        with:
          url: https://api.github.com/repos/my-org/my-repo/issues
          method: POST
          headers:
            Authorization: Bearer ${{ env.GITHUB_TOKEN }}
          json_body:
            title: Automated report
            body: ${{ steps.report.output.output }}
            labels:
              - automated
    ```

=== "Slack webhook"

    ```yaml
      - id: notify
        uses: http.request
        with:
          url: ${{ env.SLACK_WEBHOOK }}
          method: POST
          json_body:
            text: "✅ Deploy complete"
    ```

=== "Check status code"

    ```yaml
      - id: check
        uses: http.request
        continue_on_error: true
        with:
          url: https://myapp.com/healthz

      - id: alert
        if: ${{ steps.check.output.status != 200 }}
        uses: http.request
        with:
          url: ${{ env.PAGERDUTY_WEBHOOK }}
          method: POST
          json_body:
            summary: Healthcheck failed
            severity: critical
    ```

---

### `http.download`

Downloads a file from a URL to a local path.

**Parameters:**

| Name | Type | Default | Description |
|---|---|---|---|
| `url` | `string` | required | URL to download |
| `dest` | `string` | required | Local destination path |

**Output:** The absolute path of the saved file (string).

```yaml
  - id: get_binary
    uses: http.download
    with:
      url: https://releases.example.com/app-v1.2.3-linux-amd64
      dest: /tmp/app

  - id: install
    uses: shell.run
    with:
      command: chmod +x /tmp/app && sudo mv /tmp/app /usr/local/bin/app
```

---

## Files

### `file.read`

Reads the contents of a file.

**Parameters:**

| Name | Type | Default | Description |
|---|---|---|---|
| `path` | `string` | required | File path |
| `encoding` | `string` | `utf-8` | File encoding |

**Output:** File contents as a string.

```yaml
  - id: read_config
    uses: file.read
    with:
      path: config/settings.json

  - id: process
    uses: shell.run
    with:
      # file.read returns the file contents as a string in `output`.
      command: echo "Config loaded successfully."
```

---

### `file.write`

Writes a string to a file. Creates parent directories if needed.

**Parameters:**

| Name | Type | Default | Description |
|---|---|---|---|
| `path` | `string` | required | File path |
| `content` | `string` | required | Content to write |
| `encoding` | `string` | `utf-8` | File encoding |

**Output:** Absolute path of the written file (string).

```yaml
  - id: write_report
    uses: file.write
    with:
      path: reports/deploy-${{ env.GIT_SHA }}.txt
      content: |
        Deploy report
        SHA: ${{ env.GIT_SHA }}
        Status: ${{ steps.deploy.output.stdout }}
```

---

### `file.list`

Lists files and directories at a path.

**Parameters:**

| Name | Type | Default | Description |
|---|---|---|---|
| `path` | `string` | required | Directory path |

**Output:** List of filenames (list of strings).

```yaml
  - id: list_reports
    uses: file.list
    with:
      path: reports/

  - id: count
    uses: shell.run
    with:
      # file.list returns a list of names in `output`.
      command: echo "Reports found: ${{ steps.list_reports.output }}"
```

---

## Text

### `text.template`

Renders a string template with variable substitution using Python's `string.Template` (`$var` or `${var}` syntax).

**Parameters:**

| Name | Type | Default | Description |
|---|---|---|---|
| `template` | `string` | required | Template string with `$var` placeholders |
| `variables` | `mapping` | required | Dict of substitution values |

**Output:** Rendered string.

```yaml
  - id: compose_email
    uses: text.template
    with:
      template: |
        Hi $name,

        Your $resource has been provisioned.
        Access it at: $url

        Regards, The Ops Team
      variables:
        name: ${{ steps.user.output.name }}
        resource: PostgreSQL database
        url: ${{ steps.provision.output.connection_url }}
```

---

### `text.replace`

Replaces all occurrences of a substring in a string.

**Parameters:**

| Name | Type | Default | Description |
|---|---|---|---|
| `text` | `string` | required | Input text |
| `old` | `string` | required | Substring to find |
| `new` | `string` | required | Replacement string |

**Output:** Modified string.

```yaml
  - id: sanitize
    uses: text.replace
    with:
      text: ${{ steps.fetch.output.body.content }}
      old: "REDACTED_TOKEN"
      new: ${{ env.REAL_TOKEN }}
```

---

## AI / LLM

### `llm.generate`

Calls an LLM provider and returns generated text or optional structured JSON output.

**Parameters:**

| Name | Type | Default | Description |
|---|---|---|---|
| `prompt` | `string` | required | User message |
| `model` | `string` | `gpt-3.5-turbo` | Model ID |
| `system_prompt` | `string` | `null` | System instruction |
| `provider` | `string` | `openai` | `openai`, `anthropic`, `ollama`, or `openai-compatible` |
| `api_key` | `string` | env var | API key. Falls back to provider env vars (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`). Ollama accepts a placeholder key. |
| `base_url` | `string` | provider default | Custom API base URL (required for `openai-compatible`) |
| `max_tokens` | `int` | `1024` | Maximum tokens to generate |
| `temperature` | `float` | `null` | Optional sampling temperature |
| `timeout` | `float` | `60.0` | HTTP request timeout in seconds |
| `schema` | `mapping` | `null` | Optional JSON Schema subset for structured output |
| `schema_name` | `string` | `structured_output` | Name used by providers when requesting structured output |

**Output:** Always a mapping with generated content and token usage:

| Field | Type | Description |
|---|---|---|
| `output` | `string` or `mapping` | Generated text, or validated JSON object when `schema` is set |
| `usage.input_tokens` | `int` or `null` | Prompt/input tokens reported by the provider |
| `usage.output_tokens` | `int` or `null` | Completion/output tokens reported by the provider |
| `usage.total_tokens` | `int` or `null` | Total tokens (sum when the provider omits it) |
| `model` | `string` | Model ID used for the request |
| `provider` | `string` | Provider name used for the request |

Token usage is also written to step logs (`stepyard logs <run-id>`).

Read generated text as `${{ steps.<id>.output.output }}`. With `schema`, read fields as `${{ steps.<id>.output.output.<field> }}` (e.g. `${{ steps.classify.output.output.category }}`).

**Examples:**

=== "Summarise logs"

    ```yaml
      - id: get_logs
        uses: shell.run
        with:
          command: tail -n 100 /var/log/app.log

      - id: summarise
        uses: llm.generate
        with:
          model: gpt-4o-mini
          system_prompt: You are a DevOps expert. Be concise.
          prompt: |
            Summarise the following application logs in 3 bullet points.
            Highlight any errors or warnings.

            ${{ steps.get_logs.output.stdout }}
    ```

=== "AI code reviewer"

    ```yaml
      - id: diff
        uses: shell.run
        with:
          command: git diff origin/main...HEAD

      - id: review
        uses: llm.generate
        with:
          model: gpt-4o
          prompt: |
            Review this diff for bugs and security issues.
            Reply with "LGTM" if everything looks fine, otherwise
            list the issues clearly.

            ${{ steps.diff.output.stdout }}

      - id: post_review
        if: ${{ steps.review.output.output != "LGTM" }}
        uses: http.request
        with:
          url: ${{ env.GITHUB_COMMENT_URL }}
          method: POST
          json_body:
            body: ${{ steps.review.output.output }}
    ```

=== "Anthropic / Claude"

    ```yaml
      - id: classify
        uses: llm.generate
        with:
          provider: anthropic
          model: claude-3-5-sonnet-20241022
          prompt: Classify this support ticket into: bug, feature, question.
    ```

=== "Local model (Ollama)"

    ```yaml
      - id: local_llm
        uses: llm.generate
        with:
          provider: ollama
          model: llama3.2
          base_url: http://localhost:11434/v1
          prompt: What is 2+2?
    ```

=== "Structured output"

    ```yaml
      - id: classify
        uses: llm.generate
        with:
          provider: ollama
          model: llama3.2
          prompt: Classify this support ticket into bug, feature, or question.
          schema:
            type: object
            properties:
              category:
                type: string
                enum: [bug, feature, question]
              priority:
                type: string
                enum: [low, medium, high]
              summary:
                type: string
            required: [category, priority, summary]

      - id: route
        if: ${{ steps.classify.output.output.category == "bug" }}
        uses: shell.run
        with:
          command: echo "Routing to engineering"
    ```

!!! note "API key handling"
    The `api_key` field is automatically redacted before being persisted to the database. Even if you pass it explicitly in `with:`, it won't appear in `stepyard logs` output.

---

## Human interaction

### `human.approval`

Records an approval message as a step output. On its own this node does **not** suspend the run - to actually pause a step for a human decision, set `approval: true` on the step (handled by the built-in `ApprovalHook`), which puts the run into `waiting_for_approval` until someone acts via `stepyard approvals`.

**Parameters:**

| Name | Type | Default | Description |
|---|---|---|---|
| `message` | `string` | required | Message shown to the operator |

**Output:** A string confirming the approval request was recorded (e.g. `"Waiting for approval: <message>"`). The actual approve/reject decision is handled by the `ApprovalHook` via `stepyard approvals` - use `approval: true` on the step to pause the run until someone acts.

```yaml
  - id: gate
    uses: human.approval
    approval: true        # required for the run to actually pause here
    with:
      message: |
        Deploy **${{ env.SERVICE }}:${{ env.VERSION }}** to production?

        Staging tests: ${{ steps.test.output.code == 0 }}
        Artifact size: ${{ steps.build.output.stdout }}

  - id: deploy
    uses: shell.run
    with:
      command: kubectl apply -f k8s/production/
```

See [How to require human approvals](../how-to/approvals.md) for the full workflow.

---

### `human.input`

Prompts the operator for text input. Supports free text, secret input, and choice menus.

**Parameters:**

| Name | Type | Default | Description |
|---|---|---|---|
| `prompt` | `string` | required | Prompt shown to the operator |
| `default` | `string` | `""` | Value used if the operator submits empty input |
| `required` | `bool` | `true` | Raise an error if no value is provided |
| `secret` | `bool` | `false` | Hide typed characters (for passwords) |
| `choices` | `list[string]` | `null` | Restrict input to one of these values |

**Output:** The entered string value.

**Examples:**

=== "Free text"

    ```yaml
      - id: ask_reason
        uses: human.input
        with:
          prompt: Reason for this deployment

      - id: tag
        uses: shell.run
        with:
          command: |
            git tag -a v${{ vars.version }} \
              -m "${{ steps.ask_reason.output }}"
    ```

=== "Choice menu"

    ```yaml
      - id: ask_env
        uses: human.input
        with:
          prompt: Deploy to which environment?
          choices:
            - staging
            - canary
            - production
          required: true

      - id: deploy
        uses: shell.run
        with:
          command: ./deploy.sh --env ${{ steps.ask_env.output }}
    ```

=== "Secret input"

    ```yaml
      - id: ask_token
        uses: human.input
        with:
          prompt: GitHub Personal Access Token
          secret: true
          required: true

      - id: clone
        uses: shell.run
        with:
          command: git clone https://x-token:${{ steps.ask_token.output }}@github.com/org/repo
    ```

---

## Flow control

### `flow.route`

Builds a structured routing object pointing to a target step. Used with `next:` expressions for readable graph transitions.

**Parameters:**

| Name | Type | Default | Description |
|---|---|---|---|
| `target` | `string` | required | Target step id |
| `payload` | `mapping` | `{}` | Data to pass to the target |
| `reason` | `string` | `""` | Human-readable reason |

**Outputs:**

| Name | Type | Description |
|---|---|---|
| `routed` | `bool` | Always `true` |
| `target` | `string` | Normalised target step id |
| `payload` | `mapping` | Forwarded payload |
| `reason` | `string` | Routing reason |

```yaml
steps:
  - id: decide
    uses: shell.run
    next: ${{ steps.decide.output.stdout }}
    with:
      command: |
        [ "$ENV" = "prod" ] && echo "deploy_prod" || echo "deploy_staging"

  - id: deploy_staging
    uses: shell.run
    next: end
    with:
      command: ./deploy.sh staging

  - id: deploy_prod
    uses: human.approval
    approval: true
    with:
      message: Deploying to production. Confirm?
```

---

### `system.if`

Evaluates a condition and returns one of two values. Useful when you need the boolean result as a step output for downstream expressions.

**Parameters:**

| Name | Type | Default | Description |
|---|---|---|---|
| `condition` | `bool` | required | The expression to evaluate |
| `true_value` | `string` | `"true"` | Return when condition is truthy |
| `false_value` | `string` | `"false"` | Return when condition is falsy |
| `fail_on_false` | `bool` | `false` | Raise an error (fail the step) if condition is falsy |

**Output:** `true_value` or `false_value` string.

```yaml
  - id: guard
    uses: system.if
    with:
      condition: ${{ steps.tests.output.code == 0 }}
      fail_on_false: true

  - id: deploy         # never runs if tests failed
    uses: shell.run
    with:
      command: ./deploy.sh
```

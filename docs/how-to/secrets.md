# How to manage secrets

Never hardcode API keys, passwords, or tokens in YAML files. This guide shows every safe way to pass secrets to a Stepyard flow.

---

## Use environment variables

The simplest approach. Reference them in the flow with `${{ env.VAR_NAME }}`:

```yaml title="flows/notify.yaml"
steps:
  - id: send
    uses: http.request
    with:
      url: https://api.slack.com/api/chat.postMessage
      method: POST
      headers:
        Authorization: Bearer ${{ env.SLACK_BOT_TOKEN }}
      json_body:
        channel: "#deploys"
        text: "Deploy complete"
```

Pass the secret at run time:

```bash
SLACK_BOT_TOKEN=xoxb-... stepyard run notify
```

---

## Load from a `.env` file

Keep secrets in a local `.env` file (add it to `.gitignore`):

```bash title=".env.production"
SLACK_BOT_TOKEN=xoxb-...
DATABASE_URL=postgresql://user:pass@host/db
AWS_SECRET_ACCESS_KEY=...
```

```bash
stepyard run deploy --env-file .env.production
```

### `vars` vs `env`

Values loaded with `--env-file` (and `--var KEY=VALUE`) populate the **`vars`** namespace - reference them as `${{ vars.SLACK_BOT_TOKEN }}`. Plain shell environment variables, plus a project-root `.env` file that Stepyard auto-loads into the run subprocess, populate the **`env`** namespace - reference them as `${{ env.SLACK_BOT_TOKEN }}`. There is no `secrets` namespace.

You can also declare non-secret defaults in the flow YAML itself with a top-level `env:` block - those values also land in the `env` namespace. **Never put real secrets there** - the YAML file is typically committed to version control.

!!! warning
    Never commit `.env` files to version control. Add them to `.gitignore`:
    ```gitignore
    .env*
    !.env.example
    ```

---

## Inject secrets into shell commands safely

Avoid putting secrets in the `command` string - they'll appear in logs. Use the `env` field of `shell.run` instead:

=== "Safe ✓"

    ```yaml
      - id: migrate
        uses: shell.run
        with:
          command: alembic upgrade head
          env:
            DATABASE_URL: ${{ env.DATABASE_URL }}
    ```

=== "Unsafe ✗"

    ```yaml
      - id: migrate
        uses: shell.run
        with:
          # The full URL appears in logs - don't do this
          command: DATABASE_URL=${{ env.DATABASE_URL }} alembic upgrade head
    ```

---

## Use a secrets manager

For production environments, pull secrets at runtime from a secrets manager instead of environment variables.

**AWS Secrets Manager example:**

```yaml title="flows/deploy.yaml"
steps:
  - id: get_secrets
    uses: shell.run
    with:
      # Parse the JSON secret in the shell and emit just the field you need -
      # the expression engine has no JSON/pipe filters.
      shell: true
      command: |
        aws secretsmanager get-secret-value \
          --secret-id prod/myapp \
          --query SecretString \
          --output text | jq -r '.db_password'

  - id: deploy
    uses: shell.run
    with:
      command: ./deploy.sh
      env:
        DB_PASSWORD: ${{ steps.get_secrets.output.stdout }}
```

Or write a plugin that wraps the secrets manager call (see [Tutorial: Your First Plugin](../getting-started/first-plugin.md)).

**HashiCorp Vault example:**

```yaml
  - id: get_token
    uses: shell.run
    with:
      command: |
        vault kv get -field=token secret/myapp/prod
      env:
        VAULT_ADDR: ${{ env.VAULT_ADDR }}
        VAULT_TOKEN: ${{ env.VAULT_TOKEN }}

  - id: deploy
    uses: shell.run
    with:
      command: ./deploy.sh
      env:
        APP_TOKEN: ${{ steps.get_token.output.stdout }}
```

---

## Automatic redaction

Stepyard automatically redacts common secret patterns before persisting step inputs to the local database. Fields whose keys match patterns like `*key*`, `*token*`, `*password*`, `*secret*` are stored as `***`.

```yaml
  - id: send
    uses: http.request
    with:
      headers:
        Authorization: Bearer ${{ env.SLACK_BOT_TOKEN }}   # stored as ***
```

In `stepyard show <run-id>`, the step inputs display `Authorization: ***` even though the real token was passed at runtime.

This means `stepyard logs` never shows actual secret values, even if you accidentally pass them as step inputs.

---

## Checklist

- [ ] No secrets in YAML files - use `${{ env.VAR }}` or `${{ vars.VAR }}` (see [`vars` vs `env`](#vars-vs-env))
- [ ] `.env` files are in `.gitignore`
- [ ] Secrets in shell commands use the `env:` field, not the `command:` string
- [ ] Production secrets come from a secrets manager, not from the developer's laptop

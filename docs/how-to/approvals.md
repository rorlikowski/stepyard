# How to require human approvals

Some flows should pause and wait for a human to review before continuing - a production deployment, a financial transaction, or an irreversible operation.

Stepyard has two mechanisms: **approval gates** (approve/reject) and **human input** (free-form or choice prompt).

---

## Approval gates

Set `approval: true` on a step to pause the flow until someone approves or rejects the run. The built-in `ApprovalHook` performs the suspension; pairing it with the `human.approval` node lets you attach a message for the operator.

```yaml title="flows/deploy_prod.yaml"
name: deploy_prod
description: Deploy to production - requires approval.

steps:
  - id: run_tests
    uses: shell.run
    with:
      command: pytest tests/ -q

  - id: build_image
    uses: shell.run
    with:
      command: docker build -t myapp:${{ env.GIT_SHA }} .

  - id: approval
    uses: human.approval
    approval: true        # pauses the run here until approved
    with:
      message: |
        Ready to deploy **myapp:${{ env.GIT_SHA }}** to production.

        Tests passed: ${{ steps.run_tests.output.code == 0 }}
        Image: myapp:${{ env.GIT_SHA }}

  - id: deploy
    uses: shell.run
    with:
      command: kubectl set image deployment/myapp app=myapp:${{ env.GIT_SHA }}
```

When the flow reaches the `approval` step, it pauses. You can approve or reject from the CLI:

```bash
stepyard approvals
```

```
Pending approvals:

  Run:     run-20260611_094122-a1b2c3
  Flow:    deploy_prod
  Step:    approval
  Message: Ready to deploy myapp:a1b2c3d to production.
           Tests passed: True

  [A]pprove  [R]eject  [C]ancel
```

- **Approve** - the flow resumes from the `deploy` step.
- **Reject** - the run is marked `failed`.
- **Cancel** - leave it for later; the run stays in `waiting_for_approval` state.

During an interactive `stepyard run`, the same decision appears inline with a
**Postpone (Exit)** option instead of Cancel - the run also stays in
`waiting_for_approval` until you run `stepyard approvals` or `stepyard run`
again.

---

## Human input during a run

Use `human.input` to collect a value from the user interactively - a choice, a confirmation string, or any text:

```yaml title="flows/provision.yaml"
name: provision

steps:
  - id: ask_env
    uses: human.input
    with:
      prompt: "Which environment?"
      choices:
        - staging
        - production
      required: true

  - id: ask_confirm
    uses: human.input
    with:
      prompt: "Type 'yes' to confirm"
      required: true

  - id: provision
    if: ${{ steps.ask_confirm.output == "yes" }}
    uses: shell.run
    with:
      command: terraform apply -var="env=${{ steps.ask_env.output }}"
```

---

## Pre-run inputs (collected before the flow starts)

For inputs that don't change mid-run, Stepyard collects them **before** spawning the subprocess, so the prompts appear immediately when you type `stepyard run`:

```yaml title="flows/release.yaml"
name: release

steps:
  - id: version
    uses: human.input
    with:
      prompt: Release version (e.g. 1.2.3)
      required: true

  - id: changelog
    uses: human.input
    with:
      prompt: Changelog entry
      required: true
      secret: false

  - id: tag
    uses: shell.run
    with:
      command: |
        git tag -a v${{ steps.version.output }} \
          -m "${{ steps.changelog.output }}"
        git push origin v${{ steps.version.output }}
```

Running `stepyard run release` immediately asks:

```
Release version (e.g. 1.2.3): 2.1.0
Changelog entry: Fix memory leak in worker pool
```

---

## Postpone and resume later

If you can't approve right now, cancel out of `stepyard approvals` or choose
**Postpone (Exit)** during an interactive `stepyard run`. The run remains in
`waiting_for_approval` state:

```bash
stepyard approvals          # interactive: Approve / Reject / Cancel
```

---

## Approval in CI

In a CI environment (no TTY), approval prompts are skipped automatically. The run pauses in `waiting_for_approval` state, and an operator clears it later from an interactive session:

```bash
stepyard approvals          # interactive: Approve / Reject / Cancel
```

This is useful for workflows where a human reviews pending runs out-of-band.

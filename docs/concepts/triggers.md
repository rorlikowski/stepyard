# Triggers & Scheduling

Flows without a `trigger` block run only when you call `stepyard run <name>` manually. Add a trigger to run a flow automatically.

---

## How triggers work

1. You add a `trigger:` block to a flow.
2. You start the scheduler daemon: `stepyard service start`.
3. The daemon discovers all flows with triggers and starts each trigger in the background.
4. When a trigger fires, the daemon queues a run and the executor spawns a subprocess.

All runs - manual and triggered - are stored in the local SQLite database and visible in `stepyard status`.

---

## Built-in triggers

Built-in trigger types: `cron`, `interval`, and `startup`. Event-driven triggers (webhooks, polling, queues) come from plugins - see [Custom (plugin) triggers](#custom-plugin-triggers) below.

### `cron` - time-based scheduling

Accepts standard 5-field cron syntax (`minute hour day-of-month month day-of-week`).

```yaml
trigger:
  uses: cron
  with:
    schedule: "0 9 * * 1-5"   # weekdays at 09:00

# OR use the 'expression' alias:
trigger:
  uses: cron
  with:
    expression: "0 0 * * *"   # every day at midnight
```

**Common schedules:**

| Schedule | Cron expression |
|---|---|
| Every hour | `0 * * * *` |
| Every day at midnight | `0 0 * * *` |
| Every Sunday at midnight | `0 0 * * 0` |
| First of the month at midnight | `0 0 1 * *` |

**Full example - nightly database backup:**

```yaml title="flows/pg_backup.yaml"
name: pg_backup
trigger:
  uses: cron
  with:
    schedule: "0 3 * * *"

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
          s3://${{ env.BACKUP_BUCKET }}/$(date +%Y-%m-%d).sql.gz

  - id: cleanup
    uses: shell.run
    with:
      command: rm -f /tmp/backup.sql.gz
```

---

### `interval` - fixed frequency

Fires every N seconds.

```yaml
trigger:
  uses: interval
  with:
    seconds: 60
```

**Full example - API health monitor:**

```yaml title="flows/health_monitor.yaml"
name: health_monitor
trigger:
  uses: interval
  with:
    seconds: 30

steps:
  - id: check
    uses: http.request
    continue_on_error: true
    with:
      url: https://api.myapp.com/health
      method: GET

  - id: alert
    if: ${{ steps.check.output.status != 200 }}
    uses: http.request
    with:
      url: ${{ env.PAGERDUTY_WEBHOOK }}
      method: POST
      json_body:
        routing_key: ${{ env.PD_ROUTING_KEY }}
        event_action: trigger
        payload:
          summary: API health check failed (${{ steps.check.output.status }})
          severity: critical
```

---

### `startup` - run once on daemon start

Fires once, immediately when `stepyard service start` is called.

```yaml title="flows/startup_notify.yaml"
name: startup_notify
trigger:
  uses: startup

steps:
  - id: announce
    uses: http.request
    with:
      url: ${{ env.SLACK_WEBHOOK }}
      method: POST
      json_body:
        text: "🟢 Stepyard daemon started on `${{ env.HOSTNAME }}`."
```

---

## Custom (plugin) triggers

Any plugin can register an event-driven trigger using the `@trigger` decorator. The trigger is an `async` generator that `yield`s a payload dict each time an event occurs.

**Example - trigger on every new GitHub PR:**

```python title="stepyard_plugin_github/triggers.py"
import asyncio
import httpx
from stepyard.sdk import trigger


@trigger(name="github.poll_prs")
async def poll_prs(repo: str, token: str, interval: int = 60):
    """Poll GitHub for new PRs and fire when one is opened."""
    seen: set[int] = set()

    while True:
        resp = httpx.get(
            f"https://api.github.com/repos/{repo}/pulls?state=open",
            headers={"Authorization": f"Bearer {token}"},
        )
        for pr in resp.json():
            if pr["number"] not in seen:
                seen.add(pr["number"])
                yield {
                    "number": pr["number"],
                    "title": pr["title"],
                    "user": pr["user"]["login"],
                    "url": pr["html_url"],
                }

        await asyncio.sleep(interval)
```

Use it in a flow:

```yaml title="flows/pr_review.yaml"
name: pr_review
trigger:
  uses: github.poll_prs
  with:
    repo: my-org/my-repo
    token: ${{ env.GITHUB_TOKEN }}
    interval: 60

steps:
  - id: review
    uses: llm.generate
    with:
      model: gpt-4o
      prompt: |
        New PR opened by ${{ trigger.payload.user }}:
        "${{ trigger.payload.title }}"

        Should this be merged? Reply with YES or NO and a one-sentence reason.
```

The `trigger.payload` in the flow receives exactly the dict your trigger `yield`ed.

---

## Managing the daemon

```bash
stepyard service start    # start in background
stepyard service stop     # stop gracefully
stepyard service status   # show daemon pid and uptime
stepyard service restart  # stop + start
```

The daemon logs to `.stepyard/logs/scheduler.log`. View it live:

```bash
tail -f .stepyard/logs/scheduler.log
```

---

## Concurrency limits

By default, the executor runs up to 4 flows concurrently. Configure it via environment variable:

```bash
STEPYARD_MAX_CONCURRENT_FLOWS=8 stepyard service start
```

Or export it in your shell profile.

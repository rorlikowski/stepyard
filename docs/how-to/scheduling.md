# How to schedule flows

Stepyard includes a background scheduler daemon. This guide shows how to set up triggers, start the daemon, and monitor scheduled runs.

---

## Quick setup

1. Add a trigger to your flow:

    ```yaml title="flows/backup.yaml"
    name: backup
    trigger:
      uses: cron
      with:
        schedule: "0 3 * * *"   # every night at 03:00

    steps:
      - id: dump
        uses: shell.run
        with:
          command: pg_dump ${{ env.DATABASE_URL }} > /tmp/backup.sql
    ```

2. Start the daemon:

    ```bash
    stepyard service start
    ```

3. Check it's running:

    ```bash
    stepyard status
    ```

---

## Cron schedules

Standard 5-field cron syntax:

```
┌─────────── minute (0-59)
│ ┌───────── hour (0-23)
│ │ ┌─────── day of month (1-31)
│ │ │ ┌───── month (1-12)
│ │ │ │ ┌─── day of week (0-7, 0 and 7 = Sunday)
│ │ │ │ │
* * * * *
```

Common patterns:

| Schedule | Expression |
|---|---|
| Every minute | `* * * * *` |
| Every 15 minutes | `*/15 * * * *` |
| Every hour | `0 * * * *` |
| Every day at midnight | `0 0 * * *` |
| Every Monday at 09:00 | `0 9 * * 1` |
| First day of month | `0 0 1 * *` |
| Weekdays at 08:30 | `30 8 * * 1-5` |

---

## Interval triggers

Repeat every N seconds:

```yaml
trigger:
  uses: interval
  with:
    seconds: 300   # every 5 minutes
```

---

## Multiple triggers in a project

Each flow has its own trigger. You can have any number of scheduled flows:

```
flows/
├── pg_backup.yaml        # cron 03:00
├── health_monitor.yaml   # interval 30s
├── weekly_report.yaml    # cron 0 9 * * 1 (Monday 09:00)
└── deploy.yaml           # manual (no trigger)
```

All scheduled flows run under the same daemon process.

---

## Daemon management

```bash
stepyard service start     # start in background
stepyard service stop      # graceful shutdown
stepyard service restart   # stop + start
stepyard service status    # show pid and uptime
```

The daemon writes its PID to `.stepyard/scheduler.pid` and logs to `.stepyard/logs/scheduler.log`.

Watch logs live:

```bash
tail -f .stepyard/logs/scheduler.log
```

---

## Concurrency and resource limits

| Environment variable | Default | Description |
|---|---|---|
| `STEPYARD_MAX_CONCURRENT_FLOWS` | `4` | Max flows running at once |
| `STEPYARD_SCHEDULER_TICK` | `5` | Seconds between scheduler ticks |
| `STEPYARD_EXECUTOR_TICK` | `2` | Seconds between executor ticks |

```bash
STEPYARD_MAX_CONCURRENT_FLOWS=8 stepyard service start
```

---

## Checking run history

```bash
stepyard status             # table of recent and scheduled runs
stepyard logs <run-id>      # full output for one run
```

After a cron trigger fires, `stepyard status` shows the queued or completed run:

```
 Flow          Description           Last Run              Run ID                        Status
 pg_backup     Nightly database backup 2026-06-11 02:00:05   run-20260611_020005-c3d4e5   completed
```

---

## Clearing run history

```bash
stepyard clear              # prompts for confirmation
stepyard clear --force      # skip confirmation
```

This deletes all run records from the database. Running flows are not affected.

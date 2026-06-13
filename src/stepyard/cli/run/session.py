"""
Stepyard CLI - RunCommandContext and RunSession for the ``run`` command.

Contains the dataclass that holds all context for a single run, and the
async RunSession that drives live watching and interactive approval/input.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field

import click
import questionary
from rich import box
from rich.panel import Panel

from stepyard.cli.renderers.live_view import LiveLogBuffer, RunView, build_display_steps
from stepyard.cli.run.inputs import (
    ask_input_request as _ask_input_request,
)
from stepyard.cli.run.inputs import (
    collect_pre_run_inputs as _collect_pre_run_inputs,
)
from stepyard.cli.run.inputs import (
    flow_needs_runtime_human_input as _flow_needs_runtime_human_input,
)
from stepyard.cli.run.inputs import (
    input_request_from_step_inputs as _input_request_from_step_inputs,
)
from stepyard.cli.run.panels import build_waiting_panel
from stepyard.cli.theme import (
    C_ERROR,
    C_MUTED,
    C_SUCCESS,
    C_WARN,
    C_WHITE,
    PROMPT_STYLE,
)
from stepyard.cli.ui import (
    console,
    format_duration,
    format_step_line,
    print_cli_hint,
    print_step_output,
)
from stepyard.core.flow import Flow

# ─────────────────────────────────────────────────────────────────────────────
#  Private build helpers
# ─────────────────────────────────────────────────────────────────────────────


def _new_run_id(prefix: str = "run") -> str:
    import datetime
    import uuid

    return f"{prefix}-{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}-{uuid.uuid4().hex[:6]}"


def _collect_console_trigger_payload(flow: Flow, registry) -> tuple[dict | None, str]:
    trigger_payload = None
    trigger_type_str = "manual"

    if flow.model.trigger and flow.model.trigger.mode == "console":
        import inspect

        from stepyard.scheduler.triggers import build_apscheduler_trigger

        res = build_apscheduler_trigger(flow.model.trigger, registry=registry)
        if res:
            trigger_instance, trig_type = res
            if inspect.isasyncgen(trigger_instance):

                async def _get_first():
                    async for payload in trigger_instance:
                        return payload
                    return None

                try:
                    trigger_payload = asyncio.run(_get_first())
                    trigger_type_str = trig_type
                except (EOFError, KeyboardInterrupt):
                    from stepyard.cli.ui import print_error

                    print_error("Aborted by user")
                    raise click.exceptions.Exit(1) from None

    return trigger_payload, trigger_type_str


# ─────────────────────────────────────────────────────────────────────────────
#  RunCommandContext
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class RunCommandContext:
    storage: object
    flow_file: str
    flow: Flow
    registry: object
    vars_dict: dict
    trigger_payload: dict | None
    trigger_type: str
    run_id: str
    pre_run_input_env: dict[str, str]
    verbose: bool
    show_live_logs: bool
    view: RunView
    process_manager: object
    all_steps: list = field(default_factory=list)

    @classmethod
    def build(
        cls,
        flow_name: str,
        var: tuple[str, ...],
        env_file: str | None,
        verbose: bool,
        show_live_logs: bool = True,
        *,
        parse_run_vars,
        load_flow_for_run,
        get_storage,
    ) -> RunCommandContext:
        import sys

        interactive = sys.stdin.isatty()
        vars_dict = parse_run_vars(var, env_file)
        storage = get_storage()
        flow_file, flow = load_flow_for_run(flow_name, storage)

        from stepyard.plugin import discover_capabilities

        registry = discover_capabilities(storage.project_dir)
        trigger_payload, trigger_type = _collect_console_trigger_payload(flow, registry)
        use_runtime_human_input = _flow_needs_runtime_human_input(flow) and interactive
        pre_run_input_env = (
            {"STEPYARD_RUNTIME_HUMAN_INPUT": "1"}
            if use_runtime_human_input
            else _collect_pre_run_inputs(
                flow,
                storage.project_dir,
                trigger_payload,
                vars_dict,
                not interactive,
                registry=registry,
            )
        )

        run_id = _new_run_id()
        storage.create_run(
            run_id,
            flow.model.name,
            trigger_type=trigger_type,
            trigger_payload=trigger_payload,
        )

        view = RunView(
            flow_name=flow.model.name,
            run_id=run_id,
            project_dir=storage.project_dir,
            description=getattr(flow.model, "description", None),
        )

        from stepyard.executor.process_manager import ProcessManager

        stepyard_dir = os.path.join(storage.project_dir, ".stepyard")
        pm = ProcessManager(logs_dir=os.path.join(stepyard_dir, "logs"))

        return cls(
            storage=storage,
            flow_file=flow_file,
            flow=flow,
            registry=registry,
            vars_dict=vars_dict,
            trigger_payload=trigger_payload,
            trigger_type=trigger_type,
            run_id=run_id,
            pre_run_input_env=pre_run_input_env,
            verbose=verbose,
            show_live_logs=show_live_logs,
            view=view,
            process_manager=pm,
            all_steps=list(flow.model.steps),
        )


# ─────────────────────────────────────────────────────────────────────────────
#  RunSession
# ─────────────────────────────────────────────────────────────────────────────


class RunSession:
    def __init__(self, ctx: RunCommandContext) -> None:
        self.ctx = ctx
        self.live_logs = LiveLogBuffer(max_lines=5000)
        self.printed_steps: set = set()
        self.step_start_times: dict[str, float] = {}
        self.step_end_times: dict[str, float] = {}

    async def run_and_report(self) -> None:
        flow_start = time.monotonic()
        self.ctx.view.print_header()

        while True:
            await self._spawn_and_watch()

            run_db = self.ctx.storage.get_run(self.ctx.run_id)
            if run_db and run_db["status"] == "running":
                self.ctx.storage.update_run_status(
                    self.ctx.run_id,
                    "failed",
                    error="Process died unexpectedly",
                )
                run_db = self.ctx.storage.get_run(self.ctx.run_id)

            step_runs = self.ctx.storage.get_step_runs(self.ctx.run_id)
            pending_step, pending_step_id, inputs_dict, status_panel = self._pending_pause(
                step_runs, run_db
            )
            self._render_snapshot(step_runs, status_panel)
            self._print_step_outputs(step_runs, run_db)

            if run_db["status"] not in ("waiting_for_approval", "waiting_for_input"):
                break
            if not pending_step:
                break
            if run_db["status"] == "waiting_for_input":
                if not self._handle_waiting_for_input(pending_step_id, inputs_dict, status_panel):
                    break
                continue
            if run_db["status"] == "waiting_for_approval":
                if not await self._handle_waiting_for_approval(pending_step_id):
                    break
                continue

        self._print_summary(time.monotonic() - flow_start)

    async def _spawn_and_watch(self) -> None:
        fp = self.ctx.process_manager.spawn_flow(
            self.ctx.run_id,
            self.ctx.flow.model.name,
            self.ctx.flow_file,
            self.ctx.storage.project_dir,
            extra_env=self.ctx.pre_run_input_env,
            vars_dict=self.ctx.vars_dict,
        )
        self.ctx.storage.update_run_status(self.ctx.run_id, "running")

        log_fh = None
        try:
            for _ in range(20):
                if fp.log_path.exists():
                    log_fh = open(fp.log_path, encoding="utf-8")
                    break
                await asyncio.sleep(0.1)

            self.ctx.view.start_live()
            try:
                while True:
                    run_db = self.ctx.storage.get_run(self.ctx.run_id)
                    run_status = run_db["status"] if run_db else "unknown"
                    self._drain_logs(log_fh)

                    step_runs = self.ctx.storage.get_step_runs(self.ctx.run_id)
                    self.ctx.view.update_live(
                        all_steps=self.ctx.all_steps,
                        step_runs=step_runs,
                        step_start_times=self.step_start_times,
                        step_end_times=self.step_end_times,
                        live_logs=self.live_logs.snapshot(),
                        show_logs=self.ctx.show_live_logs,
                    )

                    if not fp.is_alive() or run_status in (
                        "completed",
                        "failed",
                        "cancelled",
                        "waiting_for_approval",
                        "waiting_for_input",
                    ):
                        break

                    await asyncio.sleep(0.15)
            except asyncio.CancelledError:
                self.ctx.process_manager.kill_flow(self.ctx.run_id)
                self.ctx.storage.update_run_status(
                    self.ctx.run_id, "cancelled", error="Aborted by user"
                )
                raise
            finally:
                self.ctx.view.stop_live()
        finally:
            if log_fh:
                log_fh.close()

    def _drain_logs(self, log_fh) -> None:
        if not log_fh:
            return
        for line in log_fh.readlines():
            line = line.strip()
            if line.startswith("[") and "] " in line:
                step_id_part, msg = line.split("] ", 1)
                step_id = step_id_part[1:]
                self.live_logs.append(f"[{C_MUTED}]{step_id}[/{C_MUTED}] │ {msg}")
            else:
                self.live_logs.append(line)

    def _pending_pause(self, step_runs: list[dict], run_db: dict | None):
        pending_step = None
        pending_step_id = ""
        inputs_dict = {}
        status_panel = None

        if run_db and run_db["status"] in ("waiting_for_approval", "waiting_for_input"):
            pending_step = next((sr for sr in step_runs if sr["status"] == "pending"), None)
            if pending_step:
                pending_step_id = pending_step["step_id"]
                try:
                    if pending_step.get("inputs"):
                        inputs_dict = json.loads(pending_step["inputs"])
                except Exception:  # noqa: BLE001 - inputs may be arbitrary non-JSON
                    inputs_dict = {"prompt": str(pending_step.get("inputs", ""))}
                status_panel = build_waiting_panel(
                    self.ctx.flow.model.name,
                    self.ctx.run_id,
                    pending_step_id,
                    inputs_dict,
                    waiting_for_input=run_db["status"] == "waiting_for_input",
                )

        return pending_step, pending_step_id, inputs_dict, status_panel

    def _render_snapshot(self, step_runs: list[dict], status_panel) -> None:
        self.ctx.view.start_live()
        self.ctx.view.update_live(
            all_steps=self.ctx.all_steps,
            step_runs=step_runs,
            step_start_times=self.step_start_times,
            step_end_times=self.step_end_times,
            live_logs=self.live_logs.snapshot(),
            status_panel=status_panel,
            show_logs=self.ctx.show_live_logs,
        )
        self.ctx.view.stop_live()

        run_db = self.ctx.storage.get_run(self.ctx.run_id)
        if run_db["status"] not in ("waiting_for_approval", "waiting_for_input"):
            console.print()
            self.ctx.view.start_live()
            self.ctx.view.live.transient = False
            self.ctx.view.update_live(
                self.ctx.all_steps,
                step_runs,
                self.step_start_times,
                self.step_end_times,
                self.live_logs.snapshot(),
                status_panel=status_panel,
                show_logs=self.ctx.show_live_logs,
            )
            self.ctx.view.stop_live()

    def _print_step_outputs(self, step_runs: list[dict], run_db: dict) -> None:
        display_steps = build_display_steps(self.ctx.all_steps, step_runs)
        for sr in step_runs:
            if sr["step_id"] not in display_steps:
                continue
            if sr["status"] in ("completed", "failed") and sr["step_id"] not in self.printed_steps:
                if not self.ctx.verbose and sr["status"] == "completed":
                    if run_db["status"] not in ("waiting_for_input", "waiting_for_approval"):
                        continue
                console.print()
                console.print(f"↳ [bold {C_WHITE}]{sr['step_id']}[/] outputs:")
                if sr.get("error"):
                    console.print(f"  [bold {C_ERROR}]Error:[/] {sr['error']}")
                print_step_output(sr)
                self.printed_steps.add(sr["step_id"])

    def _handle_waiting_for_input(
        self, pending_step_id: str, inputs_dict: dict, status_panel
    ) -> bool:
        import sys

        if not sys.stdin.isatty():
            return False

        if status_panel:
            console.print()
            console.print(status_panel)

        request = _input_request_from_step_inputs(pending_step_id, inputs_dict)
        value = _ask_input_request(request)
        if value is None:
            self.ctx.storage.update_step_run(
                self.ctx.run_id, pending_step_id, status="failed", error="Aborted by user"
            )
            self.ctx.storage.update_run_status(
                self.ctx.run_id, "cancelled", error="Aborted by user"
            )
            return False
        if request.required and not str(value):
            self.ctx.storage.update_step_run(
                self.ctx.run_id, pending_step_id, status="failed", error="Input is required"
            )
            self.ctx.storage.update_run_status(self.ctx.run_id, "failed", error="Input is required")
            return False

        self.ctx.storage.update_step_run(
            self.ctx.run_id, pending_step_id, status="completed", output=str(value)
        )
        self.ctx.storage.update_run_status(self.ctx.run_id, "running")
        return True

    async def _handle_waiting_for_approval(self, pending_step_id: str) -> bool:
        import sys

        if not sys.stdin.isatty():
            return False

        prompt_question = questionary.select(
            f"Action for Step '{pending_step_id}':",
            choices=[
                questionary.Choice("✓  Approve", value="approve"),
                questionary.Choice("✗  Reject", value="reject"),
                questionary.Choice("⏸  Postpone (Exit)", value="postpone"),
            ],
            style=PROMPT_STYLE,
        )
        if asyncio.get_event_loop().is_running():
            action = await prompt_question.ask_async()
        else:
            action = prompt_question.ask()

        if action == "approve":
            self.ctx.storage.update_step_run(
                self.ctx.run_id,
                pending_step_id,
                status="completed",
                output="Approved by operator",
            )
            # Re-queue (not "running") - the worker will pick it up and mark it running.
            self.ctx.storage.update_run_status(self.ctx.run_id, "queued")
            logical_pending_step_id = pending_step_id.split("#", 1)[0].split("[", 1)[0]
            step_idx = next(
                i
                for i, s in enumerate(self.ctx.flow.model.steps)
                if s.id == logical_pending_step_id
            )
            self.ctx.flow.model.steps = self.ctx.flow.model.steps[step_idx + 1 :]

            self.printed_steps.add(pending_step_id)
            self._print_approval_step_line(pending_step_id, "completed")
            return True

        if action == "reject":
            self.ctx.storage.update_step_run(
                self.ctx.run_id,
                pending_step_id,
                status="failed",
                error="Rejected by operator",
            )
            self.ctx.storage.update_run_status(
                self.ctx.run_id, "failed", error="Step rejected by operator"
            )
            self.printed_steps.add(pending_step_id)
            self._print_approval_step_line(pending_step_id, "failed", error="Rejected by operator")
            return False

        return False

    def _print_approval_step_line(
        self, pending_step_id: str, status: str, error: str | None = None
    ) -> None:
        logical_pending_step_id = pending_step_id.split("#", 1)[0].split("[", 1)[0]
        step_idx_global = next(
            (i for i, s in enumerate(self.ctx.all_steps) if s.id == logical_pending_step_id), -1
        )
        step_num = step_idx_global + 1 if step_idx_global >= 0 else None
        console.print(
            format_step_line(
                pending_step_id,
                status,
                error=error,
                duration=None,
                step_num=step_num,
                total_steps=len(self.ctx.all_steps),
            )
        )

    def _print_summary(self, flow_duration: float) -> None:
        run_db = self.ctx.storage.get_run(self.ctx.run_id)
        console.print()

        if run_db["status"] == "completed":
            console.print(
                Panel(
                    f"[bold {C_SUCCESS}]✓ Flow completed successfully[/] [{C_MUTED}]in {format_duration(flow_duration)}[/]",
                    border_style=C_SUCCESS,
                    expand=False,
                    box=box.ROUNDED,
                )
            )
            print_cli_hint(f"stepyard logs {self.ctx.run_id}", "to view logs")
        elif run_db["status"] == "waiting_for_approval":
            console.print(
                Panel(
                    f"[bold {C_WARN}]⏸  Flow paused - waiting for manual approval[/bold {C_WARN}]\n"
                    f"[{C_MUTED}]Run [bold]stepyard approvals[/bold] to review and approve.[/{C_MUTED}]",
                    border_style=C_WARN,
                    padding=(0, 3),
                    box=box.ROUNDED,
                )
            )
            print_cli_hint("stepyard approvals", "to manage manual approvals")
        elif run_db["status"] == "waiting_for_input":
            console.print(
                Panel(
                    f"[bold {C_WARN}]⏸  Flow paused - waiting for manual input[/bold {C_WARN}]",
                    border_style=C_WARN,
                    padding=(0, 3),
                    box=box.ROUNDED,
                )
            )
        else:
            console.print(
                Panel(
                    f"[bold {C_ERROR}]✗  Flow failed[/bold {C_ERROR}]"
                    f"  [{C_MUTED}]{format_duration(flow_duration)}[/{C_MUTED}]\n"
                    f"[{C_MUTED}]{run_db.get('error', 'Unknown error')}[/{C_MUTED}]\n\n"
                    f"[{C_MUTED}]View logs: [bold]stepyard logs {self.ctx.run_id}[/bold][/{C_MUTED}]",
                    border_style=C_ERROR,
                    padding=(0, 3),
                    box=box.ROUNDED,
                )
            )
            print_cli_hint(
                f"stepyard logs {self.ctx.run_id}", "to view logs and diagnostic details"
            )
            print_cli_hint(
                f"stepyard replay {self.ctx.run_id} --from-step <step_id>", "to resume execution"
            )

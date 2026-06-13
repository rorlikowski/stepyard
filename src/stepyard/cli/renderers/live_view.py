"""
Stepyard CLI - Live View for running workflows.
"""

from __future__ import annotations

import json
import time
from collections import deque
from typing import Any

from rich import box
from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from stepyard.cli.theme import C_ERROR, C_MUTED, C_PRIMARY, C_SUCCESS, C_WARN, C_WHITE
from stepyard.cli.ui import console, format_duration


class LiveLogBuffer:
    """Bounded in-memory buffer used only for the live CLI display."""

    def __init__(self, max_lines: int = 5000) -> None:
        self._lines: deque[str] = deque(maxlen=max_lines)

    def append(self, line: str) -> None:
        self._lines.append(line)

    def snapshot(self) -> list[str]:
        return list(self._lines)


def build_display_steps(all_steps: list[Any], step_runs: list[dict[str, Any]]) -> list[str]:
    if step_runs:
        ordered_runs = sorted(step_runs, key=lambda sr: sr.get("id") or 0)
        display = [sr["step_id"] for sr in ordered_runs]
        executed_logical_ids = {_logical_step_id(sr["step_id"]) for sr in ordered_runs}
        display.extend(step.id for step in all_steps if step.id not in executed_logical_ids)
        return display

    display = []
    for step in all_steps:
        display.append(step.id)
    return display


def _logical_step_id(step_id: str) -> str:
    return step_id.split("#", 1)[0].split("[", 1)[0]


def format_status_ui(status: str, sr: dict[str, Any] | None = None, is_live: bool = False) -> str:
    if status == "completed":
        try:
            out_data = json.loads(sr["output"]) if sr and sr.get("output") else None
            if isinstance(out_data, list):
                return f"[bold {C_SUCCESS}]✓ Completed ({len(out_data)} loops)[/]"
        except (json.JSONDecodeError, TypeError):
            pass
        return f"[bold {C_SUCCESS}]✓ Completed[/]"
    if status == "failed":
        return f"[bold {C_ERROR}]✗ Failed[/]"
    if status == "skipped":
        return f"[bold {C_WARN}]○ Skipped[/]"
    if status == "running" and is_live:
        frames = ["⠋", " ", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        frame = frames[int(time.monotonic() * 12) % len(frames)]
        return f"[bold {C_PRIMARY}]{frame} Running...[/]"
    return f"[{C_MUTED}]Pending[/{C_MUTED}]"


class RunView:
    def __init__(
        self, flow_name: str, run_id: str, project_dir: str, description: str | None = None
    ):
        self.flow_name = flow_name
        self.run_id = run_id
        self.project_dir = project_dir
        self.description = description
        self.live = None

    def print_header(self):
        desc_str = ""
        if self.description:
            desc_str = f"\n[{C_MUTED}]{self.description}[/{C_MUTED}]"

        console.print()
        console.print(
            f"🚀 [bold {C_WHITE}]Executing:[/] {self.flow_name} [{C_MUTED}]({self.run_id})[/]"
        )
        console.print(f"📁 [bold {C_WHITE}]Project:[/] {self.project_dir}")
        if desc_str:
            console.print(desc_str)
        console.print()

    def start_live(self):
        self.live = Live(console=console, refresh_per_second=10, transient=True)
        self.live.start()

    def stop_live(self):
        if self.live:
            self.live.stop()
            self.live = None

    def update_live(
        self,
        all_steps: list[Any],
        step_runs: list[dict[str, Any]],
        step_start_times: dict[str, float],
        step_end_times: dict[str, float],
        live_logs: list[str],
        status_panel: Any | None = None,
        show_logs: bool = True,
    ):
        sr_map = {sr["step_id"]: sr for sr in step_runs}
        display_steps = build_display_steps(all_steps, step_runs)

        if self.live and status_panel is not None:
            pending_step_id = _pending_step_id(step_runs)
            before_steps, after_steps = _split_steps_around_pending(display_steps, pending_step_id)
            renderables = [
                self._build_steps_table(
                    before_steps, sr_map, step_start_times, step_end_times, len(display_steps), 0
                ),
                status_panel,
            ]
            if after_steps:
                renderables.append(
                    self._build_steps_table(
                        after_steps,
                        sr_map,
                        step_start_times,
                        step_end_times,
                        len(display_steps),
                        len(before_steps),
                    )
                )
            self.live.update(Group(*renderables))
            return

        table = self._build_steps_table(
            _visible_tail(display_steps),
            sr_map,
            step_start_times,
            step_end_times,
            len(display_steps),
            max(0, len(display_steps) - 15),
        )

        try:
            log_text = Text.from_markup(
                "\n".join(live_logs) if live_logs else "Waiting for logs..."
            )
        except Exception:  # noqa: BLE001 - log lines may contain unbalanced Rich markup
            log_text = Text("\n".join(live_logs) if live_logs else "Waiting for logs...")

        if self.live:
            if show_logs:
                log_panel = Panel(
                    log_text,
                    title=f"[bold {C_PRIMARY}]▶ Live Logs[/bold {C_PRIMARY}]",
                    border_style=C_PRIMARY,
                )
                self.live.update(Group(table, log_panel))
            else:
                self.live.update(table)

    def _build_steps_table(
        self,
        step_ids: list[str],
        sr_map: dict[str, dict[str, Any]],
        step_start_times: dict[str, float],
        step_end_times: dict[str, float],
        total_steps: int,
        start_offset: int,
    ) -> Table:
        table = Table(box=box.SIMPLE, expand=True, border_style=C_MUTED, show_header=False)
        table.add_column("Step", style=f"bold {C_WHITE}")
        table.add_column("Status", justify="center")
        table.add_column("Duration", justify="right")

        for i_visible, step_id in enumerate(step_ids):
            overall_idx = start_offset + i_visible + 1
            sr = sr_map.get(step_id)
            status = sr["status"] if sr else "pending"

            duration_str = "-"
            if status == "running":
                if step_id not in step_start_times:
                    step_start_times[step_id] = time.monotonic()
                duration_str = format_duration(time.monotonic() - step_start_times[step_id])
            elif status in ("completed", "failed", "skipped") and step_id in step_start_times:
                if step_id not in step_end_times:
                    step_end_times[step_id] = time.monotonic()
                duration_str = format_duration(step_end_times[step_id] - step_start_times[step_id])

            status_ui = format_status_ui(status, sr, is_live=True)
            prefix = f"[{C_MUTED}][{overall_idx}/{total_steps}][/{C_MUTED}]"
            table.add_row(
                f"{prefix} {step_id}", status_ui, f"[{C_MUTED}]{duration_str}[/{C_MUTED}]"
            )

        return table


def _visible_tail(display_steps: list[str]) -> list[str]:
    return display_steps[-15:] if len(display_steps) > 15 else display_steps


def _pending_step_id(step_runs: list[dict[str, Any]]) -> str | None:
    pending = next((sr for sr in step_runs if sr["status"] == "pending"), None)
    return pending["step_id"] if pending else None


def _split_steps_around_pending(
    display_steps: list[str], pending_step_id: str | None
) -> tuple[list[str], list[str]]:
    visible_steps = _visible_tail(display_steps)
    if pending_step_id not in visible_steps:
        return visible_steps, []
    idx = visible_steps.index(pending_step_id)
    return visible_steps[: idx + 1], visible_steps[idx + 1 :]

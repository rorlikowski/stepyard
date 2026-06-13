"""
Stepyard Storage facade.

Provides the storage facade used by the API, CLI, scheduler, and engine.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from sqlmodel import select

from stepyard.storage.database import Database
from stepyard.storage.models import AuditLog, FlowState, Project, Run, StepRun


def _map_run_dict(run: Run) -> dict[str, Any]:
    return run.model_dump()


class Storage:
    def __init__(self, project_dir: str) -> None:
        self.project_dir = os.path.abspath(project_dir)
        self.stepyard_dir = os.path.join(self.project_dir, ".stepyard")
        os.makedirs(self.stepyard_dir, exist_ok=True)

        self.db_path = os.path.join(self.stepyard_dir, "stepyard.db")
        self._db = Database(self.db_path)

        # Register the project
        with self._db.get_session() as session:
            proj = session.get(Project, self.project_dir)
            if not proj:
                session.add(Project(path=self.project_dir))
                session.commit()

    @contextmanager
    def get_connection(self):
        with self._db.engine.connect() as conn:
            yield conn

    @property
    def db(self) -> Database:
        return self._db

    # ── Run management ────────────────────────────────────────────────────────

    def create_run(
        self,
        run_id: str,
        flow_name: str,
        status: str = "queued",
        trigger_type: str | None = None,
        trigger_event_id: str | None = None,
        trigger_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._db.get_session() as session:
            run = Run(
                id=run_id,
                flow_name=flow_name,
                status=status,
                trigger_type=trigger_type,
                trigger_event_id=trigger_event_id,
                trigger_payload=trigger_payload,
            )
            session.add(run)
            session.commit()
            session.refresh(run)
            return _map_run_dict(run)

    def update_run_status(self, run_id: str, status: str, error: str | None = None) -> None:
        with self._db.get_session() as session:
            run = session.get(Run, run_id)
            if run:
                run.status = status
                if error is not None:
                    run.error = error
                if status in ("completed", "failed", "cancelled"):
                    run.end_time = datetime.now(timezone.utc)
                session.commit()

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._db.get_session() as session:
            run = session.get(Run, run_id)
            return _map_run_dict(run) if run else None

    def list_queued_runs(self) -> list[dict[str, Any]]:
        with self._db.get_session() as session:
            stmt = select(Run).where(Run.status == "queued").order_by(Run.start_time)
            return [_map_run_dict(r) for r in session.exec(stmt)]

    def list_recent_runs(
        self,
        flow_name: str | None = None,
        limit: int = 20,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return the most recent runs, optionally filtered by flow or status."""
        with self._db.get_session() as session:
            stmt = select(Run).order_by(Run.start_time.desc()).limit(limit)  # type: ignore[attr-defined]
            if flow_name:
                stmt = stmt.where(Run.flow_name == flow_name)
            if status:
                stmt = stmt.where(Run.status == status)
            return [_map_run_dict(r) for r in session.exec(stmt)]

    def get_last_run_for_flow(self, flow_name: str) -> dict[str, Any] | None:
        """Return the most recent run for a specific flow."""
        with self._db.get_session() as session:
            stmt = (
                select(Run)
                .where(Run.flow_name == flow_name)
                .order_by(Run.start_time.desc())  # type: ignore[attr-defined]
                .limit(1)
            )
            run = session.exec(stmt).first()
            return _map_run_dict(run) if run else None

    def list_pending_approvals(self) -> list[dict[str, Any]]:
        """Return all runs that are paused waiting for approval or input."""
        with self._db.get_session() as session:
            stmt = (
                select(Run)
                .where(
                    Run.status.in_(["waiting_for_approval", "waiting_for_input"])  # type: ignore[attr-defined]
                )
                .order_by(Run.start_time)
            )
            return [_map_run_dict(r) for r in session.exec(stmt)]

    def clear_history(
        self,
        *,
        flow_name: str | None = None,
        keep_last: int = 0,
    ) -> int:
        """Delete run history and associated step runs.

        Parameters
        ----------
        flow_name:
            If given, delete only runs for this flow.
        keep_last:
            Keep this many most-recent runs per flow (0 = delete all).

        Returns
        -------
        int
            Number of runs deleted.
        """
        from sqlmodel import delete as sql_delete  # noqa: PLC0415

        with self._db.get_session() as session:
            stmt = select(Run)
            if flow_name:
                stmt = stmt.where(Run.flow_name == flow_name)
            stmt = stmt.order_by(Run.start_time.desc())  # type: ignore[attr-defined]
            all_runs = list(session.exec(stmt))

            if keep_last > 0:
                runs_to_delete = all_runs[keep_last:]
            else:
                runs_to_delete = all_runs

            count = 0
            for run in runs_to_delete:
                session.exec(
                    sql_delete(StepRun).where(StepRun.run_id == run.id)  # type: ignore[arg-type]
                )
                session.delete(run)
                count += 1
            session.commit()
            return count

    def list_active_runs(self, flow_name: str) -> list[dict[str, Any]]:
        with self._db.get_session() as session:
            stmt = select(Run).where(
                Run.flow_name == flow_name,
                Run.status.in_(["queued", "running", "running_teardown"]),
            )
            return [_map_run_dict(r) for r in session.exec(stmt)]

    # ── Step run management ───────────────────────────────────────────────────

    def create_step_run(
        self,
        run_id: str,
        step_id: str,
        status: str = "pending",
        attempt: int = 1,
        inputs: dict[str, Any] | None = None,
    ) -> None:
        with self._db.get_session() as session:
            # Check if exists (upsert logic if needed, but create means create or reset)
            stmt = select(StepRun).where(StepRun.run_id == run_id, StepRun.step_id == step_id)
            step_run = session.exec(stmt).first()
            if not step_run:
                step_run = StepRun(run_id=run_id, step_id=step_id)
                session.add(step_run)

            step_run.status = status
            step_run.attempt = attempt
            if inputs is not None:
                step_run.inputs = json.dumps(inputs) if not isinstance(inputs, str) else inputs
            step_run.start_time = datetime.now(timezone.utc)
            step_run.end_time = None
            step_run.output = None
            step_run.error = None
            session.commit()

    def update_step_run(
        self,
        run_id: str,
        step_id: str,
        status: str | None = None,
        output: Any = None,
        error: str | None = None,
    ) -> None:
        with self._db.get_session() as session:
            stmt = select(StepRun).where(StepRun.run_id == run_id, StepRun.step_id == step_id)
            step_run = session.exec(stmt).first()
            if step_run:
                if status is not None:
                    step_run.status = status
                if output is not None:
                    step_run.output = json.dumps(output) if not isinstance(output, str) else output
                if error is not None:
                    step_run.error = error
                if status in ("completed", "failed", "skipped"):
                    step_run.end_time = datetime.now(timezone.utc)
                session.commit()

    def get_step_runs(self, run_id: str) -> list[dict[str, Any]]:
        with self._db.get_session() as session:
            stmt = select(StepRun).where(StepRun.run_id == run_id).order_by(StepRun.id)
            return [sr.model_dump() for sr in session.exec(stmt)]

    # ── Audit log ─────────────────────────────────────────────────────────────

    def write_audit_log(
        self,
        action: str,
        actor: str,
        target: str | None = None,
        details: str | None = None,
    ) -> None:
        with self._db.get_session() as session:
            log = AuditLog(action=action, actor=actor, target=target, details=details)
            session.add(log)
            session.commit()

    # ── Flow schedule helpers ─────────────────────────────────────────────────

    def is_flow_active(self, flow_name: str) -> bool:
        with self._db.get_session() as session:
            flow = session.get(FlowState, flow_name)
            return flow.is_active if flow else True

    def set_flow_active(self, flow_name: str, active: bool) -> None:
        with self._db.get_session() as session:
            flow = session.get(FlowState, flow_name)
            if not flow:
                flow = FlowState(name=flow_name, is_active=active)
                session.add(flow)
            else:
                flow.is_active = active
            session.commit()

    # ── Process tracking ──────────────────────────────────────────────────────

    def register_process(self, run_id: str, pid: int, log_path: str) -> None:
        with self._db.get_session() as session:
            run = session.get(Run, run_id)
            if run:
                run.pid = pid
                run.log_path = log_path
                session.commit()

    def record_process_exit(self, run_id: str, exit_code: int) -> None:
        with self._db.get_session() as session:
            run = session.get(Run, run_id)
            if run:
                run.exit_code = exit_code
                session.commit()

    def get_process_info(self, run_id: str) -> dict[str, Any] | None:
        with self._db.get_session() as session:
            run = session.get(Run, run_id)
            if run:
                return {"pid": run.pid, "log_path": run.log_path, "exit_code": run.exit_code}
            return None

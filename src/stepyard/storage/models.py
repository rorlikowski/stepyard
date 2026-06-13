from datetime import datetime, timezone
from typing import Any

from sqlmodel import JSON, Field, SQLModel


class Project(SQLModel, table=True):
    __tablename__ = "projects"
    path: str = Field(primary_key=True)
    registered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FlowState(SQLModel, table=True):
    __tablename__ = "flows"
    name: str = Field(primary_key=True)
    is_active: bool = Field(default=True)


class Run(SQLModel, table=True):
    __tablename__ = "runs"
    id: str = Field(primary_key=True)
    flow_name: str
    status: str = Field(default="queued")
    error: str | None = None
    trigger_type: str | None = None
    trigger_event_id: str | None = None
    trigger_payload: Any | None = Field(default=None, sa_type=JSON)
    start_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: datetime | None = None
    pid: int | None = None
    log_path: str | None = None
    exit_code: int | None = None


class StepRun(SQLModel, table=True):
    __tablename__ = "step_runs"
    # Using a composite primary key would be better, but SQLModel requires an id for simple models sometimes,
    # or we can use multi-field PK. Let's just use an artificial ID for simplicity and run_id/step_id index.
    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(index=True)
    step_id: str
    status: str = Field(default="pending")
    attempt: int = Field(default=1)
    inputs: str | None = Field(default=None)
    output: str | None = Field(default=None)
    error: str | None = None
    start_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: datetime | None = None


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_logs"
    id: int | None = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    action: str
    actor: str
    target: str | None = None
    details: str | None = None

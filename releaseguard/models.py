from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now():
    # Store UTC consistently; SQLite does not preserve timezone information.
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)


class Endpoint(Base):
    __tablename__ = "endpoints"
    __table_args__ = (UniqueConstraint("project_id", "path"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    name: Mapped[str] = mapped_column(String(100))
    path: Mapped[str] = mapped_column(String(200))
    contract: Mapped[str] = mapped_column(String(30))
    expected_status: Mapped[int] = mapped_column(default=200)


class Release(Base):
    __tablename__ = "releases"
    __table_args__ = (UniqueConstraint("project_id", "label"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    label: Mapped[str] = mapped_column(String(100))
    variant: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("releases.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    config: Mapped[dict] = mapped_column(JSON)
    config_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(20), default="QUEUED", index=True)
    attempt: Mapped[int] = mapped_column(default=0)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    error: Mapped[str | None] = mapped_column(String(500))


class Probe(Base):
    __tablename__ = "probes"
    __table_args__ = (
        UniqueConstraint("run_id", "attempt", "endpoint_id", "window", "probe_index"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    attempt: Mapped[int] = mapped_column()
    endpoint_id: Mapped[int] = mapped_column(ForeignKey("endpoints.id"))
    window: Mapped[int] = mapped_column()
    probe_index: Mapped[int] = mapped_column()
    elapsed_ms: Mapped[float] = mapped_column(Float)
    status_code: Mapped[int | None] = mapped_column(Integer)
    response_bytes: Mapped[int | None] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(30))
    detail: Mapped[str] = mapped_column(String(500), default="")


class Window(Base):
    __tablename__ = "windows"
    __table_args__ = (UniqueConstraint("run_id", "attempt", "endpoint_id", "window"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    attempt: Mapped[int] = mapped_column()
    endpoint_id: Mapped[int] = mapped_column(ForeignKey("endpoints.id"))
    window: Mapped[int] = mapped_column()
    stats: Mapped[dict] = mapped_column(JSON)
    model_version: Mapped[str | None] = mapped_column(String(100))
    anomaly_score: Mapped[float | None] = mapped_column(Float)
    anomaly: Mapped[bool | None] = mapped_column()
    ml_note: Mapped[str] = mapped_column(String(200), default="Baseline not ready")

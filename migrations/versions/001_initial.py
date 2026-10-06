"""Initial persistent schema. Keep this revision fixed as the code evolves."""

import sqlalchemy as sa
from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
    )
    op.create_table(
        "endpoints",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("path", sa.String(200), nullable=False),
        sa.Column("contract", sa.String(30), nullable=False),
        sa.Column("expected_status", sa.Integer(), nullable=False),
        sa.UniqueConstraint("project_id", "path"),
    )
    op.create_table(
        "releases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("variant", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("project_id", "label"),
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("release_id", sa.Integer(), sa.ForeignKey("releases.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False, unique=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("lease_token", sa.String(36)),
        sa.Column("heartbeat_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("error", sa.String(500)),
    )
    op.create_index("ix_runs_release_id", "runs", ["release_id"])
    op.create_index("ix_runs_state", "runs", ["state"])
    op.create_table(
        "probes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("endpoint_id", sa.Integer(), sa.ForeignKey("endpoints.id"), nullable=False),
        sa.Column("window", sa.Integer(), nullable=False),
        sa.Column("probe_index", sa.Integer(), nullable=False),
        sa.Column("elapsed_ms", sa.Float(), nullable=False),
        sa.Column("status_code", sa.Integer()),
        sa.Column("response_bytes", sa.Integer()),
        sa.Column("outcome", sa.String(30), nullable=False),
        sa.Column("detail", sa.String(500), nullable=False),
        sa.UniqueConstraint("run_id", "attempt", "endpoint_id", "window", "probe_index"),
    )
    op.create_index("ix_probes_run_id", "probes", ["run_id"])
    op.create_table(
        "windows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("endpoint_id", sa.Integer(), sa.ForeignKey("endpoints.id"), nullable=False),
        sa.Column("window", sa.Integer(), nullable=False),
        sa.Column("stats", sa.JSON(), nullable=False),
        sa.Column("model_version", sa.String(100)),
        sa.Column("anomaly_score", sa.Float()),
        sa.Column("anomaly", sa.Boolean()),
        sa.Column("ml_note", sa.String(200), nullable=False),
        sa.UniqueConstraint("run_id", "attempt", "endpoint_id", "window"),
    )
    op.create_index("ix_windows_run_id", "windows", ["run_id"])


def downgrade():
    for name in ("windows", "probes", "runs", "releases", "endpoints", "projects"):
        op.drop_table(name)

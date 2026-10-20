"""Create the work-order foundation tables.

Revision ID: 20261019_0001
Revises:
Create Date: 2026-10-19 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20261019_0001"
down_revision = None
branch_labels = None
depends_on = None


automation_mode = sa.Enum(
    "manual_only",
    "auto_triage",
    "auto_validate",
    "approval_required",
    "auto_execute_limited",
    name="automation_mode",
    native_enum=False,
    create_constraint=True,
)
work_order_status = sa.Enum(
    "RECEIVED",
    "WAITING_MANUAL",
    "QUEUED",
    "PROCESSING",
    "CONTEXT_READY",
    "DIAGNOSED",
    "PLAN_READY",
    "SANDBOX_PASSED",
    "DRY_RUN_PASSED",
    "PENDING_APPROVAL",
    "EXECUTING",
    "VERIFYING",
    "CANCEL_REQUESTED",
    "RESOLVED",
    "ROLLED_BACK",
    "ESCALATED",
    "FAILED",
    "CANCELED",
    name="work_order_status",
    native_enum=False,
    create_constraint=True,
)
audit_from_status = sa.Enum(
    "RECEIVED",
    "WAITING_MANUAL",
    "QUEUED",
    "PROCESSING",
    "CONTEXT_READY",
    "DIAGNOSED",
    "PLAN_READY",
    "SANDBOX_PASSED",
    "DRY_RUN_PASSED",
    "PENDING_APPROVAL",
    "EXECUTING",
    "VERIFYING",
    "CANCEL_REQUESTED",
    "RESOLVED",
    "ROLLED_BACK",
    "ESCALATED",
    "FAILED",
    "CANCELED",
    name="audit_from_status",
    native_enum=False,
    create_constraint=True,
)
audit_to_status = sa.Enum(
    "RECEIVED",
    "WAITING_MANUAL",
    "QUEUED",
    "PROCESSING",
    "CONTEXT_READY",
    "DIAGNOSED",
    "PLAN_READY",
    "SANDBOX_PASSED",
    "DRY_RUN_PASSED",
    "PENDING_APPROVAL",
    "EXECUTING",
    "VERIFYING",
    "CANCEL_REQUESTED",
    "RESOLVED",
    "ROLLED_BACK",
    "ESCALATED",
    "FAILED",
    "CANCELED",
    name="audit_to_status",
    native_enum=False,
    create_constraint=True,
)
audit_event_type = sa.Enum(
    "work_order.created",
    "root_cause_event.received",
    "work_order.status_changed",
    "work_order.manual_triggered",
    "work_order.retry_requested",
    "work_order.cancellation_requested",
    name="audit_event_type",
    native_enum=False,
    create_constraint=True,
)


def upgrade() -> None:
    op.create_table(
        "work_orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("status", work_order_status, nullable=False),
        sa.Column("automation_mode", automation_mode, nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_work_orders_status", "work_orders", ["status"])
    op.create_index("ix_work_orders_next_run_at", "work_orders", ["next_run_at"])
    op.create_index("ix_work_orders_lease_expires_at", "work_orders", ["lease_expires_at"])

    op.create_table(
        "root_cause_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("work_order_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("external_event_id", sa.String(length=256), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("correlation_key", sa.String(length=256), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["work_order_id"], ["work_orders.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "external_event_id", name="uq_root_cause_event_source_external_id"),
    )
    op.create_index("ix_root_cause_events_work_order_id", "root_cause_events", ["work_order_id"])
    op.create_index("ix_root_cause_events_correlation_key", "root_cause_events", ["correlation_key"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("work_order_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", audit_event_type, nullable=False),
        sa.Column("from_status", audit_from_status, nullable=True),
        sa.Column("to_status", audit_to_status, nullable=True),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["work_order_id"], ["work_orders.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_work_order_id", "audit_events", ["work_order_id"])
    op.create_index("ix_audit_events_work_order_created", "audit_events", ["work_order_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_work_order_created", table_name="audit_events")
    op.drop_index("ix_audit_events_work_order_id", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_root_cause_events_correlation_key", table_name="root_cause_events")
    op.drop_index("ix_root_cause_events_work_order_id", table_name="root_cause_events")
    op.drop_table("root_cause_events")
    op.drop_index("ix_work_orders_lease_expires_at", table_name="work_orders")
    op.drop_index("ix_work_orders_next_run_at", table_name="work_orders")
    op.drop_index("ix_work_orders_status", table_name="work_orders")
    op.drop_table("work_orders")

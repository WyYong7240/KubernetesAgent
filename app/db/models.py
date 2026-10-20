from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, JSON, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import AuditEventType, AutomationMode, WorkOrderStatus


def enum_column(enum_class: type, name: str) -> Enum:
    return Enum(
        enum_class,
        name=name,
        native_enum=False,
        create_constraint=True,
        values_callable=lambda members: [member.value for member in members],
    )


class WorkOrder(Base):
    __tablename__ = "work_orders"
    # Return server-generated updated_at on UPDATE, without async lazy loading.
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    status: Mapped[WorkOrderStatus] = mapped_column(
        enum_column(WorkOrderStatus, "work_order_status"), nullable=False, index=True
    )
    automation_mode: Mapped[AutomationMode] = mapped_column(
        enum_column(AutomationMode, "automation_mode"), nullable=False
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100, server_default="100")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    root_cause_events: Mapped[list["RootCauseEvent"]] = relationship(back_populates="work_order")
    audit_events: Mapped[list["AuditEvent"]] = relationship(
        back_populates="work_order", order_by="AuditEvent.created_at"
    )


class RootCauseEvent(Base):
    __tablename__ = "root_cause_events"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    work_order_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("work_orders.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    external_event_id: Mapped[str] = mapped_column(String(256), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    correlation_key: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    work_order: Mapped[WorkOrder] = relationship(back_populates="root_cause_events")

    __table_args__ = (
        UniqueConstraint("source", "external_event_id", name="uq_root_cause_event_source_external_id"),
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    work_order_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("work_orders.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    event_type: Mapped[AuditEventType] = mapped_column(
        enum_column(AuditEventType, "audit_event_type"), nullable=False
    )
    from_status: Mapped[WorkOrderStatus | None] = mapped_column(
        enum_column(WorkOrderStatus, "audit_from_status"), nullable=True
    )
    to_status: Mapped[WorkOrderStatus | None] = mapped_column(
        enum_column(WorkOrderStatus, "audit_to_status"), nullable=True
    )
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    work_order: Mapped[WorkOrder] = relationship(back_populates="audit_events")

    __table_args__ = (Index("ix_audit_events_work_order_created", "work_order_id", "created_at"),)

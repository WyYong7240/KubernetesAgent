from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditEvent
from app.models.enums import AuditEventType, WorkOrderStatus


def append_audit_event(
    session: AsyncSession,
    *,
    work_order_id: UUID,
    event_type: AuditEventType,
    actor_type: str,
    actor_id: str | None = None,
    from_status: WorkOrderStatus | None = None,
    to_status: WorkOrderStatus | None = None,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        work_order_id=work_order_id,
        event_type=event_type,
        actor_type=actor_type,
        actor_id=actor_id,
        from_status=from_status,
        to_status=to_status,
        details=details or {},
    )
    session.add(event)
    return event

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import re
from typing import Any
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.audit.service import append_audit_event
from app.db.models import RootCauseEvent, WorkOrder
from app.models.api import RootCauseEventCreate
from app.models.enums import AuditEventType, AutomationMode, WorkOrderStatus
from app.work_orders.transitions import InvalidStateTransition, ensure_transition

SENSITIVE_KEY = re.compile(r"(?:api[-_]?key|authorization|password|secret|token)", re.IGNORECASE)


class WorkOrderNotFoundError(LookupError):
    pass


class WorkOrderStateError(ValueError):
    pass


def redact_sensitive_values(value: Any, key: str | None = None) -> Any:
    """Persist incident evidence safely without retaining common credential fields."""
    if key and SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): redact_sensitive_values(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [redact_sensitive_values(item) for item in value]
    return value


def canonical_payload_hash(payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class WorkOrderService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def ingest_event(self, event: RootCauseEventCreate) -> tuple[RootCauseEvent, WorkOrder, bool]:
        payload = redact_sensitive_values(event.model_dump(mode="json"))
        initial_target = (
            WorkOrderStatus.WAITING_MANUAL
            if event.automation_mode is AutomationMode.MANUAL_ONLY
            else WorkOrderStatus.QUEUED
        )

        try:
            async with self.session.begin():
                existing = await self.session.scalar(
                    select(RootCauseEvent)
                    .options(selectinload(RootCauseEvent.work_order))
                    .where(
                        RootCauseEvent.source == event.source,
                        RootCauseEvent.external_event_id == event.external_event_id,
                    )
                )
                if existing is not None:
                    return existing, existing.work_order, True

                work_order = WorkOrder(
                    status=WorkOrderStatus.RECEIVED,
                    automation_mode=event.automation_mode,
                    next_run_at=datetime.now(UTC) if initial_target is WorkOrderStatus.QUEUED else None,
                )
                self.session.add(work_order)
                await self.session.flush()
                append_audit_event(
                    self.session,
                    work_order_id=work_order.id,
                    event_type=AuditEventType.WORK_ORDER_CREATED,
                    actor_type="system",
                    to_status=WorkOrderStatus.RECEIVED,
                )

                root_cause_event = RootCauseEvent(
                    work_order_id=work_order.id,
                    source=event.source,
                    external_event_id=event.external_event_id,
                    schema_version=event.schema_version,
                    correlation_key=event.correlation_key,
                    payload=payload,
                    payload_hash=canonical_payload_hash(payload),
                )
                self.session.add(root_cause_event)
                append_audit_event(
                    self.session,
                    work_order_id=work_order.id,
                    event_type=AuditEventType.ROOT_CAUSE_EVENT_RECEIVED,
                    actor_type="ingress",
                    details={"source": event.source, "external_event_id": event.external_event_id},
                )
                self._transition_in_transaction(
                    work_order,
                    initial_target,
                    event_type=AuditEventType.STATUS_CHANGED,
                    actor_type="system",
                )
                await self.session.flush()
            return root_cause_event, work_order, False
        except IntegrityError:
            # A competing request may have inserted the unique event after the initial lookup.
            async with self.session.begin():
                existing = await self.session.scalar(
                    select(RootCauseEvent)
                    .options(selectinload(RootCauseEvent.work_order))
                    .where(
                        RootCauseEvent.source == event.source,
                        RootCauseEvent.external_event_id == event.external_event_id,
                    )
                )
            if existing is None:
                raise
            return existing, existing.work_order, True

    async def get_work_order(self, work_order_id: UUID) -> WorkOrder:
        if self.session.in_transaction():
            return await self._load_work_order(work_order_id)
        async with self.session.begin():
            return await self._load_work_order(work_order_id)

    async def _load_work_order(self, work_order_id: UUID) -> WorkOrder:
        statement: Select[tuple[WorkOrder]] = (
            select(WorkOrder)
            .options(
                selectinload(WorkOrder.root_cause_events),
                selectinload(WorkOrder.audit_events),
            )
            .where(WorkOrder.id == work_order_id)
        )
        work_order = await self.session.scalar(statement)
        if work_order is None:
            raise WorkOrderNotFoundError(str(work_order_id))
        return work_order

    async def list_work_orders(self, limit: int = 50) -> list[WorkOrder]:
        statement = (
            select(WorkOrder)
            .order_by(WorkOrder.created_at.desc())
            .limit(limit)
        )
        if self.session.in_transaction():
            return list((await self.session.scalars(statement)).all())
        async with self.session.begin():
            return list((await self.session.scalars(statement)).all())

    async def trigger_manual(self, work_order_id: UUID, actor_id: str | None) -> WorkOrder:
        return await self._change_state(
            work_order_id,
            WorkOrderStatus.QUEUED,
            event_type=AuditEventType.MANUAL_TRIGGERED,
            actor_type="human",
            actor_id=actor_id,
            update_next_run=True,
            allowed_sources={WorkOrderStatus.WAITING_MANUAL},
        )

    async def retry(self, work_order_id: UUID, actor_id: str | None) -> WorkOrder:
        return await self._change_state(
            work_order_id,
            WorkOrderStatus.QUEUED,
            event_type=AuditEventType.RETRY_REQUESTED,
            actor_type="human",
            actor_id=actor_id,
            update_next_run=True,
            increment_attempt=True,
            allowed_sources={WorkOrderStatus.FAILED, WorkOrderStatus.ESCALATED},
        )

    async def cancel(self, work_order_id: UUID, actor_id: str | None) -> WorkOrder:
        async with self.session.begin():
            work_order = await self._get_work_order_for_update(work_order_id)
            target = (
                WorkOrderStatus.CANCEL_REQUESTED
                if work_order.status in {WorkOrderStatus.EXECUTING, WorkOrderStatus.VERIFYING}
                else WorkOrderStatus.CANCELED
            )
            try:
                self._transition_in_transaction(
                    work_order,
                    target,
                    event_type=AuditEventType.CANCELLATION_REQUESTED,
                    actor_type="human",
                    actor_id=actor_id,
                )
            except InvalidStateTransition as error:
                raise WorkOrderStateError(str(error)) from error
            await self.session.flush()
        return work_order

    async def _change_state(
        self,
        work_order_id: UUID,
        target: WorkOrderStatus,
        *,
        event_type: AuditEventType,
        actor_type: str,
        actor_id: str | None,
        update_next_run: bool = False,
        increment_attempt: bool = False,
        allowed_sources: set[WorkOrderStatus] | None = None,
    ) -> WorkOrder:
        async with self.session.begin():
            work_order = await self._get_work_order_for_update(work_order_id)
            if allowed_sources is not None and work_order.status not in allowed_sources:
                raise WorkOrderStateError(f"Operation is not allowed in status {work_order.status}.")
            try:
                self._transition_in_transaction(
                    work_order,
                    target,
                    event_type=event_type,
                    actor_type=actor_type,
                    actor_id=actor_id,
                )
            except InvalidStateTransition as error:
                raise WorkOrderStateError(str(error)) from error
            if update_next_run:
                work_order.next_run_at = datetime.now(UTC)
                work_order.lease_owner = None
                work_order.lease_expires_at = None
            if increment_attempt:
                work_order.attempt_count += 1
            await self.session.flush()
        return work_order

    async def _get_work_order_for_update(self, work_order_id: UUID) -> WorkOrder:
        work_order = await self.session.scalar(
            select(WorkOrder).where(WorkOrder.id == work_order_id).with_for_update()
        )
        if work_order is None:
            raise WorkOrderNotFoundError(str(work_order_id))
        return work_order

    def _transition_in_transaction(
        self,
        work_order: WorkOrder,
        target: WorkOrderStatus,
        *,
        event_type: AuditEventType,
        actor_type: str,
        actor_id: str | None = None,
    ) -> None:
        source = work_order.status
        ensure_transition(source, target)
        work_order.status = target
        work_order.row_version += 1
        append_audit_event(
            self.session,
            work_order_id=work_order.id,
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id,
            from_status=source,
            to_status=target,
        )

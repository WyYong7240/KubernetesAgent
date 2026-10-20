from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db import models  # noqa: F401 - load mappings into Base.metadata
from app.models.api import RootCauseEventCreate
from app.models.enums import AuditEventType, AutomationMode, WorkOrderStatus
from app.work_orders.service import WorkOrderService


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as db_session:
        yield db_session
    await engine.dispose()


def event_payload(*, external_event_id: str, mode: AutomationMode = AutomationMode.MANUAL_ONLY) -> RootCauseEventCreate:
    return RootCauseEventCreate(
        source="dagger",
        external_event_id=external_event_id,
        occurred_at=datetime(2026, 10, 19, tzinfo=UTC),
        scope={"cluster": "prod-cn-01", "namespace": "payments"},
        root_cause={"summary": "database connection pool exhausted", "confidence": 0.87},
        automation_mode=mode,
    )


@pytest.mark.asyncio
async def test_ingress_is_idempotent_and_manual_work_requires_trigger(session: AsyncSession) -> None:
    service = WorkOrderService(session)

    event, order, deduplicated = await service.ingest_event(event_payload(external_event_id="dagger-001"))

    assert deduplicated is False
    assert order.status is WorkOrderStatus.WAITING_MANUAL
    assert len((await service.get_work_order(order.id)).audit_events) == 3

    duplicate_event, duplicate_order, deduplicated = await service.ingest_event(
        event_payload(external_event_id="dagger-001")
    )

    assert deduplicated is True
    assert duplicate_event.id == event.id
    assert duplicate_order.id == order.id
    assert len((await service.get_work_order(order.id)).audit_events) == 3

    triggered = await service.trigger_manual(order.id, actor_id="operator-1")
    assert triggered.status is WorkOrderStatus.QUEUED

    await service._change_state(
        order.id,
        WorkOrderStatus.PROCESSING,
        event_type=AuditEventType.STATUS_CHANGED,
        actor_type="worker",
        actor_id="worker-1",
    )
    await service._change_state(
        order.id,
        WorkOrderStatus.FAILED,
        event_type=AuditEventType.STATUS_CHANGED,
        actor_type="worker",
        actor_id="worker-1",
    )
    retried = await service.retry(order.id, actor_id="operator-1")
    assert retried.status is WorkOrderStatus.QUEUED
    assert retried.attempt_count == 1


@pytest.mark.asyncio
async def test_auto_triage_is_queued_and_cancellation_is_audited(session: AsyncSession) -> None:
    service = WorkOrderService(session)
    _, order, _ = await service.ingest_event(
        event_payload(external_event_id="dagger-002", mode=AutomationMode.AUTO_TRIAGE)
    )

    assert order.status is WorkOrderStatus.QUEUED
    canceled = await service.cancel(order.id, actor_id="operator-2")

    assert canceled.status is WorkOrderStatus.CANCELED
    detail = await service.get_work_order(order.id)
    assert detail.audit_events[-1].to_status is WorkOrderStatus.CANCELED

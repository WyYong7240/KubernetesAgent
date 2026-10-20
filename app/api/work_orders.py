from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import verify_dagger_signature
from app.db.models import WorkOrder
from app.db.session import get_session
from app.models.api import (
    AuditEventResponse,
    RootCauseEventCreate,
    RootCauseEventDetailResponse,
    RootCauseEventReceipt,
    WorkOrderDetailResponse,
    WorkOrderResponse,
)
from app.work_orders.service import WorkOrderNotFoundError, WorkOrderService, WorkOrderStateError

router = APIRouter(prefix="/api/v1", tags=["work-orders"])


def work_order_response(work_order: WorkOrder) -> WorkOrderResponse:
    return WorkOrderResponse(
        id=work_order.id,
        status=work_order.status,
        automation_mode=work_order.automation_mode,
        priority=work_order.priority,
        attempt_count=work_order.attempt_count,
        next_run_at=work_order.next_run_at,
        lease_owner=work_order.lease_owner,
        lease_expires_at=work_order.lease_expires_at,
        created_at=work_order.created_at,
        updated_at=work_order.updated_at,
    )


def detail_response(work_order: WorkOrder) -> WorkOrderDetailResponse:
    base = work_order_response(work_order)
    return WorkOrderDetailResponse(
        **base.model_dump(),
        root_cause_events=[
            RootCauseEventDetailResponse(
                id=event.id,
                source=event.source,
                external_event_id=event.external_event_id,
                schema_version=event.schema_version,
                correlation_key=event.correlation_key,
                payload=event.payload,
                payload_hash=event.payload_hash,
                received_at=event.received_at,
            )
            for event in work_order.root_cause_events
        ],
        audit_events=[
            AuditEventResponse(
                id=event.id,
                event_type=event.event_type,
                from_status=event.from_status,
                to_status=event.to_status,
                actor_type=event.actor_type,
                actor_id=event.actor_id,
                details=event.details,
                created_at=event.created_at,
            )
            for event in work_order.audit_events
        ],
    )


@router.post(
    "/root-cause-events",
    response_model=RootCauseEventReceipt,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_dagger_signature)],
)
async def receive_root_cause_event(
    event: RootCauseEventCreate,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> RootCauseEventReceipt:
    service = WorkOrderService(session)
    root_cause_event, work_order, deduplicated = await service.ingest_event(event)
    if deduplicated:
        response.status_code = status.HTTP_200_OK
    return RootCauseEventReceipt(
        event_id=root_cause_event.id,
        work_order_id=work_order.id,
        status=work_order.status,
        deduplicated=deduplicated,
    )


@router.get("/work-orders", response_model=list[WorkOrderResponse])
async def list_work_orders(
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
) -> list[WorkOrderResponse]:
    bounded_limit = min(max(limit, 1), 100)
    return [work_order_response(item) for item in await WorkOrderService(session).list_work_orders(bounded_limit)]


@router.get("/work-orders/{work_order_id}", response_model=WorkOrderDetailResponse)
async def get_work_order(
    work_order_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> WorkOrderDetailResponse:
    try:
        return detail_response(await WorkOrderService(session).get_work_order(work_order_id))
    except WorkOrderNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found.") from error


async def change_state_response(
    operation: str,
    work_order_id: UUID,
    actor_id: str | None,
    session: AsyncSession,
) -> WorkOrderResponse:
    service = WorkOrderService(session)
    try:
        if operation == "trigger":
            work_order = await service.trigger_manual(work_order_id, actor_id)
        elif operation == "retry":
            work_order = await service.retry(work_order_id, actor_id)
        else:
            work_order = await service.cancel(work_order_id, actor_id)
        return work_order_response(work_order)
    except WorkOrderNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found.") from error
    except WorkOrderStateError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.post("/work-orders/{work_order_id}/trigger", response_model=WorkOrderResponse)
async def trigger_work_order(
    work_order_id: UUID,
    x_actor_id: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> WorkOrderResponse:
    return await change_state_response("trigger", work_order_id, x_actor_id, session)


@router.post("/work-orders/{work_order_id}/retry", response_model=WorkOrderResponse)
async def retry_work_order(
    work_order_id: UUID,
    x_actor_id: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> WorkOrderResponse:
    return await change_state_response("retry", work_order_id, x_actor_id, session)


@router.post("/work-orders/{work_order_id}/cancel", response_model=WorkOrderResponse)
async def cancel_work_order(
    work_order_id: UUID,
    x_actor_id: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> WorkOrderResponse:
    return await change_state_response("cancel", work_order_id, x_actor_id, session)

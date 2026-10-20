from __future__ import annotations

from app.models.enums import WorkOrderStatus


TERMINAL_STATUSES = frozenset(
    {
        WorkOrderStatus.RESOLVED,
        WorkOrderStatus.ROLLED_BACK,
        WorkOrderStatus.ESCALATED,
        WorkOrderStatus.FAILED,
        WorkOrderStatus.CANCELED,
    }
)

ALLOWED_TRANSITIONS: dict[WorkOrderStatus, frozenset[WorkOrderStatus]] = {
    WorkOrderStatus.RECEIVED: frozenset(
        {WorkOrderStatus.WAITING_MANUAL, WorkOrderStatus.QUEUED, WorkOrderStatus.CANCELED}
    ),
    WorkOrderStatus.WAITING_MANUAL: frozenset({WorkOrderStatus.QUEUED, WorkOrderStatus.CANCELED}),
    WorkOrderStatus.QUEUED: frozenset({WorkOrderStatus.PROCESSING, WorkOrderStatus.CANCELED}),
    WorkOrderStatus.PROCESSING: frozenset(
        {
            WorkOrderStatus.CONTEXT_READY,
            WorkOrderStatus.FAILED,
            WorkOrderStatus.ESCALATED,
            WorkOrderStatus.CANCELED,
        }
    ),
    WorkOrderStatus.CONTEXT_READY: frozenset(
        {WorkOrderStatus.DIAGNOSED, WorkOrderStatus.FAILED, WorkOrderStatus.CANCELED}
    ),
    WorkOrderStatus.DIAGNOSED: frozenset(
        {WorkOrderStatus.PLAN_READY, WorkOrderStatus.FAILED, WorkOrderStatus.CANCELED}
    ),
    WorkOrderStatus.PLAN_READY: frozenset(
        {WorkOrderStatus.SANDBOX_PASSED, WorkOrderStatus.FAILED, WorkOrderStatus.CANCELED}
    ),
    WorkOrderStatus.SANDBOX_PASSED: frozenset(
        {WorkOrderStatus.DRY_RUN_PASSED, WorkOrderStatus.FAILED, WorkOrderStatus.CANCELED}
    ),
    WorkOrderStatus.DRY_RUN_PASSED: frozenset(
        {WorkOrderStatus.PENDING_APPROVAL, WorkOrderStatus.FAILED, WorkOrderStatus.CANCELED}
    ),
    WorkOrderStatus.PENDING_APPROVAL: frozenset(
        {WorkOrderStatus.EXECUTING, WorkOrderStatus.CANCELED, WorkOrderStatus.ESCALATED}
    ),
    WorkOrderStatus.EXECUTING: frozenset(
        {
            WorkOrderStatus.VERIFYING,
            WorkOrderStatus.FAILED,
            WorkOrderStatus.ESCALATED,
            WorkOrderStatus.CANCEL_REQUESTED,
        }
    ),
    WorkOrderStatus.VERIFYING: frozenset(
        {
            WorkOrderStatus.RESOLVED,
            WorkOrderStatus.ROLLED_BACK,
            WorkOrderStatus.FAILED,
            WorkOrderStatus.ESCALATED,
            WorkOrderStatus.CANCEL_REQUESTED,
        }
    ),
    WorkOrderStatus.CANCEL_REQUESTED: frozenset(
        {WorkOrderStatus.CANCELED, WorkOrderStatus.ESCALATED}
    ),
    WorkOrderStatus.FAILED: frozenset({WorkOrderStatus.QUEUED}),
    WorkOrderStatus.ESCALATED: frozenset({WorkOrderStatus.QUEUED}),
    WorkOrderStatus.RESOLVED: frozenset(),
    WorkOrderStatus.ROLLED_BACK: frozenset(),
    WorkOrderStatus.CANCELED: frozenset(),
}


class InvalidStateTransition(ValueError):
    pass


def ensure_transition(source: WorkOrderStatus, target: WorkOrderStatus) -> None:
    if target not in ALLOWED_TRANSITIONS[source]:
        raise InvalidStateTransition(f"Cannot transition work order from {source} to {target}.")

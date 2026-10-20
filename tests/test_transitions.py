import pytest

from app.models.enums import WorkOrderStatus
from app.work_orders.transitions import InvalidStateTransition, ensure_transition


def test_manual_trigger_is_allowed() -> None:
    ensure_transition(WorkOrderStatus.WAITING_MANUAL, WorkOrderStatus.QUEUED)


def test_non_executing_order_can_be_canceled() -> None:
    ensure_transition(WorkOrderStatus.PENDING_APPROVAL, WorkOrderStatus.CANCELED)


def test_executing_order_requires_cancel_requested() -> None:
    ensure_transition(WorkOrderStatus.EXECUTING, WorkOrderStatus.CANCEL_REQUESTED)
    with pytest.raises(InvalidStateTransition):
        ensure_transition(WorkOrderStatus.EXECUTING, WorkOrderStatus.CANCELED)


def test_only_failed_or_escalated_order_can_retry() -> None:
    ensure_transition(WorkOrderStatus.FAILED, WorkOrderStatus.QUEUED)
    ensure_transition(WorkOrderStatus.ESCALATED, WorkOrderStatus.QUEUED)
    with pytest.raises(InvalidStateTransition):
        ensure_transition(WorkOrderStatus.CANCELED, WorkOrderStatus.QUEUED)

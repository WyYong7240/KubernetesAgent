from enum import StrEnum


class AutomationMode(StrEnum):
    MANUAL_ONLY = "manual_only"
    AUTO_TRIAGE = "auto_triage"
    AUTO_VALIDATE = "auto_validate"
    APPROVAL_REQUIRED = "approval_required"
    AUTO_EXECUTE_LIMITED = "auto_execute_limited"


class WorkOrderStatus(StrEnum):
    RECEIVED = "RECEIVED"
    WAITING_MANUAL = "WAITING_MANUAL"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    CONTEXT_READY = "CONTEXT_READY"
    DIAGNOSED = "DIAGNOSED"
    PLAN_READY = "PLAN_READY"
    SANDBOX_PASSED = "SANDBOX_PASSED"
    DRY_RUN_PASSED = "DRY_RUN_PASSED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    RESOLVED = "RESOLVED"
    ROLLED_BACK = "ROLLED_BACK"
    ESCALATED = "ESCALATED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


class AuditEventType(StrEnum):
    WORK_ORDER_CREATED = "work_order.created"
    ROOT_CAUSE_EVENT_RECEIVED = "root_cause_event.received"
    STATUS_CHANGED = "work_order.status_changed"
    MANUAL_TRIGGERED = "work_order.manual_triggered"
    RETRY_REQUESTED = "work_order.retry_requested"
    CANCELLATION_REQUESTED = "work_order.cancellation_requested"

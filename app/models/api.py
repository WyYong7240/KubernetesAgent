from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import AutomationMode, WorkOrderStatus


class WorkloadRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=253)
    uid: str | None = Field(default=None, max_length=256)


class FaultScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cluster: str = Field(min_length=1, max_length=253)
    namespace: str | None = Field(default=None, max_length=63)
    workload: WorkloadRef | None = None


class RootCause(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=10_000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence_refs: list[str] = Field(default_factory=list, max_length=200)


class RootCauseEventCreate(BaseModel):
    """Versioned canonical ingress contract for DAGGER and other event sources."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="1.0", min_length=1, max_length=32)
    source: str = Field(min_length=1, max_length=64)
    external_event_id: str = Field(min_length=1, max_length=256)
    occurred_at: datetime
    scope: FaultScope
    root_cause: RootCause
    correlation_key: str | None = Field(default=None, max_length=256)
    labels: dict[str, str] = Field(default_factory=dict, max_length=100)
    automation_mode: AutomationMode = AutomationMode.MANUAL_ONLY

    @field_validator("automation_mode")
    @classmethod
    def validate_supported_mode(cls, value: AutomationMode) -> AutomationMode:
        if value not in {AutomationMode.MANUAL_ONLY, AutomationMode.AUTO_TRIAGE}:
            raise ValueError("PR1 supports only manual_only and auto_triage")
        return value

    @field_validator("source")
    @classmethod
    def normalize_source(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("source must not be blank")
        return normalized

    @field_validator("external_event_id")
    @classmethod
    def normalize_external_event_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("external_event_id must not be blank")
        return normalized


class RootCauseEventReceipt(BaseModel):
    event_id: UUID
    work_order_id: UUID
    status: WorkOrderStatus
    deduplicated: bool


class RootCauseEventDetailResponse(BaseModel):
    id: UUID
    source: str
    external_event_id: str
    schema_version: str
    correlation_key: str | None
    payload: dict[str, Any]
    payload_hash: str
    received_at: datetime


class AuditEventResponse(BaseModel):
    id: UUID
    event_type: str
    from_status: WorkOrderStatus | None
    to_status: WorkOrderStatus | None
    actor_type: str
    actor_id: str | None
    details: dict[str, Any]
    created_at: datetime


class WorkOrderResponse(BaseModel):
    id: UUID
    status: WorkOrderStatus
    automation_mode: AutomationMode
    priority: int
    attempt_count: int
    next_run_at: datetime | None
    lease_owner: str | None
    lease_expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


class WorkOrderDetailResponse(WorkOrderResponse):
    root_cause_events: list[RootCauseEventDetailResponse]
    audit_events: list[AuditEventResponse]

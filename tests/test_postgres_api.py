"""Real PostgreSQL tests: migrate a private schema, exercise HTTP, then remove it."""

import asyncio
from pathlib import Path
import os
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from app.core.config import Settings
from app.db.models import AuditEvent, RootCauseEvent, WorkOrder
from app.main import create_app
from app.models.enums import WorkOrderStatus


pytestmark = pytest.mark.postgres
PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
async def postgres_app():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration tests")
    if not url.startswith("postgresql+asyncpg://"):
        raise ValueError("TEST_DATABASE_URL must use postgresql+asyncpg")

    # No existing tables are modified: all DDL and test data live in this schema.
    schema = "pr1_test_" + uuid4().hex
    admin_engine = create_async_engine(url)
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))

    def migrate(connection):
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        command.upgrade(config, "head")  # A second startup migration must be a no-op.
        command.check(config)  # ORM metadata must match the migrated database.

    async with admin_engine.begin() as connection:
        await connection.execute(CreateSchema(schema))
    try:
        async with engine.begin() as connection:
            await connection.run_sync(migrate)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        app = create_app(Settings(environment="development"))
        async with app.router.lifespan_context(app):
            app.state.session_factory = sessions
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                yield client, sessions
    finally:
        await engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(DropSchema(schema, cascade=True))
        await admin_engine.dispose()


def event(external_id="postgres-api-001", mode="manual_only"):
    return {
        "schema_version": "1.0",
        "source": "dagger",
        "external_event_id": external_id,
        "occurred_at": "2026-10-19T04:00:00Z",
        "scope": {"cluster": "local-test", "namespace": "default"},
        "root_cause": {"summary": "Simulated connection pool exhaustion", "confidence": 0.87},
        "labels": {"api_key": "do-not-persist"},
        "automation_mode": mode,
    }


async def test_event_round_trip_and_manual_actions(postgres_app):
    client, sessions = postgres_app
    created = await client.post("/api/v1/root-cause-events", json=event())
    assert created.status_code == 201, created.text
    receipt = created.json()
    assert receipt["status"] == "WAITING_MANUAL"
    assert receipt["deduplicated"] is False
    order_id = receipt["work_order_id"]
    duplicate = await client.post("/api/v1/root-cause-events", json=event())
    assert duplicate.status_code == 200
    assert duplicate.json() == {**receipt, "deduplicated": True}

    detail = (await client.get(f"/api/v1/work-orders/{order_id}")).json()
    assert len(detail["audit_events"]) == 3
    assert detail["root_cause_events"][0]["payload"]["labels"]["api_key"] == "[REDACTED]"
    assert (await client.post(f"/api/v1/work-orders/{order_id}/retry")).status_code == 409
    triggered = await client.post(f"/api/v1/work-orders/{order_id}/trigger")
    assert triggered.status_code == 200, triggered.text
    assert triggered.json()["status"] == "QUEUED"
    assert triggered.json()["updated_at"]
    assert (await client.post(f"/api/v1/work-orders/{order_id}/trigger")).status_code == 409
    canceled = await client.post(f"/api/v1/work-orders/{order_id}/cancel")
    assert canceled.status_code == 200, canceled.text
    assert canceled.json()["status"] == "CANCELED"
    assert (await client.post(f"/api/v1/work-orders/{order_id}/trigger")).status_code == 409

    # Confirm actual stored enum values, rather than relying on ORM deserialization.
    async with sessions() as session:
        stored = await session.execute(text("SELECT automation_mode FROM work_orders"))
        assert stored.scalar_one() == "manual_only"
        types = (await session.execute(text("SELECT event_type FROM audit_events"))).scalars().all()
        assert "work_order.created" in types
        assert "work_order.cancellation_requested" in types
        schema = await session.scalar(text("SELECT current_schema()"))

    # A separate application and pool must still retrieve the persisted work order.
    restarted_engine = create_async_engine(
        os.environ["TEST_DATABASE_URL"], connect_args={"server_settings": {"search_path": schema}}
    )
    restarted = create_app(Settings(environment="development"))
    try:
        async with restarted.router.lifespan_context(restarted):
            restarted.state.session_factory = async_sessionmaker(restarted_engine, expire_on_commit=False)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted), base_url="http://test") as other:
                assert (await other.get(f"/api/v1/work-orders/{order_id}")).json()["status"] == "CANCELED"
    finally:
        await restarted_engine.dispose()


async def test_concurrent_duplicate_delivery_creates_one_order(postgres_app):
    client, sessions = postgres_app
    responses = await asyncio.gather(*[
        client.post("/api/v1/root-cause-events", json=event("concurrent-001", "auto_triage"))
        for _ in range(6)
    ])
    assert sorted(response.status_code for response in responses) == [200] * 5 + [201]
    assert len({response.json()["work_order_id"] for response in responses}) == 1
    async with sessions() as session:
        assert len((await session.scalars(select(WorkOrder))).all()) == 1
        assert len((await session.scalars(select(RootCauseEvent))).all()) == 1
        assert len((await session.scalars(select(AuditEvent))).all()) == 3


async def test_failed_order_can_retry_but_cannot_use_trigger(postgres_app):
    client, sessions = postgres_app
    receipt = (await client.post("/api/v1/root-cause-events", json=event())).json()
    order_id = receipt["work_order_id"]
    async with sessions.begin() as session:
        order = await session.get(WorkOrder, UUID(order_id))
        order.status = WorkOrderStatus.FAILED  # Simulate a future worker failure.
    assert (await client.post(f"/api/v1/work-orders/{order_id}/trigger")).status_code == 409
    retried = await client.post(f"/api/v1/work-orders/{order_id}/retry")
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "QUEUED"
    assert retried.json()["attempt_count"] == 1


async def test_unsupported_modes_are_rejected(postgres_app):
    client, _ = postgres_app
    response = await client.post("/api/v1/root-cause-events", json=event(mode="auto_execute_limited"))
    assert response.status_code == 422

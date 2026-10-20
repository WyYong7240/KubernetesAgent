from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


VALID_EVENT = {
    "schema_version": "1.0",
    "source": "dagger",
    "external_event_id": "event-001",
    "occurred_at": "2026-10-19T00:00:00Z",
    "scope": {"cluster": "prod-cn-01", "namespace": "payments"},
    "root_cause": {"summary": "connection pool exhausted", "confidence": 0.87},
}


def test_production_dagger_endpoint_requires_secret_configuration() -> None:
    app = create_app(Settings(environment="production"))
    with TestClient(app) as client:
        response = client.post("/api/v1/root-cause-events", json=VALID_EVENT)

    assert response.status_code == 503


def test_invalid_dagger_signature_is_rejected_before_database_access() -> None:
    app = create_app(Settings(environment="production", dagger_webhook_secret="expected-secret"))
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/root-cause-events",
            json=VALID_EVENT,
            headers={"X-Dagger-Signature": "sha256=not-a-valid-signature"},
        )

    assert response.status_code == 401


def test_health_endpoint_does_not_require_database() -> None:
    app = create_app(Settings())
    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

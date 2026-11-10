from fastapi.testclient import TestClient

from app.main import create_app


def test_liveness_responds_without_database_or_provider_connections() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_contains_health_route() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/openapi.json")
    assert "/api/health/live" in response.json()["paths"]

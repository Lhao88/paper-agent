from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.session import get_test_settings
from app.main import create_app
from app.runtime import create_event_loop


def test_readiness_checks_real_test_database_and_storage() -> None:
    with TestClient(
        create_app(get_test_settings()),
        backend_options={
            "loop_factory": create_event_loop,
        },
    ) as client:
        response = client.get("/api/health/ready")
    assert response.status_code == 200
    assert response.json()["database"] == "ok"


def test_liveness_survives_unavailable_database_but_readiness_reports_503() -> None:
    settings = get_settings().model_copy(update={"db_port": 1})
    with TestClient(
        create_app(settings),
        backend_options={
            "loop_factory": create_event_loop,
        },
    ) as client:
        assert client.get("/api/health/live").status_code == 200
        response = client.get("/api/health/ready")
    assert response.status_code == 503
    assert response.json()["database"] == "unavailable"

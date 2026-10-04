from fastapi.testclient import TestClient

from app.main import create_app


def test_health_returns_ok_and_version(settings):
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0"}

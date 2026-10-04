import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import create_app
from tests.fakes import FakeIngestStage, FakeTranscribeStage


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings, stages_factory=lambda: [FakeIngestStage(), FakeTranscribeStage()])) as c:
        yield c


def test_post_from_foreign_origin_is_rejected(client):
    res = client.post("/api/projects", json={"url": "https://youtu.be/abc"}, headers={"Origin": "http://evil.example"})
    assert res.status_code == 403


def test_post_from_allowed_origin_is_accepted(client):
    res = client.post("/api/projects", json={"url": "https://youtu.be/abc"}, headers={"Origin": "http://localhost:5173"})
    assert res.status_code == 201


def test_post_without_origin_is_accepted(client):
    assert client.post("/api/projects", json={"url": "https://youtu.be/abc"}).status_code == 201


def test_get_from_foreign_origin_is_not_blocked(client):
    assert client.get("/api/health", headers={"Origin": "http://evil.example"}).status_code == 200


def test_bad_host_header_is_rejected(client):
    assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 400


@pytest.mark.parametrize("host", ["localhost:8000", "127.0.0.1:8000", "testserver"])
def test_local_hosts_are_allowed(client, host):
    assert client.get("/api/health", headers={"Host": host}).status_code == 200


def test_websocket_from_foreign_origin_is_rejected(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/jobs/nope/events", headers={"Origin": "http://evil.example"}) as ws:
            ws.receive_text()


def test_websocket_from_allowed_origin_connects(client):
    project = client.post("/api/projects", json={"url": "https://youtu.be/abc"}).json()
    job_id = project["latest_job"]["id"]
    with client.websocket_connect(f"/api/jobs/{job_id}/events", headers={"Origin": "http://localhost:5173"}) as ws:
        assert ws.receive_json()["job_id"] == job_id

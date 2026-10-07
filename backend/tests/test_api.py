import time

import pytest
from fastapi.testclient import TestClient

from app import repo
from app.db import make_engine
from app.main import create_app
from app.models import JobStatus
from app.pipeline.ingest import IngestStage
from tests.fakes import FakeIngestStage, FakeTranscribeStage


@pytest.fixture
def make_client(settings):
    clients: list[TestClient] = []

    def _make(stages) -> TestClient:
        client = TestClient(create_app(settings, stages_factory=lambda: stages))
        client.__enter__()
        clients.append(client)
        return client

    yield _make
    for client in clients:
        client.__exit__(None, None, None)


def wait_job(client, job_id, *statuses, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in statuses:
            return job
        time.sleep(0.03)
    raise AssertionError(f"job stuck: {client.get(f'/api/jobs/{job_id}').json()}")


def test_create_from_url_runs_pipeline(make_client):
    client = make_client([FakeIngestStage(), FakeTranscribeStage()])
    res = client.post("/api/projects", json={"url": "https://youtu.be/abc?t=3"})
    assert res.status_code == 201
    project = res.json()
    assert project["source_url"] == "https://youtu.be/abc?t=3"
    job = wait_job(client, project["latest_job"]["id"], "succeeded")
    assert job["progress"] == 1.0
    assert job["created_at"].endswith(("Z", "+00:00"))  # timezone-aware
    refreshed = client.get(f"/api/projects/{project['id']}").json()
    assert refreshed["title"] == "Fake video"
    transcript = client.get(f"/api/projects/{project['id']}/transcript").json()
    assert transcript["language"] == "en" and len(transcript["segments"]) == 1


def test_invalid_url_is_rejected(make_client):
    client = make_client([FakeIngestStage()])
    res = client.post("/api/projects", json={"url": "javascript:alert(1)"})
    assert res.status_code == 422
    assert "http" in res.json()["detail"]


def test_upload_saves_file_and_starts_job(make_client, settings, sample_video):
    client = make_client([FakeIngestStage(), FakeTranscribeStage()])
    with sample_video.open("rb") as f:
        res = client.post("/api/projects/upload", files={"file": ("my vidéo.MP4", f, "video/mp4")})
    assert res.status_code == 201
    project = res.json()
    assert project["original_filename"] == "my vidéo.MP4"
    upload = settings.workspace_dir / "projects" / project["id"] / "upload.mp4"
    assert upload.exists() and upload.stat().st_size == sample_video.stat().st_size
    wait_job(client, project["latest_job"]["id"], "succeeded")


def test_upload_rejects_unsupported_type(make_client):
    client = make_client([FakeIngestStage()])
    res = client.post("/api/projects/upload", files={"file": ("notes.txt", b"hi", "text/plain")})
    assert res.status_code == 415


def test_list_projects_newest_first(make_client):
    client = make_client([FakeIngestStage(), FakeTranscribeStage()])
    a = client.post("/api/projects", json={"url": "https://youtu.be/a"}).json()
    time.sleep(0.01)
    b = client.post("/api/projects", json={"url": "https://youtu.be/b"}).json()
    ids = [p["id"] for p in client.get("/api/projects").json()]
    assert ids[:2] == [b["id"], a["id"]]


def test_transcript_404_until_ready_and_unknown_project_404(make_client):
    client = make_client([FakeIngestStage(), FakeTranscribeStage(duration=2)])
    project = client.post("/api/projects", json={"url": "https://youtu.be/a"}).json()
    assert client.get(f"/api/projects/{project['id']}/transcript").status_code == 404
    assert client.get("/api/projects/doesnotexist").status_code == 404


def test_retry_after_failure_skips_finished_stages(make_client):
    transcribe = FakeTranscribeStage(fail_times=1)
    client = make_client([FakeIngestStage(), transcribe])
    project = client.post("/api/projects", json={"url": "https://youtu.be/a"}).json()
    failed = wait_job(client, project["latest_job"]["id"], "failed")
    assert failed["error"] == "Transient failure" and failed["error_hint"] == "Press Retry"

    retried = client.post(f"/api/projects/{project['id']}/retry")
    assert retried.status_code == 200
    new_job_id = retried.json()["latest_job"]["id"]
    assert new_job_id != failed["id"]
    wait_job(client, new_job_id, "succeeded")
    with client.websocket_connect(f"/api/jobs/{new_job_id}/events") as ws:
        events = collect_until_job_end(ws)
    assert ("ingest", "cached") in [(e["stage"], e["status"]) for e in events if e["type"] == "stage"]


def test_retry_rejected_while_running(make_client):
    client = make_client([FakeIngestStage(), FakeTranscribeStage(duration=2)])
    project = client.post("/api/projects", json={"url": "https://youtu.be/a"}).json()
    wait_job(client, project["latest_job"]["id"], "running")
    assert client.post(f"/api/projects/{project['id']}/retry").status_code == 409


def test_cancel_running_job(make_client):
    client = make_client([FakeIngestStage(), FakeTranscribeStage(duration=5)])
    project = client.post("/api/projects", json={"url": "https://youtu.be/a"}).json()
    job_id = project["latest_job"]["id"]
    wait_job(client, job_id, "running")
    time.sleep(0.1)
    assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 200
    wait_job(client, job_id, "cancelled")
    assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 409


def test_delete_project(make_client, settings):
    client = make_client([FakeIngestStage(), FakeTranscribeStage()])
    project = client.post("/api/projects", json={"url": "https://youtu.be/a"}).json()
    wait_job(client, project["latest_job"]["id"], "succeeded")
    assert client.delete(f"/api/projects/{project['id']}").status_code == 204
    assert client.get(f"/api/projects/{project['id']}").status_code == 404
    assert not (settings.workspace_dir / "projects" / project["id"]).exists()


def collect_until_job_end(ws):
    events = []
    while True:
        event = ws.receive_json()
        events.append(event)
        if event["type"] == "job" and event["status"] in ("succeeded", "failed", "cancelled"):
            return events


def test_websocket_replays_full_history(make_client):
    client = make_client([FakeIngestStage(), FakeTranscribeStage()])
    project = client.post("/api/projects", json={"url": "https://youtu.be/a"}).json()
    job_id = project["latest_job"]["id"]
    wait_job(client, job_id, "succeeded")
    with client.websocket_connect(f"/api/jobs/{job_id}/events") as ws:
        events = collect_until_job_end(ws)
    stage_events = [(e["stage"], e["status"]) for e in events if e["type"] == "stage"]
    assert stage_events == [("ingest", "running"), ("ingest", "done"), ("transcribe", "running"), ("transcribe", "done")]
    assert any(e["type"] == "partial" and e["data"]["text"] == "Hello world." for e in events)


def test_pipeline_stages_endpoint(make_client):
    client = make_client([FakeIngestStage(), FakeTranscribeStage()])
    assert client.get("/api/pipeline/stages").json() == [
        {"name": "ingest", "label": "Importing video", "weight": 1.0},
        {"name": "transcribe", "label": "Transcribing speech", "weight": 3.0},
    ]


def test_restart_marks_running_jobs_failed_and_retry_resumes(make_client, settings):
    engine = make_engine(settings.db_url)
    project = repo.create_project(engine, source_type="url", source_url="https://youtu.be/a")
    job = repo.create_job(engine, project.id)
    repo.update_job(engine, job.id, status=JobStatus.running)
    engine.dispose()

    client = make_client([FakeIngestStage(), FakeTranscribeStage()])
    interrupted = client.get(f"/api/jobs/{job.id}").json()
    assert interrupted["status"] == "failed"
    assert "Retry" in interrupted["error_hint"]
    new_job = client.post(f"/api/projects/{project.id}/retry").json()["latest_job"]
    wait_job(client, new_job["id"], "succeeded")


def test_concurrent_uploads_of_same_video_transcribe_once(make_client, sample_video):
    transcribe = FakeTranscribeStage(duration=0.3)
    client = make_client([IngestStage(downloader=None), transcribe])
    projects = []
    for name in ("a.mp4", "b.mp4"):
        with sample_video.open("rb") as f:
            projects.append(client.post("/api/projects/upload", files={"file": (name, f, "video/mp4")}).json())
    for p in projects:
        wait_job(client, p["latest_job"]["id"], "succeeded")
    video_ids = {client.get(f"/api/projects/{p['id']}").json()["video_id"] for p in projects}
    assert len(video_ids) == 1
    assert transcribe.runs == 1


def test_websocket_unsubscribes_after_client_disconnects(make_client):
    client = make_client([FakeIngestStage(), FakeTranscribeStage()])
    project = client.post("/api/projects", json={"url": "https://youtu.be/a"}).json()
    job_id = project["latest_job"]["id"]
    wait_job(client, job_id, "succeeded")
    bus = client.app.state.services.bus
    with client.websocket_connect(f"/api/jobs/{job_id}/events") as ws:
        collect_until_job_end(ws)
        assert len(bus._subscribers[job_id]) == 1
    deadline = time.monotonic() + 3
    while bus._subscribers[job_id] and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not bus._subscribers[job_id]


def test_delete_project_while_job_running_is_quiet(make_client, caplog):
    client = make_client([FakeIngestStage(), FakeTranscribeStage(duration=2)])
    project = client.post("/api/projects", json={"url": "https://youtu.be/a"}).json()
    wait_job(client, project["latest_job"]["id"], "running")
    time.sleep(0.1)
    assert client.delete(f"/api/projects/{project['id']}").status_code == 204
    time.sleep(0.5)  # let the worker notice the cancel and unwind
    other = client.post("/api/projects", json={"url": "https://youtu.be/b"}).json()
    wait_job(client, other["latest_job"]["id"], "succeeded", timeout=15)
    assert not [r for r in caplog.records if "Unhandled error" in r.getMessage() or r.exc_info]


def test_export_project_zip(make_client, settings):
    import io
    import zipfile
    from app.models import Clip
    from app.workspace import Workspace

    client = make_client([])
    engine = client.app.state.services.engine
    ws: Workspace = client.app.state.services.workspace

    project = client.post("/api/projects", json={"url": "https://youtu.be/a"}).json()
    p_id = project["id"]

    # Create dummy rendered clip
    clips_dir = ws.project_dir(p_id) / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    (clips_dir / "c1.mp4").write_bytes(b"dummy mp4 video")
    (clips_dir / "c1.jpg").write_bytes(b"dummy thumb")
    (clips_dir / "c1.ass").write_text("[Script Info]", encoding="utf-8")

    clip = repo.replace_clips(engine, p_id, [
        Clip(
            id="c1",
            project_id=p_id,
            rank=0,
            start_s=0.0,
            end_s=15.0,
            title="Export Clip",
            hook_text="Hook",
            hook_type="statement",
            why_viral="Viral",
            score=95,
            video_file="clips/c1.mp4",
            thumbnail_file="clips/c1.jpg",
        )
    ])[0]

    # Test GET export
    res = client.get(f"/api/projects/{p_id}/export")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/zip"
    assert "attachment;" in res.headers["content-disposition"]

    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        names = zf.namelist()
        assert any(n.endswith(".mp4") for n in names)
        assert any(n.endswith("thumbnail.jpg") for n in names)
        assert any(n.endswith("captions.ass") for n in names)

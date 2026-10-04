import time

from app import repo
from app.models import JobStatus, SourceType


def test_create_and_get_project(engine):
    p = repo.create_project(engine, source_type=SourceType.url, source_url="https://youtu.be/x")
    loaded = repo.get_project(engine, p.id)
    assert loaded is not None
    assert loaded.source_url == "https://youtu.be/x"
    assert loaded.video_id is None


def test_list_projects_newest_first(engine):
    first = repo.create_project(engine, source_type=SourceType.upload, original_filename="a.mp4")
    time.sleep(0.01)
    second = repo.create_project(engine, source_type=SourceType.upload, original_filename="b.mp4")
    assert [p.id for p in repo.list_projects(engine)] == [second.id, first.id]


def test_update_project_fields(engine):
    p = repo.create_project(engine, source_type=SourceType.upload)
    updated = repo.update_project(engine, p.id, video_id="abc", title="Talk", duration_s=12.5)
    assert (updated.video_id, updated.title, updated.duration_s) == ("abc", "Talk", 12.5)


def test_jobs_latest_and_update(engine):
    p = repo.create_project(engine, source_type=SourceType.upload)
    j1 = repo.create_job(engine, p.id)
    time.sleep(0.01)
    j2 = repo.create_job(engine, p.id)
    assert repo.latest_job(engine, p.id).id == j2.id
    before = repo.get_job(engine, j1.id).updated_at
    time.sleep(0.01)
    j1u = repo.update_job(engine, j1.id, status=JobStatus.running, stage="ingest", progress=0.25)
    assert j1u.status is JobStatus.running and j1u.stage == "ingest" and j1u.progress == 0.25
    assert j1u.updated_at > before


def test_delete_project_removes_jobs(engine):
    p = repo.create_project(engine, source_type=SourceType.upload)
    j = repo.create_job(engine, p.id)
    repo.delete_project(engine, p.id)
    assert repo.get_project(engine, p.id) is None
    assert repo.get_job(engine, j.id) is None


def test_recover_interrupted_jobs(engine):
    p = repo.create_project(engine, source_type=SourceType.upload)
    running = repo.create_job(engine, p.id)
    repo.update_job(engine, running.id, status=JobStatus.running)
    queued = repo.create_job(engine, p.id)
    done = repo.create_job(engine, p.id)
    repo.update_job(engine, done.id, status=JobStatus.succeeded)

    requeue = repo.recover_interrupted_jobs(engine)

    assert requeue == [queued.id]
    failed = repo.get_job(engine, running.id)
    assert failed.status is JobStatus.failed
    assert "interrupted" in failed.error.lower()
    assert "retry" in failed.error_hint.lower()
    assert repo.get_job(engine, done.id).status is JobStatus.succeeded

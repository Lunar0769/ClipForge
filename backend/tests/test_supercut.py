from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app import repo
from app.main import create_app
from app.models import Clip, Project, SourceType
from app.pipeline.supercut import build_master_supercut


def test_build_master_supercut_compilation(tmp_path, settings):
    app = create_app(settings)
    engine = app.state.services.engine
    proj = repo.create_project(engine, source_type=SourceType.upload, title="Test Compilation")
    p_id = proj.id

    clips_dir = settings.workspace_dir / "projects" / p_id / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    # Create dummy rendered files
    (clips_dir / "clip_a.mp4").write_bytes(b"dummy_video_a")
    (clips_dir / "clip_b.mp4").write_bytes(b"dummy_video_b")

    clip1 = Clip(
        id="clip_a",
        project_id=p_id,
        rank=0,
        start_s=5.0,
        end_s=25.0,
        title="Hook Intro",
        hook_text="Check this",
        hook_type="question",
        why_viral="High retention",
        score=92,
        video_file="clips/clip_a.mp4",
    )
    clip2 = Clip(
        id="clip_b",
        project_id=p_id,
        rank=1,
        start_s=30.0,
        end_s=50.0,
        title="Big Climax",
        hook_text="Boom",
        hook_type="statement",
        why_viral="Payoff",
        score=88,
        video_file="clips/clip_b.mp4",
    )
    repo.replace_clips(engine, p_id, [clip1, clip2])

    class MockWorkspace:
        def project_dir(self, pid: str) -> Path:
            return settings.workspace_dir / "projects" / pid
        @property
        def videos_dir(self) -> Path:
            return settings.workspace_dir / "videos"

    workspace = MockWorkspace()

    # Mock _run_cancellable so it produces the expected destination file
    def mock_run(cmd, cancel, cwd=None):
        out_file = Path(cmd[-1])
        out_file.write_bytes(b"rendered_supercut_mp4")

    with patch("app.pipeline.supercut._run_cancellable", side_effect=mock_run), \
         patch("app.pipeline.supercut.extract_clip_thumbnail"):
        supercut = build_master_supercut(
            engine=engine,
            project_id=p_id,
            workspace=workspace,
            settings=settings,
            max_duration_s=45.0,
            color_grade="cinematic",
            music_mood="suspense",
        )

    assert supercut is not None
    assert supercut.is_supercut is True
    assert supercut.rank == 0
    assert supercut.score == 99
    assert supercut.color_grade == "cinematic"
    assert supercut.music_mood == "suspense"
    assert "Super-Cut" in supercut.title

    # Verify other clips' ranks were shifted
    all_clips = repo.list_clips(engine, p_id)
    assert len(all_clips) == 3
    # First clip in ordered list should be the supercut
    assert all_clips[0].id == supercut.id
    assert all_clips[0].rank == 0
    assert all_clips[1].rank == 1
    assert all_clips[2].rank == 2


def test_supercut_endpoint(settings):
    app = create_app(settings)
    engine = app.state.services.engine
    proj = repo.create_project(engine, source_type=SourceType.upload, title="Endpoint Supercut")
    p_id = proj.id

    clips_dir = settings.workspace_dir / "projects" / p_id / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    (clips_dir / "c1.mp4").write_bytes(b"video1")

    repo.replace_clips(engine, p_id, [
        Clip(
            id="c1",
            project_id=p_id,
            rank=0,
            start_s=0.0,
            end_s=15.0,
            title="Clip 1",
            hook_text="Hook 1",
            hook_type="statement",
            why_viral="Viral",
            score=90,
            video_file="clips/c1.mp4",
        )
    ])

    def mock_run(cmd, cancel, cwd=None):
        Path(cmd[-1]).write_bytes(b"supercut_mp4")

    with patch("app.pipeline.supercut._run_cancellable", side_effect=mock_run), \
         patch("app.pipeline.supercut.extract_clip_thumbnail"), \
         TestClient(app) as client:
        res = client.post(
            f"/api/projects/{p_id}/supercut",
            json={"max_duration_s": 30.0, "color_grade": "dramatic", "music_mood": "suspense"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["is_supercut"] is True
        assert data["color_grade"] == "dramatic"
        assert data["score"] == 99

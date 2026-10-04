import subprocess
from pathlib import Path

import pytest

from app import repo
from app.config import Settings
from app.db import make_engine
from app.events import EventBus
from app.models import SourceType
from app.pipeline.context import PipelineContext
from app.workspace import Workspace


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    # Spaces and non-ASCII on purpose: the real repo lives in "Shorts Generator".
    return Settings(
        _env_file=None,
        workspace_dir=tmp_path / "work space ü",
        models_dir=tmp_path / "models",
    )


@pytest.fixture
def engine(settings):
    return make_engine(settings.db_url)


@pytest.fixture
def workspace(settings):
    return Workspace(settings.workspace_dir)


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def make_ctx(settings, workspace, engine, bus):
    def _make(project=None, **project_fields) -> PipelineContext:
        if project is None:
            project_fields.setdefault("source_type", SourceType.upload)
            project = repo.create_project(engine, **project_fields)
        job = repo.create_job(engine, project.id)
        return PipelineContext(
            project_id=project.id,
            job_id=job.id,
            settings=settings,
            workspace=workspace,
            engine=engine,
            bus=bus,
            video_id=project.video_id,
        )

    return _make


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True)


@pytest.fixture(scope="session")
def media_dir(tmp_path_factory) -> Path:
    directory = tmp_path_factory.mktemp("media") / "dir with spaces ü"
    directory.mkdir()
    return directory


@pytest.fixture(scope="session")
def sample_video(media_dir) -> Path:
    out = media_dir / "sample vidéo.mp4"
    _ffmpeg(
        "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=3",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out),
    )
    return out


@pytest.fixture(scope="session")
def silent_video(media_dir) -> Path:
    out = media_dir / "silent.mp4"
    _ffmpeg(
        "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=3",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", "3", str(out),
    )
    return out


@pytest.fixture(scope="session")
def no_audio_video(media_dir) -> Path:
    out = media_dir / "no audio.mp4"
    _ffmpeg(
        "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out),
    )
    return out

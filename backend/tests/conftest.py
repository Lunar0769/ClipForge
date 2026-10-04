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

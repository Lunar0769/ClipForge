from pathlib import Path

import pytest

from app.config import Settings
from app.db import make_engine
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

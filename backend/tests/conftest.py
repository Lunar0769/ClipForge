from pathlib import Path

import pytest

from app.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    # Spaces and non-ASCII on purpose: the real repo lives in "Shorts Generator".
    return Settings(
        _env_file=None,
        workspace_dir=tmp_path / "work space ü",
        models_dir=tmp_path / "models",
    )

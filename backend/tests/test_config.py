from pathlib import Path

from app.config import REPO_ROOT, Settings


def test_relative_paths_resolve_against_repo_root():
    s = Settings(
        _env_file=None, workspace_dir="./workspace", models_dir="models",
        ytdlp_cookies_file="secrets/cookies.txt",
    )
    assert s.workspace_dir == REPO_ROOT / "workspace"
    assert s.models_dir == REPO_ROOT / "models"
    assert s.ytdlp_cookies_file == REPO_ROOT / "secrets" / "cookies.txt"


def test_relative_paths_from_env_resolve_against_repo_root(monkeypatch):
    monkeypatch.setenv("CLIPFORGE_WORKSPACE_DIR", "./ws")
    assert Settings(_env_file=None).workspace_dir == REPO_ROOT / "ws"


def test_absolute_paths_and_defaults_are_kept(tmp_path):
    s = Settings(_env_file=None, workspace_dir=tmp_path / "w")
    assert s.workspace_dir == tmp_path / "w"
    assert s.models_dir == REPO_ROOT / "models"
    assert s.ytdlp_cookies_file is None
    assert isinstance(s.workspace_dir, Path)

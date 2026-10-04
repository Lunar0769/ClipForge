from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CLIPFORGE_", env_file=REPO_ROOT / ".env", extra="ignore"
    )

    workspace_dir: Path = REPO_ROOT / "workspace"
    models_dir: Path = REPO_ROOT / "models"
    database_url: str | None = None

    whisper_model: str = "large-v3-turbo"
    whisper_device: str = "auto"  # auto | cuda | cpu
    whisper_compute_type: str = "float16"

    max_download_height: int = 1080
    ytdlp_cookies_file: Path | None = None
    ytdlp_js_runtime: str | None = "node"

    job_concurrency: int = 2
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.workspace_dir / 'clipforge.db').as_posix()}"


@lru_cache
def get_settings() -> Settings:
    return Settings()

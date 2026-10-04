# ClipForge Phase 1 — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A working local app where you paste a YouTube URL or upload a video, watch an animated live pipeline download/import it and transcribe it on the GPU (with the transcript streaming in), and can cancel, retry and revisit projects — the foundation every later phase builds on.

**Architecture:** A Python 3.13 FastAPI backend owns an in-process asyncio job queue that runs checkpointed pipeline stages (`ingest`, `transcribe`) in worker threads, serialising GPU stages and stages touching the same video. Stage progress flows through an in-memory event bus to a WebSocket consumed by a React 19 + Vite frontend. Artifacts live on disk under `workspace/`, metadata in SQLite.

**Tech Stack:** Python 3.13, uv, FastAPI, SQLModel/SQLite, yt-dlp, faster-whisper (CTranslate2, CUDA 12 + cuDNN 9), FFmpeg 8; React 19, Vite 8, TypeScript 5.9, Tailwind v4, Motion, GSAP (+SplitText), Lenis, React Three Fiber, TanStack Query, Vitest, Testing Library.

**Spec:** `docs/superpowers/specs/2026-10-03-shorts-generator-design.md` (this plan implements delivery phase 1: §2 architecture skeleton, §3.1 Ingest, §3.2 Transcribe, §5 API subset, §6 Home + Processing screens, §7 error handling for these stages, §8 tests for these units).

## Global Constraints

- Python `>=3.13,<3.14`, dependencies managed with **uv** (`backend/pyproject.toml`, `backend/uv.lock`). Node 22+, npm. FFmpeg 8 full build (`ffmpeg`, `ffprobe`) on PATH.
- Primary platform is **Windows 11**; the repo path contains a space (`Shorts Generator`). Every subprocess call uses an argument list (never `shell=True`), every path is a `pathlib.Path`.
- Target GPU: RTX 3050 Laptop, **4 GB VRAM**. ASR model `large-v3-turbo`, `float16` → `int8_float16` → CPU `int8` fallback.
- WhisperX is **not** used. Legacy `mediapipe.solutions` is **not** used.
- Workspace layout (spec §2): `workspace/projects/<project_id>/` (per-project inputs) and `workspace/videos/<video_id>/{source.<ext>, audio.wav, meta.json, transcript.json}` (shared, content-addressed cache).
- `video_id` = SHA-256 over first 64 MB + file size + duration, truncated to 20 hex chars (spec §3.1).
- ASR: `word_timestamps=True`, `vad_filter=True`, auto language (spec §3.2).
- Each stage writes its artifact atomically (`*.tmp` + `os.replace`); a retry resumes from the first incomplete stage (spec §7).
- Settings use env prefix `CLIPFORGE_`, loaded from repo-root `.env` (gitignored). Secrets never logged.
- UI: dark-first, near-black `#07060d` canvas, violet `#8b5cf6` → indigo `#6366f1` → cyan `#22d3ee` accent, grain overlay; display font Clash Display, UI font Inter; light theme supported; `prefers-reduced-motion` respected globally (spec §6).
- Every git commit message ends with the trailer line `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>` (omitted from the commands below for brevity — always add it).
- Backend commands run from `backend/`; frontend commands from `frontend/`.

## Review Focus

1. **YouTube URL variants** (`youtu.be/…?t=30`, `/shorts/…`, `watch?v=…&list=…`, pasted without `https://`) — must all be accepted and download a single video, never a playlist; non-http(s) input (`javascript:`, `ftp:`) rejected with a helpful message. Tests: Task 8 (`validate_source_url`, `build_ytdlp_options`), Task 13 (`normalizeSourceUrl`).
2. **Paths with spaces and non-ASCII characters** (the repo itself lives in `Shorts Generator`; uploads like `vidéo ü.mp4`) — ffmpeg/ffprobe/yt-dlp must work. Tests: all media fixtures live in `dir with spaces ü/sample vidéo.mp4` and the workspace is `work space ü` (Tasks 1, 7, 8).
3. **Videos without usable speech** — no audio stream must fail ingest with a clear message; silent audio must produce an empty transcript plus a "No speech detected" notice, not a crash. Tests: Task 8 (no-audio), Task 9 (empty transcript).
4. **Server restart mid-job** — jobs left `running` must become `failed` with a "press Retry" hint, queued jobs resume, and Retry skips already-finished stages. Tests: Task 3 (`recover_interrupted_jobs`), Task 11 (restart + retry via API).
5. **Same video submitted twice / concurrently** — must share one cached video directory and transcribe only once. Tests: Task 6 (per-video lock), Task 8 (three concurrent ingests of one file), Task 11 (two concurrent uploads, transcribe runs once).

---

## File Map

```
.env.example                         CLIPFORGE_* settings template
scripts/setup.ps1                    one-shot setup (uv sync, npm install, model download, doctor)
scripts/dev.ps1                      starts API (new window) + UI
backend/
  pyproject.toml, uv.lock
  app/__init__.py                    __version__
  app/config.py                      Settings (pydantic-settings), get_settings()
  app/gpu.py                         CUDA DLL registration, GPU/NVENC detection
  app/db.py                          make_engine()
  app/models.py                      Project, Job tables + enums
  app/repo.py                        all DB reads/writes
  app/workspace.py                   Workspace, VideoPaths, atomic JSON writes
  app/events.py                      JobEvent, EventBus (thread-safe pub/sub + replay)
  app/media.py                       probe(), extract_audio(), compute_video_id()
  app/cli.py                         `python -m app.cli doctor | download-models`
  app/main.py                        create_app() factory, lifespan, routers
  app/api/deps.py                    Services container + dependency
  app/api/schemas.py                 response/request models
  app/api/system.py                  /api/health, /api/system
  app/api/projects.py                /api/projects…
  app/api/jobs.py                    /api/jobs…, /api/pipeline/stages, WS events
  app/jobs/queue.py                  JobQueue (asyncio workers, cancel, GPU lock)
  app/pipeline/errors.py             StageError, StageCancelled
  app/pipeline/context.py            PipelineContext
  app/pipeline/stage.py              Stage protocol
  app/pipeline/runner.py             run_pipeline(), VideoLocks
  app/pipeline/download.py           URL validation, yt-dlp downloader, error explanations
  app/pipeline/ingest.py             IngestStage, VideoMeta
  app/pipeline/transcript.py         Word/Segment/Sentence/Transcript, build_sentences()
  app/pipeline/transcribe.py         FasterWhisperTranscriber, TranscribeStage
  app/pipeline/registry.py           default_stages_factory()
  tests/…                            one test module per unit + fakes.py + conftest.py
frontend/
  package.json, index.html, vite.config.ts, tsconfig.json
  src/main.tsx, src/App.tsx, src/index.css, src/vite-env.d.ts
  src/test/setup.ts, src/test/utils.tsx
  src/lib/{types,api,url,format,theme,progress,useSmoothScroll,useNow}.ts
  src/components/{AppShell,Logo,Grain,PageTransition,MagneticButton,Skeleton,StatusChip,ShaderBackground,NotFound}.tsx
  src/features/home/{HomePage,HeroHeadline,HeroInput,DropZone,RecentProjects}.tsx
  src/features/processing/{ProcessingPage,PipelineConstellation,TranscriptStream,ErrorPanel}.tsx
  src/features/processing/{jobEvents,useJobEvents}.ts
```

---

### Task 1: Backend scaffold and health endpoint

**Files:**
- Create: `backend/pyproject.toml`, `backend/app/__init__.py`, `backend/app/config.py`, `backend/app/main.py`, `backend/app/api/__init__.py`, `backend/app/api/system.py`, `backend/tests/__init__.py`, `backend/tests/conftest.py`, `backend/tests/test_health.py`

**Interfaces:**
- Produces: `app.__version__: str`; `app.config.Settings` (fields below), `app.config.get_settings() -> Settings`, `app.config.REPO_ROOT: Path`; `app.main.create_app(settings: Settings | None = None) -> FastAPI` (extended in Task 11); pytest fixture `settings` (workspace path contains spaces + `ü`).

- [ ] **Step 1: Create `backend/pyproject.toml`**

```toml
[project]
name = "clipforge"
version = "0.1.0"
description = "ClipForge — turn long videos into viral shorts"
requires-python = ">=3.13,<3.14"
dependencies = [
    "fastapi>=0.142",
    "uvicorn[standard]>=0.54",
    "sqlmodel>=0.0.47",
    "pydantic-settings>=2.15",
    "python-multipart>=0.0.20",
    "yt-dlp[default]>=2026.8.19",
    "faster-whisper>=1.2.1",
    "nvidia-cublas-cu12>=12.4; sys_platform == 'win32' or sys_platform == 'linux'",
    "nvidia-cudnn-cu12>=9,<10; sys_platform == 'win32' or sys_platform == 'linux'",
]

[dependency-groups]
dev = ["pytest>=9.1", "pytest-asyncio>=1.4", "httpx>=0.28"]

[tool.uv]
package = false

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
markers = [
    "gpu: needs an NVIDIA GPU and the downloaded whisper model",
    "network: needs internet access",
]
addopts = "-m 'not gpu and not network'"
```

- [ ] **Step 2: Install dependencies**

Run (from `backend/`): `uv sync`
Expected: creates `.venv` and `uv.lock`, ends with `Installed N packages`.

- [ ] **Step 3: Write the failing test**

`backend/tests/__init__.py`: empty file.

`backend/tests/conftest.py`:
```python
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
```

`backend/tests/test_health.py`:
```python
from fastapi.testclient import TestClient

from app.main import create_app


def test_health_returns_ok_and_version(settings):
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0"}
```

- [ ] **Step 4: Run test to verify it fails**

Run: `uv run pytest tests/test_health.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app'`.

- [ ] **Step 5: Implement**

`backend/app/__init__.py`:
```python
__version__ = "0.1.0"
```

`backend/app/config.py`:
```python
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
```

`backend/app/api/__init__.py`: empty file.

`backend/app/api/system.py`:
```python
from fastapi import APIRouter

from app import __version__

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}
```

`backend/app/main.py`:
```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import system
from app.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="ClipForge API", version=__version__)
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(system.router, prefix="/api")
    return app
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest -v`
Expected: `1 passed`.

- [ ] **Step 7: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/app backend/tests
git commit -m "feat(backend): scaffold FastAPI app with settings and health endpoint"
```

---

### Task 2: GPU, CUDA DLL and NVENC diagnostics

**Files:**
- Create: `backend/app/gpu.py`, `backend/tests/test_gpu.py`
- Modify: `backend/app/api/system.py` (add `/system`)

**Interfaces:**
- Consumes: Task 1 `create_app`, `settings` fixture.
- Produces: `GpuInfo(name: str, memory_total_mb: int, driver: str)` dataclass; `parse_nvidia_smi(output: str) -> list[GpuInfo]`; `detect_gpus() -> list[GpuInfo]`; `ffmpeg_has_nvenc() -> bool`; `register_cuda_dlls() -> list[Path]` (must be called before importing `faster_whisper`/`ctranslate2`); `GET /api/system -> {"gpus": [...], "ffmpeg": bool, "nvenc": bool}`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_gpu.py`:
```python
import sys

from fastapi.testclient import TestClient

from app import gpu
from app.api import system
from app.gpu import GpuInfo, parse_nvidia_smi
from app.main import create_app


def test_parse_nvidia_smi_without_units():
    out = "NVIDIA GeForce RTX 3050 Laptop GPU, 4096, 610.62\n"
    assert parse_nvidia_smi(out) == [GpuInfo("NVIDIA GeForce RTX 3050 Laptop GPU", 4096, "610.62")]


def test_parse_nvidia_smi_with_units_and_multiple_gpus():
    out = "GPU A, 8192 MiB, 600.1\nGPU B, 4096 MiB, 600.1\n"
    assert [g.memory_total_mb for g in parse_nvidia_smi(out)] == [8192, 4096]


def test_parse_nvidia_smi_ignores_garbage():
    assert parse_nvidia_smi("No devices were found\n\n") == []


def test_register_cuda_dlls_is_noop_off_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert gpu.register_cuda_dlls() == []


def test_system_endpoint_reports_gpu_and_ffmpeg(settings, monkeypatch):
    monkeypatch.setattr(system, "detect_gpus", lambda: [GpuInfo("Test GPU", 4096, "1.0")])
    monkeypatch.setattr(system, "ffmpeg_has_nvenc", lambda: True)
    with TestClient(create_app(settings)) as client:
        body = client.get("/api/system").json()
    assert body["gpus"] == [{"name": "Test GPU", "memory_total_mb": 4096, "driver": "1.0"}]
    assert body["nvenc"] is True
    assert isinstance(body["ffmpeg"], bool)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_gpu.py -v`
Expected: FAIL — `ImportError: cannot import name 'gpu' from 'app'`.

- [ ] **Step 3: Implement**

`backend/app/gpu.py`:
```python
"""GPU discovery and Windows CUDA DLL wiring.

ctranslate2 (used by faster-whisper) needs cuBLAS and cuDNN DLLs. We install them
as pip wheels (nvidia-cublas-cu12, nvidia-cudnn-cu12); on Windows their `bin`
folders must be registered before ctranslate2 is imported.
"""

import importlib.util
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GpuInfo:
    name: str
    memory_total_mb: int
    driver: str


def register_cuda_dlls() -> list[Path]:
    if sys.platform != "win32":
        return []
    spec = importlib.util.find_spec("nvidia")
    if spec is None or not spec.submodule_search_locations:
        return []
    added: list[Path] = []
    for base in spec.submodule_search_locations:
        for bin_dir in sorted(Path(base).glob("*/bin")):
            os.add_dll_directory(str(bin_dir))
            os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"
            added.append(bin_dir)
    logger.debug("Registered CUDA DLL directories: %s", added)
    return added


def parse_nvidia_smi(output: str) -> list[GpuInfo]:
    gpus: list[GpuInfo] = []
    for line in output.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 3:
            continue
        name, memory, driver = parts
        try:
            memory_mb = int(memory.split()[0])
        except (ValueError, IndexError):
            continue
        gpus.append(GpuInfo(name, memory_mb, driver))
    return gpus


@lru_cache
def detect_gpus() -> list[GpuInfo]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    try:
        proc = subprocess.run(
            [exe, "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=True,
        )
    except (subprocess.SubprocessError, OSError):
        return []
    return parse_nvidia_smi(proc.stdout)


@lru_cache
def ffmpeg_has_nvenc() -> bool:
    exe = shutil.which("ffmpeg")
    if not exe:
        return False
    try:
        proc = subprocess.run(
            [exe, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=15
        )
    except (subprocess.SubprocessError, OSError):
        return False
    return "h264_nvenc" in proc.stdout
```

Replace `backend/app/api/system.py` with:
```python
import shutil
from dataclasses import asdict

from fastapi import APIRouter

from app import __version__
from app.gpu import detect_gpus, ffmpeg_has_nvenc

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.get("/system")
def system_info() -> dict:
    return {
        "gpus": [asdict(g) for g in detect_gpus()],
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "nvenc": ffmpeg_has_nvenc(),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -v`
Expected: all passed (6).

- [ ] **Step 5: Commit**

```bash
git add backend/app/gpu.py backend/app/api/system.py backend/tests/test_gpu.py
git commit -m "feat(backend): add GPU/NVENC detection and CUDA DLL registration"
```

---

### Task 3: Database models and repository

**Files:**
- Create: `backend/app/db.py`, `backend/app/models.py`, `backend/app/repo.py`, `backend/tests/test_repo.py`
- Modify: `backend/tests/conftest.py` (add `engine` fixture)

**Interfaces:**
- Produces:
  - `make_engine(url: str) -> sqlalchemy.Engine` (creates the SQLite parent dir and all tables).
  - `SourceType(StrEnum)`: `url`, `upload`. `JobStatus(StrEnum)`: `queued`, `running`, `succeeded`, `failed`, `cancelled`. `TERMINAL_STATUSES: frozenset[JobStatus]`.
  - `Project` table: `id: str`, `created_at: datetime`, `source_type: SourceType`, `source_url: str | None`, `original_filename: str | None`, `title: str | None`, `video_id: str | None`, `duration_s: float | None`.
  - `Job` table: `id: str`, `project_id: str`, `status: JobStatus`, `stage: str | None`, `progress: float`, `error: str | None`, `error_hint: str | None`, `created_at`, `updated_at`.
  - `repo`: `create_project(engine, *, source_type, source_url=None, original_filename=None, title=None) -> Project`, `get_project(engine, project_id) -> Project | None`, `list_projects(engine) -> list[Project]` (newest first), `update_project(engine, project_id, **fields) -> Project`, `delete_project(engine, project_id) -> None` (deletes its jobs too), `create_job(engine, project_id) -> Job`, `get_job(engine, job_id) -> Job | None`, `latest_job(engine, project_id) -> Job | None`, `update_job(engine, job_id, **fields) -> Job` (bumps `updated_at`), `recover_interrupted_jobs(engine) -> list[str]` (running → failed; returns ids of still-queued jobs).
  - Fixture `engine`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/conftest.py`:
```python
from app.db import make_engine


@pytest.fixture
def engine(settings):
    return make_engine(settings.db_url)
```

`backend/tests/test_repo.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_repo.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.db'`.

- [ ] **Step 3: Implement**

`backend/app/db.py`:
```python
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import SQLModel, create_engine

from app import models  # noqa: F401  (registers tables on SQLModel.metadata)


def make_engine(url: str) -> Engine:
    connect_args: dict = {}
    if url.startswith("sqlite:///"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        connect_args["check_same_thread"] = False
    engine = create_engine(url, connect_args=connect_args)
    SQLModel.metadata.create_all(engine)
    return engine
```

`backend/app/models.py`:
```python
from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid4().hex[:12]


class SourceType(StrEnum):
    url = "url"
    upload = "upload"


class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


TERMINAL_STATUSES = frozenset({JobStatus.succeeded, JobStatus.failed, JobStatus.cancelled})


class Project(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    created_at: datetime = Field(default_factory=utcnow)
    source_type: SourceType
    source_url: str | None = None
    original_filename: str | None = None
    title: str | None = None
    video_id: str | None = Field(default=None, index=True)
    duration_s: float | None = None


class Job(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    project_id: str = Field(foreign_key="project.id", index=True)
    status: JobStatus = JobStatus.queued
    stage: str | None = None
    progress: float = 0.0
    error: str | None = None
    error_hint: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
```

`backend/app/repo.py`:
```python
"""All database access. Every function opens its own short session so callers
(worker threads, the event loop, request handlers) never share a Session."""

from sqlalchemy import Engine
from sqlmodel import Session, col, delete, select

from app.models import Job, JobStatus, Project, SourceType, utcnow


def _session(engine: Engine) -> Session:
    return Session(engine, expire_on_commit=False)


def create_project(
    engine: Engine,
    *,
    source_type: SourceType,
    source_url: str | None = None,
    original_filename: str | None = None,
    title: str | None = None,
) -> Project:
    project = Project(
        source_type=source_type,
        source_url=source_url,
        original_filename=original_filename,
        title=title,
    )
    with _session(engine) as s:
        s.add(project)
        s.commit()
    return project


def get_project(engine: Engine, project_id: str) -> Project | None:
    with _session(engine) as s:
        return s.get(Project, project_id)


def list_projects(engine: Engine) -> list[Project]:
    with _session(engine) as s:
        return list(s.exec(select(Project).order_by(col(Project.created_at).desc())))


def update_project(engine: Engine, project_id: str, **fields) -> Project:
    with _session(engine) as s:
        project = s.get(Project, project_id)
        if project is None:
            raise KeyError(project_id)
        for key, value in fields.items():
            setattr(project, key, value)
        s.add(project)
        s.commit()
        return project


def delete_project(engine: Engine, project_id: str) -> None:
    with _session(engine) as s:
        s.exec(delete(Job).where(col(Job.project_id) == project_id))
        project = s.get(Project, project_id)
        if project is not None:
            s.delete(project)
        s.commit()


def create_job(engine: Engine, project_id: str) -> Job:
    job = Job(project_id=project_id)
    with _session(engine) as s:
        s.add(job)
        s.commit()
    return job


def get_job(engine: Engine, job_id: str) -> Job | None:
    with _session(engine) as s:
        return s.get(Job, job_id)


def latest_job(engine: Engine, project_id: str) -> Job | None:
    with _session(engine) as s:
        stmt = (
            select(Job)
            .where(col(Job.project_id) == project_id)
            .order_by(col(Job.created_at).desc())
            .limit(1)
        )
        return s.exec(stmt).first()


def update_job(engine: Engine, job_id: str, **fields) -> Job:
    with _session(engine) as s:
        job = s.get(Job, job_id)
        if job is None:
            raise KeyError(job_id)
        for key, value in fields.items():
            setattr(job, key, value)
        job.updated_at = utcnow()
        s.add(job)
        s.commit()
        return job


def recover_interrupted_jobs(engine: Engine) -> list[str]:
    """Called at startup: jobs that were mid-run can't continue (their worker died)."""
    with _session(engine) as s:
        for job in s.exec(select(Job).where(col(Job.status) == JobStatus.running)):
            job.status = JobStatus.failed
            job.error = "Interrupted because ClipForge was restarted."
            job.error_hint = "Press Retry to resume from the last completed step."
            job.updated_at = utcnow()
            s.add(job)
        s.commit()
        queued = s.exec(
            select(Job).where(col(Job.status) == JobStatus.queued).order_by(col(Job.created_at))
        )
        return [j.id for j in queued]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db.py backend/app/models.py backend/app/repo.py backend/tests
git commit -m "feat(backend): add SQLite models and repository with restart recovery"
```

---

### Task 4: Workspace layout and atomic artifacts

**Files:**
- Create: `backend/app/workspace.py`, `backend/tests/test_workspace.py`
- Modify: `backend/tests/conftest.py` (add `workspace` fixture)

**Interfaces:**
- Produces: `Workspace(root: Path)` with `.root`, `.projects_dir`, `.videos_dir`, `.project_dir(project_id) -> Path` (created), `.video(video_id) -> VideoPaths` (dir created), `.remove_project(project_id) -> None`; `VideoPaths` with `.dir`, `.audio` (`audio.wav`), `.meta` (`meta.json`), `.transcript` (`transcript.json`), `.find_source() -> Path | None` (first `source.*` that is not `.tmp`/`.part`); `atomic_write_json(path: Path, data: BaseModel | dict | list) -> None`; `read_json(path: Path) -> Any`. Fixture `workspace`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/conftest.py`:
```python
from app.workspace import Workspace


@pytest.fixture
def workspace(settings):
    return Workspace(settings.workspace_dir)
```

`backend/tests/test_workspace.py`:
```python
from pydantic import BaseModel

from app.workspace import atomic_write_json, read_json


class Thing(BaseModel):
    name: str
    score: float


def test_workspace_creates_dirs(workspace):
    assert workspace.projects_dir.is_dir()
    assert workspace.videos_dir.is_dir()
    assert workspace.project_dir("p1").is_dir()
    assert workspace.video("v1").dir.is_dir()


def test_video_paths(workspace):
    vp = workspace.video("v1")
    assert vp.audio.name == "audio.wav"
    assert vp.meta.name == "meta.json"
    assert vp.transcript.name == "transcript.json"


def test_find_source_ignores_partial_files(workspace):
    vp = workspace.video("v1")
    assert vp.find_source() is None
    (vp.dir / "source.mp4.tmp").write_bytes(b"x")
    (vp.dir / "source.mkv.part").write_bytes(b"x")
    assert vp.find_source() is None
    (vp.dir / "source.mkv").write_bytes(b"x")
    assert vp.find_source() == vp.dir / "source.mkv"


def test_atomic_write_json_model_and_dict(workspace):
    target = workspace.video("v1").meta
    atomic_write_json(target, Thing(name="vidéo ü", score=0.5))
    assert read_json(target) == {"name": "vidéo ü", "score": 0.5}
    atomic_write_json(target, {"a": [1, 2]})
    assert read_json(target) == {"a": [1, 2]}
    assert not list(target.parent.glob("*.tmp"))


def test_remove_project(workspace):
    d = workspace.project_dir("p1")
    (d / "upload.mp4").write_bytes(b"x")
    workspace.remove_project("p1")
    assert not d.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_workspace.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.workspace'`.

- [ ] **Step 3: Implement**

`backend/app/workspace.py`:
```python
import json
import os
import shutil
from pathlib import Path
from typing import Any

from pydantic import BaseModel

_PARTIAL_SUFFIXES = {".tmp", ".part", ".ytdl"}


class VideoPaths:
    """Content-addressed cache for one source video, shared by all projects using it."""

    def __init__(self, directory: Path) -> None:
        self.dir = directory

    @property
    def audio(self) -> Path:
        return self.dir / "audio.wav"

    @property
    def meta(self) -> Path:
        return self.dir / "meta.json"

    @property
    def transcript(self) -> Path:
        return self.dir / "transcript.json"

    def find_source(self) -> Path | None:
        for path in sorted(self.dir.glob("source.*")):
            if path.suffix.lower() not in _PARTIAL_SUFFIXES:
                return path
        return None


class Workspace:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.projects_dir = self.root / "projects"
        self.videos_dir = self.root / "videos"
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.videos_dir.mkdir(parents=True, exist_ok=True)

    def project_dir(self, project_id: str) -> Path:
        path = self.projects_dir / project_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def video(self, video_id: str) -> VideoPaths:
        path = self.videos_dir / video_id
        path.mkdir(parents=True, exist_ok=True)
        return VideoPaths(path)

    def remove_project(self, project_id: str) -> None:
        shutil.rmtree(self.projects_dir / project_id, ignore_errors=True)


def atomic_write_json(path: Path, data: BaseModel | dict | list) -> None:
    if isinstance(data, BaseModel):
        text = data.model_dump_json(indent=2)
    else:
        text = json.dumps(data, ensure_ascii=False, indent=2)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/workspace.py backend/tests
git commit -m "feat(backend): add workspace layout with atomic JSON artifacts"
```

---

### Task 5: Event bus

**Files:**
- Create: `backend/app/events.py`, `backend/tests/test_events.py`

**Interfaces:**
- Produces: `EventType = Literal["stage", "progress", "log", "partial", "job"]`; `JobEvent(BaseModel)`: `job_id: str`, `type: EventType`, `stage: str | None`, `status: str | None`, `progress: float | None`, `message: str | None`, `data: dict[str, Any] | None`, `ts: float`; `EventBus(history_limit: int = 1000)` with `bind(loop)`, `publish(event)` (safe from any thread), `subscribe(job_id) -> asyncio.Queue[JobEvent]` (pre-filled with history), `unsubscribe(job_id, queue)`, `history(job_id) -> list[JobEvent]`, `forget(job_id)`. Unbound bus delivers synchronously.

Event conventions used by all later tasks:
| `type` | fields | meaning |
|---|---|---|
| `stage` | `stage`, `status` ∈ `running/done/cached/failed/cancelled`, `progress`, `message?` | stage lifecycle |
| `progress` | `stage`, `progress` 0–1, `message?` | within-stage progress |
| `partial` | `stage`, `data.kind` = `segment` (`start`,`end`,`text`) or `language` (`language`) | streamed results |
| `log` | `stage?`, `message` | user-facing notice |
| `job` | `status` ∈ `running/succeeded/failed/cancelled`, `message?`, `data.hint?` | job lifecycle |

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_events.py`:
```python
import asyncio

from app.events import EventBus, JobEvent


def ev(job_id: str, message: str) -> JobEvent:
    return JobEvent(job_id=job_id, type="log", message=message)


async def test_subscriber_receives_published_events():
    bus = EventBus()
    bus.bind(asyncio.get_running_loop())
    queue = bus.subscribe("j1")
    bus.publish(ev("j1", "hello"))
    got = await asyncio.wait_for(queue.get(), 1)
    assert got.message == "hello"


async def test_late_subscriber_gets_history_replay_in_order():
    bus = EventBus()
    bus.bind(asyncio.get_running_loop())
    bus.publish(ev("j1", "a"))
    bus.publish(ev("j1", "b"))
    queue = bus.subscribe("j1")
    assert [(await queue.get()).message for _ in range(2)] == ["a", "b"]


async def test_publish_from_worker_thread_is_delivered():
    bus = EventBus()
    bus.bind(asyncio.get_running_loop())
    queue = bus.subscribe("j1")
    await asyncio.to_thread(bus.publish, ev("j1", "from thread"))
    got = await asyncio.wait_for(queue.get(), 1)
    assert got.message == "from thread"


async def test_events_are_isolated_per_job():
    bus = EventBus()
    bus.bind(asyncio.get_running_loop())
    q1 = bus.subscribe("j1")
    bus.publish(ev("j2", "other"))
    assert q1.empty()


def test_unbound_bus_records_history_synchronously():
    bus = EventBus()
    bus.publish(ev("j1", "x"))
    assert [e.message for e in bus.history("j1")] == ["x"]


def test_history_is_capped_and_forgettable():
    bus = EventBus(history_limit=3)
    for i in range(5):
        bus.publish(ev("j1", str(i)))
    assert [e.message for e in bus.history("j1")] == ["2", "3", "4"]
    bus.forget("j1")
    assert bus.history("j1") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_events.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.events'`.

- [ ] **Step 3: Implement**

`backend/app/events.py`:
```python
import asyncio
import time
from collections import defaultdict, deque
from typing import Any, Literal

from pydantic import BaseModel, Field

EventType = Literal["stage", "progress", "log", "partial", "job"]


class JobEvent(BaseModel):
    job_id: str
    type: EventType
    stage: str | None = None
    status: str | None = None
    progress: float | None = None
    message: str | None = None
    data: dict[str, Any] | None = None
    ts: float = Field(default_factory=time.time)


class EventBus:
    """In-memory pub/sub keyed by job id.

    Stages run in worker threads, so publish() hops onto the bound event loop.
    Each job keeps a bounded history that is replayed to new subscribers, so a
    browser that connects (or reconnects) mid-job sees the full picture.
    """

    def __init__(self, history_limit: int = 1000) -> None:
        self._history_limit = history_limit
        self._history: dict[str, deque[JobEvent]] = {}
        self._subscribers: dict[str, set[asyncio.Queue[JobEvent]]] = defaultdict(set)
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def publish(self, event: JobEvent) -> None:
        loop = self._loop
        if loop is None:
            self._deliver(event)
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            self._deliver(event)
            return
        try:
            loop.call_soon_threadsafe(self._deliver, event)
        except RuntimeError:  # loop closed during shutdown
            pass

    def _deliver(self, event: JobEvent) -> None:
        history = self._history.setdefault(event.job_id, deque(maxlen=self._history_limit))
        history.append(event)
        for queue in list(self._subscribers.get(event.job_id, ())):
            queue.put_nowait(event)

    def subscribe(self, job_id: str) -> asyncio.Queue[JobEvent]:
        queue: asyncio.Queue[JobEvent] = asyncio.Queue()
        for event in self._history.get(job_id, ()):
            queue.put_nowait(event)
        self._subscribers[job_id].add(queue)
        return queue

    def unsubscribe(self, job_id: str, queue: asyncio.Queue[JobEvent]) -> None:
        self._subscribers.get(job_id, set()).discard(queue)

    def history(self, job_id: str) -> list[JobEvent]:
        return list(self._history.get(job_id, ()))

    def forget(self, job_id: str) -> None:
        self._history.pop(job_id, None)
        self._subscribers.pop(job_id, None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/events.py backend/tests/test_events.py
git commit -m "feat(backend): add thread-safe job event bus with replay"
```

---

### Task 6: Pipeline context, stage protocol and runner

**Files:**
- Create: `backend/app/pipeline/__init__.py` (empty), `backend/app/pipeline/errors.py`, `backend/app/pipeline/context.py`, `backend/app/pipeline/stage.py`, `backend/app/pipeline/runner.py`, `backend/tests/fakes.py`, `backend/tests/test_runner.py`
- Modify: `backend/tests/conftest.py` (add `bus`, `make_ctx` fixtures)

**Interfaces:**
- Consumes: `Settings` (T1), `Engine`/`repo`/`SourceType` (T3), `Workspace`/`VideoPaths` (T4), `EventBus`/`JobEvent`/`EventType` (T5).
- Produces:
  - `StageError(message: str, hint: str | None = None)` with `.message`, `.hint`; `StageCancelled(Exception)`.
  - `PipelineContext` dataclass: `project_id`, `job_id`, `settings`, `workspace`, `engine`, `bus`, `video_id: str | None = None`, `cancel_event: threading.Event`; methods `video() -> VideoPaths`, `emit(type, **fields)`, `progress(stage, fraction, message=None)`, `check_cancelled()`.
  - `Stage` Protocol: attributes `name: str`, `label: str`, `weight: float`, `uses_gpu: bool`; methods `is_done(ctx) -> bool`, `run(ctx) -> None` (both synchronous; run in a worker thread).
  - `VideoLocks` with `.get(video_id) -> asyncio.Lock`.
  - `async run_pipeline(stages, ctx, *, gpu_lock: asyncio.Lock, video_locks: VideoLocks, on_progress: Callable[[str, float], None] | None = None) -> None`.
  - `tests/fakes.py`: `RecordingStage`.
  - Fixtures `bus`, `make_ctx(project=None, **project_fields) -> PipelineContext`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/conftest.py`:
```python
from app import repo
from app.events import EventBus
from app.models import SourceType
from app.pipeline.context import PipelineContext


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
```

`backend/tests/fakes.py`:
```python
import threading
import time

from app.pipeline.context import PipelineContext


class RecordingStage:
    """Configurable stage for runner/queue tests."""

    def __init__(
        self,
        name: str,
        *,
        uses_gpu: bool = False,
        weight: float = 1.0,
        done: bool = False,
        fail: Exception | None = None,
        duration: float = 0.0,
    ) -> None:
        self.name = name
        self.label = name.title()
        self.uses_gpu = uses_gpu
        self.weight = weight
        self.done = done
        self.fail = fail
        self.duration = duration
        self.runs = 0
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def is_done(self, ctx: PipelineContext) -> bool:
        return self.done

    def run(self, ctx: PipelineContext) -> None:
        with self._lock:
            self.runs += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            deadline = time.monotonic() + self.duration
            while time.monotonic() < deadline:
                ctx.check_cancelled()
                time.sleep(0.01)
            if self.fail is not None:
                raise self.fail
        finally:
            with self._lock:
                self.active -= 1
```

`backend/tests/test_runner.py`:
```python
import asyncio

import pytest

from app.pipeline.errors import StageCancelled, StageError
from app.pipeline.runner import VideoLocks, run_pipeline
from tests.fakes import RecordingStage


def statuses(bus, job_id):
    return [(e.stage, e.status) for e in bus.history(job_id) if e.type == "stage"]


async def run(stages, ctx, **kw):
    return await run_pipeline(
        stages, ctx, gpu_lock=kw.pop("gpu_lock", asyncio.Lock()),
        video_locks=kw.pop("video_locks", VideoLocks()), **kw,
    )


async def test_runs_stages_in_order_and_emits_lifecycle(make_ctx, bus):
    ctx = make_ctx()
    a, b = RecordingStage("a"), RecordingStage("b")
    await run([a, b], ctx)
    assert (a.runs, b.runs) == (1, 1)
    assert statuses(bus, ctx.job_id) == [("a", "running"), ("a", "done"), ("b", "running"), ("b", "done")]


async def test_skips_completed_stage(make_ctx, bus):
    ctx = make_ctx()
    cached = RecordingStage("a", done=True)
    await run([cached], ctx)
    assert cached.runs == 0
    assert statuses(bus, ctx.job_id) == [("a", "cached")]


async def test_stage_error_emits_failed_and_propagates(make_ctx, bus):
    ctx = make_ctx()
    boom = RecordingStage("a", fail=StageError("Bad video", hint="Try another"))
    after = RecordingStage("b")
    with pytest.raises(StageError):
        await run([boom, after], ctx)
    assert after.runs == 0
    failed = [e for e in bus.history(ctx.job_id) if e.status == "failed"][0]
    assert failed.message == "Bad video"


async def test_cancel_stops_before_next_stage(make_ctx):
    ctx = make_ctx()
    slow = RecordingStage("a", duration=5.0)
    after = RecordingStage("b")
    task = asyncio.create_task(run([slow, after], ctx))
    await asyncio.sleep(0.1)
    ctx.cancel_event.set()
    with pytest.raises(StageCancelled):
        await asyncio.wait_for(task, 2)
    assert after.runs == 0


async def test_gpu_stages_are_serialized_across_jobs(make_ctx):
    gpu_stage = RecordingStage("gpu", uses_gpu=True, duration=0.2)
    gpu_lock, locks = asyncio.Lock(), VideoLocks()
    await asyncio.gather(
        run([gpu_stage], make_ctx(), gpu_lock=gpu_lock, video_locks=locks),
        run([gpu_stage], make_ctx(), gpu_lock=gpu_lock, video_locks=locks),
    )
    assert gpu_stage.runs == 2
    assert gpu_stage.max_active == 1


async def test_same_video_stages_are_serialized(make_ctx):
    cpu_stage = RecordingStage("cpu", duration=0.2)
    c1, c2 = make_ctx(), make_ctx()
    c1.video_id = c2.video_id = "samevideo"
    locks = VideoLocks()
    await asyncio.gather(run([cpu_stage], c1, video_locks=locks), run([cpu_stage], c2, video_locks=locks))
    assert cpu_stage.max_active == 1


async def test_on_progress_reports_weighted_overall_progress(make_ctx):
    calls = []
    await run(
        [RecordingStage("a", weight=1), RecordingStage("b", weight=3)],
        make_ctx(),
        on_progress=lambda stage, overall: calls.append((stage, overall)),
    )
    assert calls == [("a", 0.0), ("a", 0.25), ("b", 0.25), ("b", 1.0)]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.pipeline'`.

- [ ] **Step 3: Implement**

`backend/app/pipeline/__init__.py`: empty file.

`backend/app/pipeline/errors.py`:
```python
class StageCancelled(Exception):
    """Raised inside a stage when the user cancels the job."""


class StageError(Exception):
    """An expected, user-explainable failure. `hint` tells the user what to do."""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
```

`backend/app/pipeline/context.py`:
```python
import threading
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Engine

from app.config import Settings
from app.events import EventBus, EventType, JobEvent
from app.pipeline.errors import StageCancelled
from app.workspace import VideoPaths, Workspace


@dataclass
class PipelineContext:
    project_id: str
    job_id: str
    settings: Settings
    workspace: Workspace
    engine: Engine
    bus: EventBus
    video_id: str | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)

    def video(self) -> VideoPaths:
        if self.video_id is None:
            raise RuntimeError("video_id is not set; the ingest stage must run first")
        return self.workspace.video(self.video_id)

    def emit(self, type: EventType, **fields: Any) -> None:
        self.bus.publish(JobEvent(job_id=self.job_id, type=type, **fields))

    def progress(self, stage: str, fraction: float, message: str | None = None) -> None:
        self.emit("progress", stage=stage, progress=max(0.0, min(1.0, fraction)), message=message)

    def check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise StageCancelled()
```

`backend/app/pipeline/stage.py`:
```python
from typing import Protocol

from app.pipeline.context import PipelineContext


class Stage(Protocol):
    name: str      # stable id used in events and the API, e.g. "transcribe"
    label: str     # human label shown in the UI, e.g. "Transcribing speech"
    weight: float  # relative share of total job time, for the overall progress bar
    uses_gpu: bool # GPU stages run one at a time across all jobs

    def is_done(self, ctx: PipelineContext) -> bool:
        """True if this stage's artifacts already exist (checkpoint/cache hit)."""
        ...

    def run(self, ctx: PipelineContext) -> None:
        """Do the work synchronously. Called in a worker thread."""
        ...
```

`backend/app/pipeline/runner.py`:
```python
import asyncio
import contextlib
from collections.abc import Callable, Sequence

from app.pipeline.context import PipelineContext
from app.pipeline.errors import StageCancelled, StageError
from app.pipeline.stage import Stage

ProgressCallback = Callable[[str, float], None]


class VideoLocks:
    """One asyncio.Lock per video_id so two jobs never build the same artifacts at once."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    def get(self, video_id: str) -> asyncio.Lock:
        return self._locks.setdefault(video_id, asyncio.Lock())


async def run_pipeline(
    stages: Sequence[Stage],
    ctx: PipelineContext,
    *,
    gpu_lock: asyncio.Lock,
    video_locks: VideoLocks,
    on_progress: ProgressCallback | None = None,
) -> None:
    total = sum(s.weight for s in stages) or 1.0
    completed = 0.0
    for stage in stages:
        ctx.check_cancelled()
        if on_progress:
            on_progress(stage.name, completed / total)
        video_lock = video_locks.get(ctx.video_id) if ctx.video_id else contextlib.nullcontext()
        gpu = gpu_lock if stage.uses_gpu else contextlib.nullcontext()
        try:
            async with video_lock, gpu:
                # Checked inside the locks: another job may have just produced the artifact.
                if await asyncio.to_thread(stage.is_done, ctx):
                    ctx.emit("stage", stage=stage.name, status="cached", progress=1.0)
                else:
                    ctx.emit("stage", stage=stage.name, status="running", progress=0.0)
                    await asyncio.to_thread(stage.run, ctx)
                    ctx.emit("stage", stage=stage.name, status="done", progress=1.0)
        except StageCancelled:
            ctx.emit("stage", stage=stage.name, status="cancelled")
            raise
        except Exception as exc:
            message = exc.message if isinstance(exc, StageError) else str(exc)
            ctx.emit("stage", stage=stage.name, status="failed", message=message)
            raise
        completed += stage.weight
        if on_progress:
            on_progress(stage.name, completed / total)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline backend/tests
git commit -m "feat(backend): add checkpointed pipeline runner with GPU and per-video locks"
```

---
### Task 7: Media utilities (ffprobe, audio extraction, video id)

**Files:**
- Create: `backend/app/media.py`, `backend/tests/test_media.py`
- Modify: `backend/tests/conftest.py` (add session-scoped media fixtures)

**Interfaces:**
- Produces: `MediaError(Exception)`; `MediaInfo(duration_s: float, has_video: bool, has_audio: bool, width: int | None, height: int | None, fps: float | None)`; `probe(path: Path) -> MediaInfo`; `extract_audio(src: Path, dst: Path, sample_rate: int = 16000) -> None` (mono PCM WAV, atomic); `compute_video_id(path: Path, duration_s: float) -> str` (20 hex chars). Fixtures `media_dir`, `sample_video` (3 s, 640×360, 30 fps, 440 Hz tone), `silent_video`, `no_audio_video` — all inside `dir with spaces ü/`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/conftest.py`:
```python
import subprocess


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
```

`backend/tests/test_media.py`:
```python
import shutil

import pytest

from app.media import MediaError, compute_video_id, extract_audio, probe


def test_probe_video_with_audio(sample_video):
    info = probe(sample_video)
    assert info.has_video and info.has_audio
    assert (info.width, info.height) == (640, 360)
    assert info.fps == pytest.approx(30, abs=0.1)
    assert info.duration_s == pytest.approx(3, abs=0.2)


def test_probe_video_without_audio(no_audio_video):
    info = probe(no_audio_video)
    assert info.has_video and not info.has_audio


def test_probe_rejects_non_media(tmp_path):
    bogus = tmp_path / "notes.mp4"
    bogus.write_text("definitely not a video")
    with pytest.raises(MediaError):
        probe(bogus)


def test_extract_audio_writes_mono_wav_atomically(sample_video, tmp_path):
    dst = tmp_path / "out dir ü" / "audio.wav"
    dst.parent.mkdir()
    extract_audio(sample_video, dst)
    info = probe(dst)
    assert info.has_audio and not info.has_video
    assert info.duration_s == pytest.approx(3, abs=0.2)
    assert not list(dst.parent.glob("*.tmp"))


def test_video_id_is_content_based(sample_video, silent_video, tmp_path):
    duration = probe(sample_video).duration_s
    copy = tmp_path / "copy.mp4"
    shutil.copy(sample_video, copy)
    vid = compute_video_id(sample_video, duration)
    assert len(vid) == 20
    assert compute_video_id(copy, duration) == vid
    assert compute_video_id(silent_video, probe(silent_video).duration_s) != vid
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_media.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.media'`.

- [ ] **Step 3: Implement**

`backend/app/media.py`:
```python
import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

HEAD_BYTES = 64 * 1024 * 1024


class MediaError(Exception):
    pass


@dataclass(frozen=True)
class MediaInfo:
    duration_s: float
    has_video: bool
    has_audio: bool
    width: int | None = None
    height: int | None = None
    fps: float | None = None


def _tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise MediaError(f"{name} was not found on PATH. Install FFmpeg 8 (full build) and restart.")
    return path


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-5:])
        raise MediaError(f"{Path(args[0]).stem} failed: {tail}")
    return proc


def _parse_fps(rate: str | None) -> float | None:
    if not rate or "/" not in rate:
        return None
    num, den = rate.split("/", 1)
    try:
        n, d = float(num), float(den)
    except ValueError:
        return None
    return round(n / d, 3) if d else None


def probe(path: Path) -> MediaInfo:
    proc = _run([
        _tool("ffprobe"), "-v", "error", "-print_format", "json",
        "-show_streams", "-show_format", str(path),
    ])
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams", [])
    video = next(
        (s for s in streams
         if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")),
        None,
    )
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = float(data.get("format", {}).get("duration") or (video or {}).get("duration") or 0.0)
    if video is None and audio is None:
        raise MediaError("No audio or video streams found")
    return MediaInfo(
        duration_s=duration,
        has_video=video is not None,
        has_audio=audio is not None,
        width=video.get("width") if video else None,
        height=video.get("height") if video else None,
        fps=_parse_fps(video.get("avg_frame_rate")) if video else None,
    )


def extract_audio(src: Path, dst: Path, sample_rate: int = 16000) -> None:
    tmp = dst.with_name(dst.name + ".tmp")
    _run([
        _tool("ffmpeg"), "-y", "-v", "error", "-i", str(src),
        "-vn", "-ac", "1", "-ar", str(sample_rate), "-c:a", "pcm_s16le", "-f", "wav", str(tmp),
    ])
    os.replace(tmp, dst)


def compute_video_id(path: Path, duration_s: float) -> str:
    digest = hashlib.sha256()
    remaining = HEAD_BYTES
    with path.open("rb") as f:
        while remaining > 0 and (chunk := f.read(min(1024 * 1024, remaining))):
            digest.update(chunk)
            remaining -= len(chunk)
    digest.update(str(path.stat().st_size).encode())
    digest.update(f"{duration_s:.3f}".encode())
    return digest.hexdigest()[:20]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/media.py backend/tests
git commit -m "feat(backend): add ffprobe/ffmpeg media utilities and content-based video ids"
```

---

### Task 8: Ingest stage (YouTube download + uploads)

**Files:**
- Create: `backend/app/pipeline/download.py`, `backend/app/pipeline/ingest.py`, `backend/tests/test_download.py`, `backend/tests/test_ingest.py`

**Interfaces:**
- Consumes: `PipelineContext` (T6), `StageError`/`StageCancelled` (T6), `repo`/`SourceType` (T3), `probe`/`extract_audio`/`compute_video_id`/`MediaError` (T7), `atomic_write_json` (T4).
- Produces:
  - `download.py`: `validate_source_url(url: str) -> str` (raises `ValueError`); `DownloadResult(path, title=None, channel=None, description=None, webpage_url=None)`; `ProgressFn = Callable[[float, str | None], None]`; `Downloader` Protocol `__call__(url, dest_dir, on_progress, cancel) -> DownloadResult`; `build_ytdlp_options(dest_dir, *, max_height, cookies_file, js_runtime) -> dict`; `explain_download_error(raw: str) -> tuple[str, str]`; `YtDlpDownloader(*, max_height, cookies_file, js_runtime)`.
  - `ingest.py`: `UPLOAD_EXTENSIONS: frozenset[str]`; `VideoMeta` model; `IngestStage(downloader)` with `name="ingest"`, `label="Importing video"`, `weight=1.0`, `uses_gpu=False`. Uploads are expected at `workspace.project_dir(id)/upload<ext>`. On success: `ctx.video_id` set, project `video_id/title/duration_s` updated, `videos/<id>/source.<ext>`, `audio.wav`, `meta.json` exist.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_download.py`:
```python
import threading
from pathlib import Path

import pytest

from app.pipeline.download import (
    YtDlpDownloader,
    build_ytdlp_options,
    explain_download_error,
    validate_source_url,
)


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ?t=30",
    "https://www.youtube.com/shorts/abc123",
    "https://www.youtube.com/watch?v=abc&list=PL123&index=2",
    "http://vimeo.com/12345",
    "  https://youtu.be/x  ",
])
def test_validate_accepts_http_video_links(url):
    assert validate_source_url(url) == url.strip()


@pytest.mark.parametrize("url", ["javascript:alert(1)", "ftp://example.com/a.mp4", "notaurl", "https://", ""])
def test_validate_rejects_non_http_links(url):
    with pytest.raises(ValueError, match="http"):
        validate_source_url(url)


def test_options_never_download_playlists_and_cap_resolution(tmp_path):
    opts = build_ytdlp_options(tmp_path, max_height=1080, cookies_file=None, js_runtime="node")
    assert opts["noplaylist"] is True
    assert "height<=1080" in opts["format"]
    assert opts["merge_output_format"] == "mp4"
    assert opts["outtmpl"] == str(tmp_path / "download.%(ext)s")
    assert opts["js_runtimes"] == {"node": {}}
    assert "cookiefile" not in opts


def test_options_include_cookies_when_configured(tmp_path):
    cookies = tmp_path / "cookies.txt"
    opts = build_ytdlp_options(tmp_path, max_height=720, cookies_file=cookies, js_runtime=None)
    assert opts["cookiefile"] == str(cookies)
    assert "js_runtimes" not in opts


@pytest.mark.parametrize(("raw", "expected_hint_word"), [
    ("ERROR: [youtube] x: Sign in to confirm your age", "cookies"),
    ("ERROR: [youtube] x: Private video. Sign in if you've been granted access", "upload"),
    ("ERROR: [youtube] x: Video unavailable", "upload"),
    ("ERROR: Unsupported URL: https://example.com", "upload"),
    ("ERROR: unable to download video data: HTTP Error 403: Forbidden", "yt-dlp"),
    ("ERROR: something new and weird", "yt-dlp"),
])
def test_explain_download_error(raw, expected_hint_word):
    message, hint = explain_download_error(raw)
    assert message
    assert expected_hint_word in hint.lower()


@pytest.mark.network
def test_real_youtube_download(tmp_path):
    downloader = YtDlpDownloader(max_height=360, cookies_file=None, js_runtime="node")
    result = downloader(
        "https://www.youtube.com/watch?v=jNQXAC9IVRw", tmp_path, lambda f, m: None, threading.Event()
    )
    assert result.path.exists() and result.path.stat().st_size > 0
    assert result.title
```

`backend/tests/test_ingest.py`:
```python
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app import repo
from app.models import SourceType
from app.pipeline.download import DownloadResult
from app.pipeline.errors import StageError
from app.pipeline.ingest import IngestStage
from app.workspace import read_json


class FakeDownloader:
    def __init__(self, source: Path, title: str = "My Talk") -> None:
        self.source, self.title, self.calls = source, title, 0

    def __call__(self, url, dest_dir, on_progress, cancel):
        self.calls += 1
        dest_dir.mkdir(parents=True, exist_ok=True)
        target = dest_dir / "download.mp4"
        shutil.copy(self.source, target)
        on_progress(0.5, "Downloading… 50%")
        on_progress(1.0, "Downloading… 100%")
        return DownloadResult(path=target, title=self.title, channel="Chan", webpage_url=url)


def make_upload(make_ctx, workspace, src: Path, name: str = "sample vidéo.mp4"):
    ctx = make_ctx(source_type=SourceType.upload, original_filename=name)
    shutil.copy(src, workspace.project_dir(ctx.project_id) / f"upload{Path(name).suffix}")
    return ctx


def test_ingest_upload(make_ctx, workspace, engine, sample_video):
    ctx = make_upload(make_ctx, workspace, sample_video)
    stage = IngestStage(downloader=FakeDownloader(sample_video))
    assert not stage.is_done(ctx)

    stage.run(ctx)

    assert ctx.video_id
    vp = ctx.video()
    assert vp.find_source().name == "source.mp4"
    assert vp.audio.exists()
    meta = read_json(vp.meta)
    assert meta["video_id"] == ctx.video_id and meta["width"] == 640
    project = repo.get_project(engine, ctx.project_id)
    assert project.video_id == ctx.video_id
    assert project.title == "sample vidéo"
    assert project.duration_s == pytest.approx(3, abs=0.2)
    assert not list(workspace.project_dir(ctx.project_id).glob("upload.*"))
    assert stage.is_done(ctx)


def test_ingest_url_uses_downloader_title_and_reports_progress(make_ctx, engine, bus, sample_video):
    ctx = make_ctx(source_type=SourceType.url, source_url="https://youtu.be/x")
    downloader = FakeDownloader(sample_video, title="My Talk")
    IngestStage(downloader=downloader).run(ctx)
    assert downloader.calls == 1
    assert repo.get_project(engine, ctx.project_id).title == "My Talk"
    assert read_json(ctx.video().meta)["channel"] == "Chan"
    progress = [e.progress for e in bus.history(ctx.job_id) if e.type == "progress"]
    assert progress and max(progress) <= 1.0


def test_same_file_twice_shares_one_video_dir(make_ctx, workspace, sample_video):
    stage = IngestStage(downloader=FakeDownloader(sample_video))
    a = make_upload(make_ctx, workspace, sample_video)
    b = make_upload(make_ctx, workspace, sample_video)
    stage.run(a)
    stage.run(b)
    assert a.video_id == b.video_id
    assert len(list(workspace.videos_dir.iterdir())) == 1


def test_concurrent_ingest_of_same_file(make_ctx, workspace, sample_video):
    stage = IngestStage(downloader=FakeDownloader(sample_video))
    contexts = [make_upload(make_ctx, workspace, sample_video) for _ in range(3)]
    with ThreadPoolExecutor(3) as pool:
        list(pool.map(stage.run, contexts))
    assert len({c.video_id for c in contexts}) == 1
    assert contexts[0].video().audio.exists()
    assert len(list(workspace.videos_dir.iterdir())) == 1


def test_ingest_rejects_video_without_audio(make_ctx, workspace, no_audio_video):
    ctx = make_upload(make_ctx, workspace, no_audio_video, name="no audio.mp4")
    with pytest.raises(StageError, match="no audio track"):
        IngestStage(downloader=FakeDownloader(no_audio_video)).run(ctx)


def test_ingest_rejects_non_video(make_ctx, workspace, tmp_path):
    bogus = tmp_path / "fake.mp4"
    bogus.write_text("hello")
    ctx = make_upload(make_ctx, workspace, bogus, name="fake.mp4")
    with pytest.raises(StageError, match="couldn't be read"):
        IngestStage(downloader=FakeDownloader(bogus)).run(ctx)


def test_ingest_missing_upload(make_ctx, sample_video):
    ctx = make_ctx(source_type=SourceType.upload, original_filename="gone.mp4")
    with pytest.raises(StageError, match="missing"):
        IngestStage(downloader=FakeDownloader(sample_video)).run(ctx)


def test_ingest_resumes_when_audio_extraction_was_interrupted(make_ctx, workspace, sample_video):
    ctx = make_upload(make_ctx, workspace, sample_video)
    stage = IngestStage(downloader=FakeDownloader(sample_video))
    stage.run(ctx)
    ctx.video().audio.unlink()  # simulate crash after the source was imported
    assert not stage.is_done(ctx)
    stage.run(ctx)  # must not need the (already moved) upload again
    assert ctx.video().audio.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_download.py tests/test_ingest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.pipeline.download'`.

- [ ] **Step 3: Implement `download.py`**

`backend/app/pipeline/download.py`:
```python
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from app.pipeline.errors import StageCancelled, StageError

ProgressFn = Callable[[float, str | None], None]

_URL_HELP = "Enter a full http(s) link to a video, e.g. https://www.youtube.com/watch?v=…"


def validate_source_url(url: str) -> str:
    candidate = url.strip()
    parsed = urlparse(candidate)
    host = parsed.hostname or ""
    if parsed.scheme.lower() not in {"http", "https"} or "." not in host:
        raise ValueError(_URL_HELP)
    return candidate


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    title: str | None = None
    channel: str | None = None
    description: str | None = None
    webpage_url: str | None = None


class Downloader(Protocol):
    def __call__(
        self, url: str, dest_dir: Path, on_progress: ProgressFn, cancel: threading.Event
    ) -> DownloadResult: ...


def build_ytdlp_options(
    dest_dir: Path, *, max_height: int, cookies_file: Path | None, js_runtime: str | None
) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "format": f"bv*[height<={max_height}]+ba/b[height<={max_height}]/bv*+ba/b",
        "merge_output_format": "mp4",
        "outtmpl": str(dest_dir / "download.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "retries": 3,
        "fragment_retries": 3,
        "overwrites": True,
    }
    if cookies_file:
        opts["cookiefile"] = str(cookies_file)
    if js_runtime:
        # YouTube extraction needs a JS runtime; we use the Node that ships with the frontend toolchain.
        opts["js_runtimes"] = {js_runtime: {}}
    return opts


_UPDATE_HINT = "Update yt-dlp: in backend/ run `uv lock --upgrade-package yt-dlp` then `uv sync`, and press Retry."

_ERROR_RULES: list[tuple[tuple[str, ...], str, str]] = [
    (("sign in to confirm", "confirm your age", "age-restricted", "members-only", "join this channel"),
     "This video needs a signed-in YouTube session.",
     "Export your browser's YouTube cookies to a cookies.txt file and set CLIPFORGE_YTDLP_COOKIES_FILE in .env."),
    (("private video",),
     "This video is private.",
     "Use a public or unlisted video, or upload the file directly."),
    (("video unavailable", "is not available", "has been removed", "account associated with this video has been terminated"),
     "This video is unavailable.",
     "Check the link in your browser, or upload the file directly."),
    (("unsupported url",),
     "This site or link isn't supported.",
     "Paste a link to a video page (YouTube, Vimeo, X, …) or upload the file directly."),
    (("http error 403", "forbidden", "nsig", "signature", "po token", "js runtime", "javascript runtime"),
     "YouTube blocked the download.",
     _UPDATE_HINT),
]


def explain_download_error(raw: str) -> tuple[str, str]:
    low = raw.lower()
    for needles, message, hint in _ERROR_RULES:
        if any(n in low for n in needles):
            return message, hint
    return "The download failed.", f"Check your internet connection and the link. {_UPDATE_HINT}"


class YtDlpDownloader:
    def __init__(self, *, max_height: int, cookies_file: Path | None, js_runtime: str | None) -> None:
        self._max_height = max_height
        self._cookies_file = cookies_file
        self._js_runtime = js_runtime

    def __call__(
        self, url: str, dest_dir: Path, on_progress: ProgressFn, cancel: threading.Event
    ) -> DownloadResult:
        import yt_dlp

        dest_dir.mkdir(parents=True, exist_ok=True)

        def hook(d: dict[str, Any]) -> None:
            if cancel.is_set():
                raise yt_dlp.utils.DownloadCancelled("Cancelled by user")
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                if total:
                    pct = (d.get("_percent_str") or "").strip()
                    on_progress(d.get("downloaded_bytes", 0) / total, f"Downloading… {pct}".strip())

        opts = build_ytdlp_options(
            dest_dir, max_height=self._max_height,
            cookies_file=self._cookies_file, js_runtime=self._js_runtime,
        )
        opts["progress_hooks"] = [hook]
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadCancelled as exc:
            raise StageCancelled() from exc
        except yt_dlp.utils.DownloadError as exc:
            if cancel.is_set():
                raise StageCancelled() from exc
            message, hint = explain_download_error(str(exc))
            raise StageError(message, hint) from exc

        return DownloadResult(
            path=_downloaded_path(info, dest_dir),
            title=info.get("title"),
            channel=info.get("channel") or info.get("uploader"),
            description=info.get("description"),
            webpage_url=info.get("webpage_url"),
        )


def _downloaded_path(info: dict[str, Any], dest_dir: Path) -> Path:
    for item in info.get("requested_downloads") or []:
        filepath = item.get("filepath")
        if filepath and Path(filepath).exists():
            return Path(filepath)
    candidates = [
        p for p in dest_dir.glob("download.*") if p.suffix.lower() not in {".part", ".ytdl", ".tmp"}
    ]
    if not candidates:
        raise StageError("The download finished but no video file was found.", "Retry, or upload the file directly.")
    return max(candidates, key=lambda p: p.stat().st_size)
```

> If `test_real_youtube_download` (run with `uv run pytest -m network`) reports that `js_runtimes` is an unknown option, check the current option name in the installed yt-dlp (`uv run python -c "import yt_dlp, inspect; print([l for l in inspect.getsource(yt_dlp.YoutubeDL).splitlines() if 'js_runtime' in l][:5])"`) and update `build_ytdlp_options` plus its test to match.

- [ ] **Step 4: Implement `ingest.py`**

`backend/app/pipeline/ingest.py`:
```python
import shutil
import threading
from pathlib import Path

from pydantic import BaseModel

from app import repo
from app.media import MediaError, compute_video_id, extract_audio, probe
from app.models import Project, SourceType
from app.pipeline.context import PipelineContext
from app.pipeline.download import Downloader, DownloadResult
from app.pipeline.errors import StageError
from app.workspace import atomic_write_json

UPLOAD_EXTENSIONS = frozenset({".mp4", ".mkv", ".mov", ".webm", ".m4v", ".avi"})


class VideoMeta(BaseModel):
    video_id: str
    source_file: str
    title: str | None = None
    channel: str | None = None
    description: str | None = None
    webpage_url: str | None = None
    duration_s: float
    width: int | None = None
    height: int | None = None
    fps: float | None = None


class IngestStage:
    name = "ingest"
    label = "Importing video"
    weight = 1.0
    uses_gpu = False

    def __init__(self, downloader: Downloader) -> None:
        self._downloader = downloader
        # Two jobs can import the same file at once (video_id is only known after hashing),
        # so placing the source and extracting audio is guarded per video_id.
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _video_lock(self, video_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(video_id, threading.Lock())

    def is_done(self, ctx: PipelineContext) -> bool:
        if ctx.video_id is None:
            return False
        vp = ctx.video()
        return vp.find_source() is not None and vp.audio.exists() and vp.meta.exists()

    def run(self, ctx: PipelineContext) -> None:
        project = repo.get_project(ctx.engine, ctx.project_id)
        if project is None:
            raise StageError("This project no longer exists.")
        already_imported = (
            ctx.video_id is not None
            and ctx.video().find_source() is not None
            and ctx.video().meta.exists()
        )
        if not already_imported:
            self._import_source(ctx, project)
        with self._video_lock(ctx.video_id):
            vp = ctx.video()
            if not vp.audio.exists():
                ctx.progress(self.name, 0.9, "Extracting audio…")
                try:
                    extract_audio(vp.find_source(), vp.audio)
                except MediaError as exc:
                    raise StageError("Couldn't extract the audio track.", "Try re-exporting the video as MP4.") from exc

    def _import_source(self, ctx: PipelineContext, project: Project) -> None:
        result = self._acquire(ctx, project)
        ctx.check_cancelled()
        ctx.progress(self.name, 0.8, "Inspecting video…")
        try:
            info = probe(result.path)
        except MediaError as exc:
            raise StageError(
                "This file couldn't be read as a video.",
                "Make sure it's a normal video file (MP4, MKV, MOV, WebM).",
            ) from exc
        if not info.has_video:
            raise StageError("This file has no video track.", "Upload a video file, not audio only.")
        if not info.has_audio:
            raise StageError(
                "This video has no audio track.",
                "ClipForge finds moments from speech, so the video needs sound.",
            )

        video_id = compute_video_id(result.path, info.duration_s)
        title = result.title or (Path(project.original_filename).stem if project.original_filename else None)
        with self._video_lock(video_id):
            vp = ctx.workspace.video(video_id)
            source = vp.find_source()
            if source is None:
                source = vp.dir / f"source{result.path.suffix.lower()}"
                shutil.move(result.path, source)
            else:
                result.path.unlink(missing_ok=True)
            if not vp.meta.exists():
                atomic_write_json(vp.meta, VideoMeta(
                    video_id=video_id, source_file=source.name, title=title,
                    channel=result.channel, description=result.description, webpage_url=result.webpage_url,
                    duration_s=info.duration_s, width=info.width, height=info.height, fps=info.fps,
                ))
        repo.update_project(ctx.engine, project.id, video_id=video_id, title=title, duration_s=info.duration_s)
        ctx.video_id = video_id

    def _acquire(self, ctx: PipelineContext, project: Project) -> DownloadResult:
        project_dir = ctx.workspace.project_dir(project.id)
        if project.source_type == SourceType.url:
            ctx.progress(self.name, 0.0, "Starting download…")
            return self._downloader(
                project.source_url,
                project_dir / "download",
                lambda fraction, message: ctx.progress(self.name, fraction * 0.8, message),
                ctx.cancel_event,
            )
        uploads = [p for p in project_dir.glob("upload.*") if p.suffix.lower() in UPLOAD_EXTENSIONS]
        if not uploads:
            raise StageError("The uploaded file is missing.", "Upload the video again.")
        return DownloadResult(path=uploads[0])
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest -v`
Expected: all passed (network test deselected).

- [ ] **Step 6: Commit**

```bash
git add backend/app/pipeline/download.py backend/app/pipeline/ingest.py backend/tests
git commit -m "feat(backend): add ingest stage with yt-dlp download, uploads and friendly errors"
```

---

### Task 9: Transcription stage (faster-whisper)

**Files:**
- Create: `backend/app/pipeline/transcript.py`, `backend/app/pipeline/transcribe.py`, `backend/tests/test_transcript.py`, `backend/tests/test_transcribe.py`, `backend/tests/test_transcribe_gpu.py`

**Interfaces:**
- Consumes: `PipelineContext` (T6), `StageError`/`StageCancelled` (T6), `atomic_write_json` (T4).
- Produces:
  - `transcript.py`: `Word(text, start, end, prob=1.0)` (text keeps Whisper's leading space), `Segment(id, start, end, text, words)`, `Sentence(id, start, end, text, word_start, word_end)` (word indices into `Transcript.words`, end exclusive), `Transcript(language, language_prob=0.0, duration_s, segments, words, sentences)`; `join_words(words) -> str`; `build_sentences(words, *, max_gap_s=1.2, max_words=60) -> list[Sentence]`.
  - `transcribe.py`: `SegmentCallback = Callable[[Segment, float], None]`; `Transcriber` Protocol `transcribe(audio, on_segment, cancel) -> Transcript`; `FasterWhisperTranscriber(*, model_name, device, compute_type, download_root, model_factory=None, cuda_available=None)` with `.attempts() -> list[tuple[str, str]]` and `.active: tuple[str, str] | None`; `TranscribeStage(transcriber)` with `name="transcribe"`, `label="Transcribing speech"`, `weight=3.0`, `uses_gpu=True`; writes `videos/<id>/transcript.json`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_transcript.py`:
```python
from app.pipeline.transcript import Word, build_sentences


def w(text, start, end):
    return Word(text=text, start=start, end=end)


def test_splits_on_sentence_punctuation():
    words = [w(" Hello", 0, 0.4), w(" world.", 0.4, 0.8), w(" How", 1.0, 1.2), w(" are", 1.2, 1.3), w(" you?", 1.3, 1.6)]
    sentences = build_sentences(words)
    assert [s.text for s in sentences] == ["Hello world.", "How are you?"]
    assert [(s.word_start, s.word_end) for s in sentences] == [(0, 2), (2, 5)]
    assert (sentences[1].start, sentences[1].end) == (1.0, 1.6)


def test_splits_on_long_pause_without_punctuation():
    words = [w(" so", 0, 0.3), w(" yeah", 0.3, 0.6), w(" anyway", 2.5, 2.9)]
    assert [s.text for s in build_sentences(words)] == ["so yeah", "anyway"]


def test_caps_sentence_length():
    words = [w(f" w{i}", i * 0.1, i * 0.1 + 0.05) for i in range(130)]
    sentences = build_sentences(words, max_words=60)
    assert [s.word_end - s.word_start for s in sentences] == [60, 60, 10]


def test_closing_quote_after_period_ends_sentence():
    words = [w(' "Stop."', 0, 0.5), w(" Then", 0.6, 0.8)]
    assert [s.text for s in build_sentences(words)] == ['"Stop."', "Then"]


def test_non_latin_scripts():
    hindi = [w(" नमस्ते।", 0, 0.5), w(" दुनिया", 0.6, 1.0)]
    assert [s.text for s in build_sentences(hindi)] == ["नमस्ते।", "दुनिया"]
    chinese = [w("你好", 0, 0.3), w("。", 0.3, 0.35), w("世界", 0.5, 0.8)]
    assert [s.text for s in build_sentences(chinese)] == ["你好。", "世界"]


def test_empty_words():
    assert build_sentences([]) == []
```

`backend/tests/test_transcribe.py`:
```python
import threading
from types import SimpleNamespace

import pytest

from app.pipeline.errors import StageCancelled, StageError
from app.pipeline.transcribe import FasterWhisperTranscriber, TranscribeStage
from app.pipeline.transcript import Segment, Transcript, Word
from app.workspace import read_json


def fake_segments():
    words1 = [SimpleNamespace(word=" Hello", start=0.0, end=0.4, probability=0.9),
              SimpleNamespace(word=" world.", start=0.4, end=0.9, probability=0.95)]
    words2 = [SimpleNamespace(word=" Bye.", start=1.0, end=1.5, probability=0.99)]
    return [SimpleNamespace(start=0.0, end=0.9, text=" Hello world.", words=words1),
            SimpleNamespace(start=1.0, end=1.5, text=" Bye.", words=words2)]


class FakeModel:
    def __init__(self, fail_with: Exception | None = None):
        self.fail_with = fail_with

    def transcribe(self, audio, **kwargs):
        assert kwargs["word_timestamps"] is True and kwargs["vad_filter"] is True
        if self.fail_with:
            raise self.fail_with
        info = SimpleNamespace(language="en", language_probability=0.98, duration=2.0)
        return iter(fake_segments()), info


def make_transcriber(models: dict, cuda=True):
    created = []

    def factory(name, device, compute_type, download_root):
        created.append((device, compute_type))
        outcome = models[(device, compute_type)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    t = FasterWhisperTranscriber(
        model_name="large-v3-turbo", device="auto", compute_type="float16",
        download_root="models", model_factory=factory, cuda_available=lambda: cuda,
    )
    return t, created


def test_attempt_order_with_and_without_cuda():
    with_gpu, _ = make_transcriber({}, cuda=True)
    assert with_gpu.attempts() == [("cuda", "float16"), ("cuda", "int8_float16"), ("cpu", "int8")]
    cpu_only, _ = make_transcriber({}, cuda=False)
    assert cpu_only.attempts() == [("cpu", "int8")]


def test_transcribe_builds_words_sentences_and_streams_segments(tmp_path):
    t, _ = make_transcriber({("cuda", "float16"): FakeModel()})
    seen = []
    result = t.transcribe(tmp_path / "a.wav", lambda seg, frac: seen.append((seg.text, frac)), threading.Event())
    assert result.language == "en"
    assert [w.text for w in result.words] == [" Hello", " world.", " Bye."]
    assert [s.text for s in result.sentences] == ["Hello world.", "Bye."]
    assert seen == [("Hello world.", 0.45), ("Bye.", 0.75)]
    assert t.active == ("cuda", "float16")


def test_falls_back_when_model_fails_to_load(tmp_path):
    t, created = make_transcriber({
        ("cuda", "float16"): RuntimeError("Library cublas64_12.dll is not found"),
        ("cuda", "int8_float16"): RuntimeError("still broken"),
        ("cpu", "int8"): FakeModel(),
    })
    t.transcribe(tmp_path / "a.wav", lambda *_: None, threading.Event())
    assert created == [("cuda", "float16"), ("cuda", "int8_float16"), ("cpu", "int8")]
    assert t.active == ("cpu", "int8")


def test_falls_back_on_out_of_memory_during_inference(tmp_path):
    t, _ = make_transcriber({
        ("cuda", "float16"): FakeModel(fail_with=RuntimeError("CUDA failed with error out of memory")),
        ("cuda", "int8_float16"): FakeModel(),
    })
    result = t.transcribe(tmp_path / "a.wav", lambda *_: None, threading.Event())
    assert t.active == ("cuda", "int8_float16")
    assert len(result.segments) == 2


def test_all_attempts_failing_raises_stage_error(tmp_path):
    t, _ = make_transcriber({("cpu", "int8"): RuntimeError("nope")}, cuda=False)
    with pytest.raises(StageError, match="speech recognition model"):
        t.transcribe(tmp_path / "a.wav", lambda *_: None, threading.Event())


def test_cancel_during_transcription(tmp_path):
    t, _ = make_transcriber({("cuda", "float16"): FakeModel()})
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(StageCancelled):
        t.transcribe(tmp_path / "a.wav", lambda *_: None, cancel)


class StubTranscriber:
    def __init__(self, transcript: Transcript):
        self.transcript = transcript

    def transcribe(self, audio, on_segment, cancel):
        for seg in self.transcript.segments:
            on_segment(seg, seg.end / self.transcript.duration_s)
        return self.transcript


def test_stage_writes_transcript_and_streams_partials(make_ctx, bus):
    ctx = make_ctx()
    ctx.video_id = "vid1"
    word = Word(text=" Hi.", start=0, end=0.5)
    transcript = Transcript(language="en", duration_s=1.0,
                            segments=[Segment(id=0, start=0, end=0.5, text="Hi.", words=[word])],
                            words=[word])
    stage = TranscribeStage(StubTranscriber(transcript))
    assert not stage.is_done(ctx)
    stage.run(ctx)
    assert stage.is_done(ctx)
    assert read_json(ctx.video().transcript)["language"] == "en"
    partials = [e.data for e in bus.history(ctx.job_id) if e.type == "partial"]
    assert {"kind": "segment", "start": 0.0, "end": 0.5, "text": "Hi."} in partials
    assert {"kind": "language", "language": "en"} in partials


def test_stage_handles_video_without_speech(make_ctx, bus):
    ctx = make_ctx()
    ctx.video_id = "silent"
    TranscribeStage(StubTranscriber(Transcript(language="en", duration_s=3.0))).run(ctx)
    assert read_json(ctx.video().transcript)["words"] == []
    logs = [e.message for e in bus.history(ctx.job_id) if e.type == "log"]
    assert any("No speech" in m for m in logs)
```

`backend/tests/test_transcribe_gpu.py`:
```python
import threading

import pytest

from app.gpu import register_cuda_dlls
from app.media import extract_audio
from app.pipeline.transcribe import FasterWhisperTranscriber


@pytest.mark.gpu
def test_real_model_runs_on_gpu(sample_video, tmp_path, settings):
    """Run with: uv run pytest -m gpu  (needs `python -m app.cli download-models` first)."""
    from app.config import REPO_ROOT

    register_cuda_dlls()
    audio = tmp_path / "audio.wav"
    extract_audio(sample_video, audio)
    t = FasterWhisperTranscriber(
        model_name=settings.whisper_model, device="auto", compute_type="float16",
        download_root=REPO_ROOT / "models" / "whisper",
    )
    result = t.transcribe(audio, lambda *_: None, threading.Event())
    assert result.duration_s == pytest.approx(3, abs=0.3)
    assert t.active[0] == "cuda", f"expected GPU, got {t.active}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_transcript.py tests/test_transcribe.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.pipeline.transcript'`.

- [ ] **Step 3: Implement `transcript.py`**

`backend/app/pipeline/transcript.py`:
```python
from collections.abc import Sequence

from pydantic import BaseModel, Field

SENTENCE_END = (".", "?", "!", "…", "。", "？", "！", "।", "؟")
_TRAILING_CLOSERS = "\"'”’)]»"


class Word(BaseModel):
    text: str  # as emitted by Whisper; Latin scripts carry a leading space
    start: float
    end: float
    prob: float = 1.0


class Segment(BaseModel):
    id: int
    start: float
    end: float
    text: str
    words: list[Word] = Field(default_factory=list)


class Sentence(BaseModel):
    id: int
    start: float
    end: float
    text: str
    word_start: int  # index into Transcript.words
    word_end: int    # exclusive


class Transcript(BaseModel):
    language: str
    language_prob: float = 0.0
    duration_s: float
    segments: list[Segment] = Field(default_factory=list)
    words: list[Word] = Field(default_factory=list)
    sentences: list[Sentence] = Field(default_factory=list)


def join_words(words: Sequence[Word]) -> str:
    return "".join(w.text for w in words).strip()


def build_sentences(words: Sequence[Word], *, max_gap_s: float = 1.2, max_words: int = 60) -> list[Sentence]:
    sentences: list[Sentence] = []
    start = 0

    def close(end: int) -> None:
        nonlocal start
        chunk = words[start:end]
        if chunk:
            sentences.append(Sentence(
                id=len(sentences), start=chunk[0].start, end=chunk[-1].end,
                text=join_words(chunk), word_start=start, word_end=end,
            ))
        start = end

    for i, word in enumerate(words):
        if i > start and word.start - words[i - 1].end > max_gap_s:
            close(i)
        token = word.text.strip().rstrip(_TRAILING_CLOSERS)
        if token.endswith(SENTENCE_END) or (i + 1 - start) >= max_words:
            close(i + 1)
    close(len(words))
    return sentences
```

- [ ] **Step 4: Implement `transcribe.py`**

`backend/app/pipeline/transcribe.py`:
```python
import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from app.pipeline.context import PipelineContext
from app.pipeline.errors import StageCancelled, StageError
from app.pipeline.transcript import Segment, Transcript, Word, build_sentences
from app.workspace import atomic_write_json

logger = logging.getLogger(__name__)

SegmentCallback = Callable[[Segment, float], None]
ModelFactory = Callable[[str, str, str, str], Any]


class Transcriber(Protocol):
    def transcribe(self, audio: Path, on_segment: SegmentCallback, cancel: threading.Event) -> Transcript: ...


def _default_cuda_available() -> bool:
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:  # missing DLLs, no driver, …
        return False


def _default_model_factory(name: str, device: str, compute_type: str, download_root: str) -> Any:
    from faster_whisper import WhisperModel

    return WhisperModel(name, device=device, compute_type=compute_type, download_root=download_root)


def _is_oom(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "out of memory" in text or "cuda_error_out_of_memory" in text


class FasterWhisperTranscriber:
    """faster-whisper with automatic precision/device fallback (4 GB GPUs can OOM)."""

    def __init__(
        self,
        *,
        model_name: str,
        device: str,
        compute_type: str,
        download_root: Path | str,
        model_factory: ModelFactory | None = None,
        cuda_available: Callable[[], bool] | None = None,
    ) -> None:
        self._model_name = model_name
        self._device = device
        self._compute_type = compute_type
        self._download_root = str(download_root)
        self._factory = model_factory or _default_model_factory
        self._cuda_available = cuda_available or _default_cuda_available
        self._attempts: list[tuple[str, str]] | None = None
        self._index = 0
        self._model: Any = None
        self._lock = threading.Lock()
        self.active: tuple[str, str] | None = None

    def attempts(self) -> list[tuple[str, str]]:
        if self._attempts is None:
            order: list[tuple[str, str]] = []
            if self._device in ("auto", "cuda") and self._cuda_available():
                order += [("cuda", self._compute_type), ("cuda", "int8_float16")]
            order.append(("cpu", "int8"))
            self._attempts = list(dict.fromkeys(order))
        return self._attempts

    def _load(self) -> Any:
        last_error: Exception | None = None
        attempts = self.attempts()
        while self._index < len(attempts):
            device, compute_type = attempts[self._index]
            try:
                self._model = self._factory(self._model_name, device, compute_type, self._download_root)
                self.active = (device, compute_type)
                logger.info("Loaded whisper %s on %s/%s", self._model_name, device, compute_type)
                return self._model
            except (RuntimeError, ValueError, OSError) as exc:
                logger.warning("Whisper load failed on %s/%s: %s", device, compute_type, exc)
                last_error = exc
                self._index += 1
        raise StageError(
            "Couldn't load the speech recognition model.",
            f"Run `uv run python -m app.cli doctor` in backend/ to check your GPU setup. Last error: {last_error}",
        )

    def transcribe(self, audio: Path, on_segment: SegmentCallback, cancel: threading.Event) -> Transcript:
        with self._lock:
            while True:
                model = self._model or self._load()
                try:
                    return self._run(model, audio, on_segment, cancel)
                except RuntimeError as exc:
                    if not _is_oom(exc) or self._index + 1 >= len(self.attempts()):
                        raise
                    logger.warning("Out of GPU memory on %s; falling back", self.active)
                    self._model = None
                    self._index += 1

    def _run(self, model: Any, audio: Path, on_segment: SegmentCallback, cancel: threading.Event) -> Transcript:
        if cancel.is_set():
            raise StageCancelled()
        segments_iter, info = model.transcribe(
            str(audio), word_timestamps=True, vad_filter=True,
            beam_size=5, condition_on_previous_text=False,
        )
        segments: list[Segment] = []
        for raw in segments_iter:
            if cancel.is_set():
                raise StageCancelled()
            words = [Word(text=w.word, start=w.start, end=w.end, prob=w.probability) for w in (raw.words or [])]
            segment = Segment(id=len(segments), start=raw.start, end=raw.end, text=raw.text.strip(), words=words)
            segments.append(segment)
            fraction = min(raw.end / info.duration, 1.0) if info.duration else 0.0
            on_segment(segment, fraction)
        all_words = [w for s in segments for w in s.words]
        return Transcript(
            language=info.language, language_prob=info.language_probability, duration_s=info.duration,
            segments=segments, words=all_words, sentences=build_sentences(all_words),
        )


class TranscribeStage:
    name = "transcribe"
    label = "Transcribing speech"
    weight = 3.0
    uses_gpu = True

    def __init__(self, transcriber: Transcriber) -> None:
        self._transcriber = transcriber

    def is_done(self, ctx: PipelineContext) -> bool:
        return ctx.video_id is not None and ctx.video().transcript.exists()

    def run(self, ctx: PipelineContext) -> None:
        vp = ctx.video()

        def on_segment(segment: Segment, fraction: float) -> None:
            ctx.progress(self.name, fraction)
            ctx.emit("partial", stage=self.name, data={
                "kind": "segment", "start": segment.start, "end": segment.end, "text": segment.text,
            })

        transcript = self._transcriber.transcribe(vp.audio, on_segment, ctx.cancel_event)
        ctx.emit("partial", stage=self.name, data={"kind": "language", "language": transcript.language})
        if not transcript.words:
            ctx.emit("log", stage=self.name, message="No speech was detected in this video.")
        atomic_write_json(vp.transcript, transcript)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest -v`
Expected: all passed (gpu/network deselected).

- [ ] **Step 6: Commit**

```bash
git add backend/app/pipeline/transcript.py backend/app/pipeline/transcribe.py backend/tests
git commit -m "feat(backend): add faster-whisper transcription with sentence building and OOM fallback"
```

---

### Task 10: Job queue

**Files:**
- Create: `backend/app/jobs/__init__.py` (empty), `backend/app/jobs/queue.py`, `backend/tests/test_queue.py`

**Interfaces:**
- Consumes: `repo`, `JobStatus` (T3), `Workspace` (T4), `EventBus`, `JobEvent` (T5), `PipelineContext`, `Stage`, `run_pipeline`, `VideoLocks`, `StageError`, `StageCancelled` (T6).
- Produces: `StagesFactory = Callable[[], list[Stage]]`; `JobQueue(*, engine, workspace, settings, bus, stages_factory, concurrency=2)` with `async start()`, `async stop()`, `submit(job_id)`, `cancel(job_id) -> bool`, `.bus`. On finish it updates the job row (`status`, `progress`, `stage`, `error`, `error_hint`) and publishes a `job` event (`status`, `message`, `data={"hint": …}`).

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_queue.py`:
```python
import asyncio
import time

import pytest

from app import repo
from app.events import EventBus
from app.jobs.queue import JobQueue
from app.models import JobStatus, SourceType
from app.pipeline.errors import StageError
from tests.fakes import RecordingStage


@pytest.fixture
async def make_queue(settings, workspace, engine):
    queues: list[JobQueue] = []

    async def _make(stages, concurrency=2):
        q = JobQueue(engine=engine, workspace=workspace, settings=settings, bus=EventBus(),
                     stages_factory=lambda: stages, concurrency=concurrency)
        await q.start()
        queues.append(q)
        return q

    yield _make
    for q in queues:
        await q.stop()


def new_job(engine):
    project = repo.create_project(engine, source_type=SourceType.upload)
    return repo.create_job(engine, project.id)


async def wait_status(engine, job_id, *statuses, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = repo.get_job(engine, job_id)
        if job.status in statuses:
            return job
        await asyncio.sleep(0.02)
    raise AssertionError(f"job {job_id} stuck in {repo.get_job(engine, job_id).status}")


async def test_successful_job(make_queue, engine):
    q = await make_queue([RecordingStage("a"), RecordingStage("b")])
    job = new_job(engine)
    q.submit(job.id)
    done = await wait_status(engine, job.id, JobStatus.succeeded)
    assert done.progress == 1.0
    events = q.bus.history(job.id)
    assert events[0].type == "job" and events[0].status == "running"
    assert events[-1].type == "job" and events[-1].status == "succeeded"


async def test_stage_error_marks_failed_with_hint(make_queue, engine):
    q = await make_queue([RecordingStage("a", fail=StageError("Bad video", hint="Use another"))])
    job = new_job(engine)
    q.submit(job.id)
    failed = await wait_status(engine, job.id, JobStatus.failed)
    assert (failed.error, failed.error_hint, failed.stage) == ("Bad video", "Use another", "a")
    last = q.bus.history(job.id)[-1]
    assert last.status == "failed" and last.data == {"hint": "Use another"}


async def test_unexpected_error_marks_failed(make_queue, engine):
    q = await make_queue([RecordingStage("a", fail=ValueError("kaboom"))])
    job = new_job(engine)
    q.submit(job.id)
    failed = await wait_status(engine, job.id, JobStatus.failed)
    assert failed.error == "ValueError: kaboom"


async def test_cancel_running_job(make_queue, engine):
    q = await make_queue([RecordingStage("slow", duration=5)])
    job = new_job(engine)
    q.submit(job.id)
    await wait_status(engine, job.id, JobStatus.running)
    await asyncio.sleep(0.05)
    assert q.cancel(job.id) is True
    await wait_status(engine, job.id, JobStatus.cancelled, timeout=2)


async def test_cancel_queued_job_never_runs(make_queue, engine):
    slow = RecordingStage("slow", duration=0.5)
    q = await make_queue([slow], concurrency=1)
    first, second = new_job(engine), new_job(engine)
    q.submit(first.id)
    q.submit(second.id)
    await wait_status(engine, first.id, JobStatus.running)
    assert q.cancel(second.id) is True
    await wait_status(engine, first.id, JobStatus.succeeded)
    await asyncio.sleep(0.1)
    assert repo.get_job(engine, second.id).status is JobStatus.cancelled
    assert slow.runs == 1


async def test_cancel_unknown_or_finished_job_returns_false(make_queue, engine):
    q = await make_queue([RecordingStage("a")])
    job = new_job(engine)
    q.submit(job.id)
    await wait_status(engine, job.id, JobStatus.succeeded)
    assert q.cancel(job.id) is False
    assert q.cancel("nope") is False


async def test_gpu_stages_never_overlap(make_queue, engine):
    gpu = RecordingStage("gpu", uses_gpu=True, duration=0.2)
    q = await make_queue([gpu], concurrency=2)
    jobs = [new_job(engine), new_job(engine)]
    for j in jobs:
        q.submit(j.id)
    for j in jobs:
        await wait_status(engine, j.id, JobStatus.succeeded)
    assert gpu.runs == 2 and gpu.max_active == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_queue.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.jobs'`.

- [ ] **Step 3: Implement**

`backend/app/jobs/__init__.py`: empty file.

`backend/app/jobs/queue.py`:
```python
import asyncio
import logging
import threading
from collections.abc import Callable

from sqlalchemy import Engine

from app import repo
from app.config import Settings
from app.events import EventBus, JobEvent
from app.models import JobStatus
from app.pipeline.context import PipelineContext
from app.pipeline.errors import StageCancelled, StageError
from app.pipeline.runner import VideoLocks, run_pipeline
from app.pipeline.stage import Stage
from app.workspace import Workspace

logger = logging.getLogger(__name__)

StagesFactory = Callable[[], list[Stage]]


class JobQueue:
    """In-process job queue. `concurrency` jobs run at once; GPU stages share one lock."""

    def __init__(
        self,
        *,
        engine: Engine,
        workspace: Workspace,
        settings: Settings,
        bus: EventBus,
        stages_factory: StagesFactory,
        concurrency: int = 2,
    ) -> None:
        self._engine = engine
        self._workspace = workspace
        self._settings = settings
        self.bus = bus
        self._stages_factory = stages_factory
        self._concurrency = concurrency
        self._queue: asyncio.Queue[str] | None = None
        self._workers: list[asyncio.Task] = []
        self._cancels: dict[str, threading.Event] = {}
        self._gpu_lock: asyncio.Lock | None = None
        self._video_locks = VideoLocks()

    async def start(self) -> None:
        self.bus.bind(asyncio.get_running_loop())
        self._queue = asyncio.Queue()
        self._gpu_lock = asyncio.Lock()
        self._workers = [asyncio.create_task(self._worker()) for _ in range(self._concurrency)]

    async def stop(self) -> None:
        for event in self._cancels.values():
            event.set()
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers = []

    def submit(self, job_id: str) -> None:
        assert self._queue is not None, "JobQueue.start() was not awaited"
        self._queue.put_nowait(job_id)

    def cancel(self, job_id: str) -> bool:
        event = self._cancels.get(job_id)
        if event is not None:
            event.set()
            return True
        job = repo.get_job(self._engine, job_id)
        if job is not None and job.status is JobStatus.queued:
            repo.update_job(self._engine, job_id, status=JobStatus.cancelled)
            self._publish_job(job_id, JobStatus.cancelled, message="Cancelled before it started.")
            return True
        return False

    def _publish_job(self, job_id: str, status: JobStatus, message: str | None = None, hint: str | None = None) -> None:
        self.bus.publish(JobEvent(
            job_id=job_id, type="job", status=status.value, message=message,
            data={"hint": hint} if hint else None,
        ))

    async def _worker(self) -> None:
        assert self._queue is not None
        while True:
            job_id = await self._queue.get()
            try:
                await self._run_job(job_id)
            except Exception:  # never let one job kill the worker
                logger.exception("Unhandled error while running job %s", job_id)
            finally:
                self._queue.task_done()

    async def _run_job(self, job_id: str) -> None:
        job = repo.get_job(self._engine, job_id)
        if job is None or job.status is not JobStatus.queued:
            return
        project = repo.get_project(self._engine, job.project_id)
        if project is None:
            repo.update_job(self._engine, job_id, status=JobStatus.failed, error="The project was deleted.")
            return

        ctx = PipelineContext(
            project_id=project.id, job_id=job_id, settings=self._settings,
            workspace=self._workspace, engine=self._engine, bus=self.bus, video_id=project.video_id,
        )
        self._cancels[job_id] = ctx.cancel_event
        repo.update_job(self._engine, job_id, status=JobStatus.running, progress=0.0, error=None, error_hint=None)
        self._publish_job(job_id, JobStatus.running)

        def on_progress(stage: str, overall: float) -> None:
            repo.update_job(self._engine, job_id, stage=stage, progress=overall)

        assert self._gpu_lock is not None
        try:
            await run_pipeline(
                self._stages_factory(), ctx,
                gpu_lock=self._gpu_lock, video_locks=self._video_locks, on_progress=on_progress,
            )
        except StageCancelled:
            repo.update_job(self._engine, job_id, status=JobStatus.cancelled)
            self._publish_job(job_id, JobStatus.cancelled, message="Cancelled.")
        except StageError as exc:
            repo.update_job(self._engine, job_id, status=JobStatus.failed, error=exc.message, error_hint=exc.hint)
            self._publish_job(job_id, JobStatus.failed, message=exc.message, hint=exc.hint)
        except Exception as exc:
            logger.exception("Job %s failed", job_id)
            error = f"{type(exc).__name__}: {exc}"
            hint = "This looks like a bug. Check the API window's log, then press Retry."
            repo.update_job(self._engine, job_id, status=JobStatus.failed, error=error, error_hint=hint)
            self._publish_job(job_id, JobStatus.failed, message=error, hint=hint)
        else:
            repo.update_job(self._engine, job_id, status=JobStatus.succeeded, progress=1.0)
            self._publish_job(job_id, JobStatus.succeeded)
        finally:
            self._cancels.pop(job_id, None)
```

> Note: `test_unexpected_error_marks_failed` asserts `error == "ValueError: kaboom"`, matching the format above.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/jobs backend/tests/test_queue.py
git commit -m "feat(backend): add asyncio job queue with cancel, failure hints and GPU serialisation"
```

---

### Task 11: HTTP + WebSocket API and app wiring

**Files:**
- Create: `backend/app/api/deps.py`, `backend/app/api/schemas.py`, `backend/app/api/projects.py`, `backend/app/api/jobs.py`, `backend/app/pipeline/registry.py`, `backend/tests/test_api.py`
- Modify: `backend/app/main.py` (full replacement), `backend/tests/fakes.py` (add `FakeIngestStage`, `FakeTranscribeStage`)

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `Services` dataclass (`settings`, `engine`, `workspace`, `bus`, `queue`, `stages_factory`) at `app.state.services`; `get_services(request) -> Services`.
  - `create_app(settings: Settings | None = None, stages_factory: StagesFactory | None = None) -> FastAPI`.
  - `default_stages_factory(settings) -> StagesFactory` (`[IngestStage, TranscribeStage]`, built once, reused).
  - REST (all under `/api`): `POST /projects {url}` → 201 `ProjectOut`; `POST /projects/upload` (multipart `file`) → 201 `ProjectOut`; `GET /projects` → `list[ProjectOut]`; `GET /projects/{id}` → `ProjectOut`; `DELETE /projects/{id}` → 204; `GET /projects/{id}/transcript` → `Transcript` (404 until ready); `POST /projects/{id}/retry` → `ProjectOut` (409 if active); `GET /jobs/{id}` → `JobOut`; `POST /jobs/{id}/cancel` → `JobOut` (409 if finished); `GET /pipeline/stages` → `list[StageInfo]`; `WS /jobs/{id}/events` streams `JobEvent` JSON (history replayed first). Static `/files/*` → `workspace/videos`.
  - `ProjectOut`: `id, created_at, source_type, source_url, original_filename, title, video_id, duration_s, latest_job: JobOut | None`. `JobOut`: `id, project_id, status, stage, progress, error, error_hint, created_at, updated_at` (datetimes serialised with UTC offset). `StageInfo`: `name, label, weight`.

- [ ] **Step 1: Add fake stages**

Append to `backend/tests/fakes.py`:
```python
from app import repo
from app.pipeline.transcript import Segment, Transcript, Word, build_sentences
from app.workspace import atomic_write_json


class FakeIngestStage:
    name, label, weight, uses_gpu = "ingest", "Importing video", 1.0, False

    def is_done(self, ctx: PipelineContext) -> bool:
        return ctx.video_id is not None

    def run(self, ctx: PipelineContext) -> None:
        ctx.video_id = "fakevideo0001"
        repo.update_project(ctx.engine, ctx.project_id, video_id=ctx.video_id, title="Fake video", duration_s=3.0)


class FakeTranscribeStage:
    name, label, weight, uses_gpu = "transcribe", "Transcribing speech", 3.0, True

    def __init__(self, fail_times: int = 0, duration: float = 0.0) -> None:
        self.runs = 0
        self.fail_times = fail_times
        self.duration = duration

    def is_done(self, ctx: PipelineContext) -> bool:
        return ctx.video().transcript.exists()

    def run(self, ctx: PipelineContext) -> None:
        self.runs += 1
        deadline = time.monotonic() + self.duration
        while time.monotonic() < deadline:
            ctx.check_cancelled()
            time.sleep(0.01)
        if self.runs <= self.fail_times:
            from app.pipeline.errors import StageError
            raise StageError("Transient failure", hint="Press Retry")
        words = [Word(text=" Hello", start=0.0, end=0.5), Word(text=" world.", start=0.5, end=1.0)]
        segment = Segment(id=0, start=0.0, end=1.0, text="Hello world.", words=words)
        ctx.emit("partial", stage=self.name, data={"kind": "segment", "start": 0.0, "end": 1.0, "text": "Hello world."})
        atomic_write_json(ctx.video().transcript, Transcript(
            language="en", duration_s=1.0, segments=[segment], words=words, sentences=build_sentences(words),
        ))
```

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_api.py`:
```python
import shutil
import time
from pathlib import Path

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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_api.py -v`
Expected: FAIL — `TypeError: create_app() got an unexpected keyword argument 'stages_factory'`.

- [ ] **Step 4: Implement registry, deps and schemas**

`backend/app/pipeline/registry.py`:
```python
from app.config import Settings
from app.jobs.queue import StagesFactory
from app.pipeline.download import YtDlpDownloader
from app.pipeline.ingest import IngestStage
from app.pipeline.transcribe import FasterWhisperTranscriber, TranscribeStage


def default_stages_factory(settings: Settings) -> StagesFactory:
    # Built once: the transcriber keeps the Whisper model loaded between jobs.
    stages = [
        IngestStage(YtDlpDownloader(
            max_height=settings.max_download_height,
            cookies_file=settings.ytdlp_cookies_file,
            js_runtime=settings.ytdlp_js_runtime,
        )),
        TranscribeStage(FasterWhisperTranscriber(
            model_name=settings.whisper_model,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
            download_root=settings.models_dir / "whisper",
        )),
    ]
    return lambda: stages
```

`backend/app/api/deps.py`:
```python
from dataclasses import dataclass

from fastapi import Request
from sqlalchemy import Engine

from app.config import Settings
from app.events import EventBus
from app.jobs.queue import JobQueue, StagesFactory
from app.workspace import Workspace


@dataclass
class Services:
    settings: Settings
    engine: Engine
    workspace: Workspace
    bus: EventBus
    queue: JobQueue
    stages_factory: StagesFactory


def get_services(request: Request) -> Services:
    return request.app.state.services
```

`backend/app/api/schemas.py`:
```python
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import Engine

from app import repo
from app.models import JobStatus, Project, SourceType


def _as_utc(value: datetime) -> datetime:
    # SQLite drops tzinfo; everything we store is UTC.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    status: JobStatus
    stage: str | None
    progress: float
    error: str | None
    error_hint: str | None
    created_at: datetime
    updated_at: datetime

    utc_dates = field_validator("created_at", "updated_at")(_as_utc)


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    source_type: SourceType
    source_url: str | None
    original_filename: str | None
    title: str | None
    video_id: str | None
    duration_s: float | None
    latest_job: JobOut | None = None

    utc_created = field_validator("created_at")(_as_utc)


class CreateFromUrl(BaseModel):
    url: str


class StageInfo(BaseModel):
    name: str
    label: str
    weight: float


def project_out(engine: Engine, project: Project) -> ProjectOut:
    job = repo.latest_job(engine, project.id)
    out = ProjectOut.model_validate(project)
    out.latest_job = JobOut.model_validate(job) if job else None
    return out
```

- [ ] **Step 5: Implement routers**

`backend/app/api/projects.py`:
```python
import asyncio
import os
import shutil
from pathlib import Path
from typing import BinaryIO

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile

from app import repo
from app.api.deps import Services, get_services
from app.api.schemas import CreateFromUrl, ProjectOut, project_out
from app.models import TERMINAL_STATUSES, Project, SourceType
from app.pipeline.download import validate_source_url
from app.pipeline.ingest import UPLOAD_EXTENSIONS
from app.pipeline.transcript import Transcript
from app.workspace import read_json

router = APIRouter(tags=["projects"])


def _get_project_or_404(svc: Services, project_id: str) -> Project:
    project = repo.get_project(svc.engine, project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    return project


def _start_job(svc: Services, project: Project) -> ProjectOut:
    job = repo.create_job(svc.engine, project.id)
    svc.queue.submit(job.id)
    return project_out(svc.engine, project)


def _save_upload(src: BinaryIO, dest: Path) -> None:
    tmp = dest.with_name(dest.name + ".part")
    with tmp.open("wb") as out:
        shutil.copyfileobj(src, out, 8 * 1024 * 1024)  # streamed: multi-GB files never sit in RAM
    os.replace(tmp, dest)


@router.post("/projects", status_code=201, response_model=ProjectOut)
async def create_from_url(body: CreateFromUrl, svc: Services = Depends(get_services)) -> ProjectOut:
    try:
        url = validate_source_url(body.url)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    project = repo.create_project(svc.engine, source_type=SourceType.url, source_url=url)
    return _start_job(svc, project)


@router.post("/projects/upload", status_code=201, response_model=ProjectOut)
async def create_from_upload(file: UploadFile, svc: Services = Depends(get_services)) -> ProjectOut:
    name = Path(file.filename or "video.mp4").name
    ext = Path(name).suffix.lower()
    if ext not in UPLOAD_EXTENSIONS:
        allowed = ", ".join(sorted(e.lstrip(".").upper() for e in UPLOAD_EXTENSIONS))
        raise HTTPException(415, f"Unsupported file type '{ext or 'none'}'. Use {allowed}.")
    project = repo.create_project(
        svc.engine, source_type=SourceType.upload, original_filename=name, title=Path(name).stem
    )
    dest = svc.workspace.project_dir(project.id) / f"upload{ext}"
    try:
        await asyncio.to_thread(_save_upload, file.file, dest)
    except OSError as exc:
        repo.delete_project(svc.engine, project.id)
        svc.workspace.remove_project(project.id)
        raise HTTPException(507, f"Couldn't save the upload: {exc}") from exc
    return _start_job(svc, project)


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(svc: Services = Depends(get_services)) -> list[ProjectOut]:
    return [project_out(svc.engine, p) for p in repo.list_projects(svc.engine)]


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, svc: Services = Depends(get_services)) -> ProjectOut:
    return project_out(svc.engine, _get_project_or_404(svc, project_id))


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: str, svc: Services = Depends(get_services)) -> Response:
    _get_project_or_404(svc, project_id)
    job = repo.latest_job(svc.engine, project_id)
    if job is not None:
        svc.queue.cancel(job.id)
        svc.bus.forget(job.id)
    repo.delete_project(svc.engine, project_id)
    svc.workspace.remove_project(project_id)
    return Response(status_code=204)


@router.get("/projects/{project_id}/transcript", response_model=Transcript)
def get_transcript(project_id: str, svc: Services = Depends(get_services)) -> Transcript:
    project = _get_project_or_404(svc, project_id)
    if project.video_id is None or not svc.workspace.video(project.video_id).transcript.exists():
        raise HTTPException(404, "The transcript isn't ready yet")
    return Transcript.model_validate(read_json(svc.workspace.video(project.video_id).transcript))


@router.post("/projects/{project_id}/retry", response_model=ProjectOut)
def retry_project(project_id: str, svc: Services = Depends(get_services)) -> ProjectOut:
    project = _get_project_or_404(svc, project_id)
    job = repo.latest_job(svc.engine, project_id)
    if job is not None and job.status not in TERMINAL_STATUSES:
        raise HTTPException(409, "This project is already processing")
    return _start_job(svc, project)
```

`backend/app/api/jobs.py`:
```python
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect

from app import repo
from app.api.deps import Services, get_services
from app.api.schemas import JobOut, StageInfo
from app.models import TERMINAL_STATUSES

router = APIRouter(tags=["jobs"])


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, svc: Services = Depends(get_services)) -> JobOut:
    job = repo.get_job(svc.engine, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return JobOut.model_validate(job)


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: str, svc: Services = Depends(get_services)) -> JobOut:
    job = repo.get_job(svc.engine, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    if job.status in TERMINAL_STATUSES or not svc.queue.cancel(job_id):
        raise HTTPException(409, "This job has already finished")
    return JobOut.model_validate(repo.get_job(svc.engine, job_id))


@router.get("/pipeline/stages", response_model=list[StageInfo])
def pipeline_stages(svc: Services = Depends(get_services)) -> list[StageInfo]:
    return [StageInfo(name=s.name, label=s.label, weight=s.weight) for s in svc.stages_factory()]


@router.websocket("/jobs/{job_id}/events")
async def job_events(websocket: WebSocket, job_id: str) -> None:
    svc: Services = websocket.app.state.services
    await websocket.accept()
    queue = svc.bus.subscribe(job_id)
    try:
        while True:
            event = await queue.get()
            await websocket.send_text(event.model_dump_json())
    except WebSocketDisconnect:
        pass
    finally:
        svc.bus.unsubscribe(job_id, queue)
```

- [ ] **Step 6: Replace `backend/app/main.py`**

```python
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import __version__, repo
from app.api import jobs, projects, system
from app.api.deps import Services
from app.config import Settings, get_settings
from app.db import make_engine
from app.events import EventBus
from app.gpu import register_cuda_dlls
from app.jobs.queue import JobQueue, StagesFactory
from app.workspace import Workspace

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(settings: Settings | None = None, stages_factory: StagesFactory | None = None) -> FastAPI:
    settings = settings or get_settings()
    register_cuda_dlls()  # before anything imports ctranslate2

    workspace = Workspace(settings.workspace_dir)
    engine = make_engine(settings.db_url)
    bus = EventBus()
    if stages_factory is None:
        from app.pipeline.registry import default_stages_factory

        stages_factory = default_stages_factory(settings)
    queue = JobQueue(
        engine=engine, workspace=workspace, settings=settings, bus=bus,
        stages_factory=stages_factory, concurrency=settings.job_concurrency,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await queue.start()
        for job_id in repo.recover_interrupted_jobs(engine):
            queue.submit(job_id)
        yield
        await queue.stop()
        engine.dispose()

    app = FastAPI(title="ClipForge API", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.services = Services(settings, engine, workspace, bus, queue, stages_factory)
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"],
    )
    app.include_router(system.router, prefix="/api")
    app.include_router(projects.router, prefix="/api")
    app.include_router(jobs.router, prefix="/api")
    app.mount("/files", StaticFiles(directory=workspace.videos_dir), name="files")
    return app
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest -v`
Expected: all passed (gpu/network deselected). If `test_concurrent_uploads_of_same_video_transcribe_once` is flaky, the per-video lock in `run_pipeline` is not wrapping `is_done` — fix the runner, not the test.

- [ ] **Step 8: Commit**

```bash
git add backend/app backend/tests
git commit -m "feat(backend): add projects/jobs REST + WebSocket API and wire the job queue"
```

---
### Task 12: Frontend scaffold, design system, app shell and API client

**Files:**
- Create: `frontend/package.json`, `frontend/index.html`, `frontend/public/favicon.svg`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/src/vite-env.d.ts`, `frontend/src/index.css`, `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/lib/types.ts`, `frontend/src/lib/api.ts`, `frontend/src/lib/theme.ts`, `frontend/src/lib/useSmoothScroll.ts`, `frontend/src/components/{AppShell,Logo,Grain,PageTransition,NotFound,Skeleton,MagneticButton,StatusChip}.tsx`, `frontend/src/features/home/HomePage.tsx` (stub, replaced in Task 13), `frontend/src/features/processing/ProcessingPage.tsx` (stub, replaced in Task 14), `frontend/src/test/setup.ts`, `frontend/src/test/utils.tsx`, `frontend/src/test/fixtures.ts`, `frontend/src/lib/api.test.ts`, `frontend/src/components/AppShell.test.tsx`

**Interfaces:**
- Consumes: backend REST shapes from Task 11 (`ProjectOut`, `JobOut`, `StageInfo`, `Transcript`, `JobEvent`).
- Produces:
  - `types.ts`: `JobStatus`, `Job`, `Project`, `StageInfo`, `StageStatus`, `JobEvent`, `TranscriptLine`, `Transcript`, `SystemInfo`, `TERMINAL: JobStatus[]`, `isTerminal(status?) -> boolean`.
  - `api.ts`: `ApiError(status, message)`; `api.listProjects()`, `api.getProject(id)`, `api.createFromUrl(url)`, `api.upload(file, onProgress)`, `api.retry(projectId)`, `api.cancelJob(jobId)`, `api.deleteProject(id)`, `api.stages()`, `api.transcript(projectId)`, `api.system()`; `jobEventsUrl(jobId) -> string`.
  - `theme.ts`: `Theme`, `getStoredTheme()`, `applyTheme(theme)`, `applyStoredTheme()`.
  - Components: `AppShell({children})`, `Logo({className})`, `Grain()`, `PageTransition({children})`, `NotFound()`, `Skeleton({className})`, `MagneticButton(props & {strength?})`, `StatusChip({status})`.
  - Tailwind tokens (use these class names everywhere): `bg-bg`, `text-fg`, `text-muted`, `bg-surface`, `bg-surface-2`, `border-border`, `*-violet-brand`, `*-indigo-brand`, `*-cyan-brand`, `*-ember`, `*-gold`, `font-display`, `font-sans`, `font-mono`, `animate-shimmer`, utility `.text-gradient`.
  - Test helpers: `renderWithProviders(ui, {route?, path?})` (renders `<LocationProbe/>` with `data-testid="location"` for any other path), `makeProject(overrides)`, `makeJob(overrides)`.

- [ ] **Step 1: Create the package and install dependencies**

`frontend/package.json`:
```json
{
  "name": "clipforge-ui",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "preview": "vite preview",
    "typecheck": "tsc --noEmit",
    "test": "vitest run"
  }
}
```

Run (from `frontend/`):
```bash
npm install react react-dom react-router @tanstack/react-query motion gsap @gsap/react lenis three @react-three/fiber lucide-react clsx
npm install -D vite @vitejs/plugin-react typescript@~5.9 @types/react @types/react-dom @types/three tailwindcss @tailwindcss/vite vitest jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event
```
Expected: `package-lock.json` created, no `ERESOLVE` errors.

- [ ] **Step 2: Tooling config**

`frontend/vite.config.ts`:
```ts
/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", ws: true, changeOrigin: true },
      "/files": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
```

`frontend/tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2023", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noEmit": true,
    "skipLibCheck": true,
    "isolatedModules": true,
    "resolveJsonModule": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "types": ["vite/client", "vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src", "vite.config.ts"]
}
```

`frontend/src/vite-env.d.ts`:
```ts
/// <reference types="vite/client" />
```

`frontend/index.html`:
```html
<!doctype html>
<html lang="en" data-theme="dark">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="description" content="ClipForge — turn long videos into viral shorts with AI." />
    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet" />
    <link href="https://api.fontshare.com/v2/css?f[]=clash-display@500,600,700&display=swap" rel="stylesheet" />
    <title>ClipForge</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`frontend/public/favicon.svg`:
```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><defs><linearGradient id="a" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#8b5cf6"/><stop offset=".55" stop-color="#6366f1"/><stop offset="1" stop-color="#22d3ee"/></linearGradient><linearGradient id="e" x1="0" y1="1" x2="0" y2="0"><stop offset="0" stop-color="#f97316"/><stop offset="1" stop-color="#facc15"/></linearGradient></defs><rect width="64" height="64" rx="16" fill="url(#a)"/><path d="M22 18 46 32 22 46Z" fill="#07060d"/><path d="m40 44 6-10 6 10z" fill="url(#e)"/></svg>
```

- [ ] **Step 3: Design tokens**

`frontend/src/index.css`:
```css
@import "tailwindcss";
@import "lenis/dist/lenis.css";

@theme {
  --font-display: "Clash Display", "Inter", ui-sans-serif, system-ui, sans-serif;
  --font-sans: "Inter", ui-sans-serif, system-ui, sans-serif;
  --font-mono: "JetBrains Mono", ui-monospace, monospace;

  --color-violet-brand: #8b5cf6;
  --color-indigo-brand: #6366f1;
  --color-cyan-brand: #22d3ee;
  --color-ember: #f97316;
  --color-gold: #facc15;

  --animate-shimmer: shimmer 1.6s linear infinite;
  @keyframes shimmer {
    from { background-position: 200% 0; }
    to { background-position: -200% 0; }
  }
}

@theme inline {
  --color-bg: var(--bg);
  --color-fg: var(--fg);
  --color-muted: var(--muted);
  --color-surface: var(--surface);
  --color-surface-2: var(--surface-2);
  --color-border: var(--border);
}

:root,
[data-theme="dark"] {
  --bg: #07060d;
  --fg: #f4f3ff;
  --muted: #9b9bb4;
  --surface: rgb(255 255 255 / 0.04);
  --surface-2: rgb(255 255 255 / 0.08);
  --border: rgb(255 255 255 / 0.1);
  color-scheme: dark;
}

[data-theme="light"] {
  --bg: #f7f6fb;
  --fg: #120f22;
  --muted: #5d5a73;
  --surface: rgb(18 15 34 / 0.04);
  --surface-2: rgb(18 15 34 / 0.07);
  --border: rgb(18 15 34 / 0.12);
  color-scheme: light;
}

html, body { background: var(--bg); color: var(--fg); }
body { font-family: var(--font-sans); -webkit-font-smoothing: antialiased; }
::selection { background: rgb(139 92 246 / 0.35); }

.text-gradient {
  background: linear-gradient(90deg, #8b5cf6, #6366f1 55%, #22d3ee);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```

- [ ] **Step 4: Write the failing tests and test helpers**

`frontend/src/test/setup.ts`:
```ts
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

afterEach(() => cleanup());

// Report reduced motion so Lenis/GSAP/WebGL effects stay off in jsdom.
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: query.includes("reduce"),
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }),
});

class MockIntersectionObserver {
  readonly root = null;
  readonly rootMargin = "";
  readonly thresholds = [];
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() { return []; }
}
window.IntersectionObserver = MockIntersectionObserver as unknown as typeof IntersectionObserver;
Element.prototype.scrollIntoView = vi.fn();
```

`frontend/src/test/utils.tsx`:
```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";

export function LocationProbe() {
  return <div data-testid="location">{useLocation().pathname}</div>;
}

export function renderWithProviders(ui: ReactElement, { route = "/", path = "/" } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const result = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path={path} element={ui} />
          <Route path="*" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { queryClient, ...result };
}
```

`frontend/src/test/fixtures.ts`:
```ts
import type { Job, Project } from "../lib/types";

export function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id: "j1", project_id: "p1", status: "queued", stage: null, progress: 0,
    error: null, error_hint: null,
    created_at: "2026-10-03T10:00:00+00:00", updated_at: "2026-10-03T10:00:00+00:00",
    ...overrides,
  };
}

export function makeProject(overrides: Partial<Project> = {}): Project {
  return {
    id: "p1", created_at: "2026-10-03T10:00:00+00:00", source_type: "url",
    source_url: "https://youtu.be/abc", original_filename: null, title: null,
    video_id: null, duration_s: null, latest_job: makeJob(),
    ...overrides,
  };
}
```

`frontend/src/lib/api.test.ts`:
```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, jobEventsUrl } from "./api";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("api", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("parses JSON responses", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse([{ id: "p1" }])));
    await expect(api.listProjects()).resolves.toEqual([{ id: "p1" }]);
  });

  it("posts JSON for createFromUrl", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ id: "p1" }, 201));
    vi.stubGlobal("fetch", fetchMock);
    await api.createFromUrl("https://youtu.be/x");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/projects");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ url: "https://youtu.be/x" });
    expect(init.headers["Content-Type"]).toBe("application/json");
  });

  it("throws ApiError with the server's detail message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "Enter a full http(s) link" }, 422)));
    await expect(api.createFromUrl("x")).rejects.toMatchObject({ status: 422, message: "Enter a full http(s) link" });
  });

  it("flattens FastAPI validation errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: [{ msg: "Field required" }] }, 422)));
    const error = await api.createFromUrl("x").catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.message).toBe("Field required");
  });

  it("builds websocket URLs from the page origin", () => {
    expect(jobEventsUrl("j1")).toBe(`ws://${window.location.host}/api/jobs/j1/events`);
  });
});
```

`frontend/src/components/AppShell.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { expect, it } from "vitest";
import { AppShell } from "./AppShell";

it("renders the brand, children and toggles the theme", async () => {
  document.documentElement.dataset.theme = "dark";
  render(
    <MemoryRouter>
      <AppShell><p>child content</p></AppShell>
    </MemoryRouter>,
  );
  expect(screen.getByRole("link", { name: /clipforge home/i })).toBeInTheDocument();
  expect(screen.getByText("child content")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /switch to light theme/i }));
  expect(document.documentElement.dataset.theme).toBe("light");
  await userEvent.click(screen.getByRole("button", { name: /switch to dark theme/i }));
  expect(document.documentElement.dataset.theme).toBe("dark");
});
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `npx vitest run`
Expected: FAIL — cannot resolve `./api` and `./AppShell`.

- [ ] **Step 6: Implement lib**

`frontend/src/lib/types.ts`:
```ts
export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";
export const TERMINAL: JobStatus[] = ["succeeded", "failed", "cancelled"];
export const isTerminal = (status?: JobStatus | null) => !!status && TERMINAL.includes(status);

export interface Job {
  id: string;
  project_id: string;
  status: JobStatus;
  stage: string | null;
  progress: number;
  error: string | null;
  error_hint: string | null;
  created_at: string;
  updated_at: string;
}

export interface Project {
  id: string;
  created_at: string;
  source_type: "url" | "upload";
  source_url: string | null;
  original_filename: string | null;
  title: string | null;
  video_id: string | null;
  duration_s: number | null;
  latest_job: Job | null;
}

export interface StageInfo {
  name: string;
  label: string;
  weight: number;
}

export type StageStatus = "pending" | "running" | "done" | "cached" | "failed" | "cancelled";

export interface JobEvent {
  job_id: string;
  type: "stage" | "progress" | "log" | "partial" | "job";
  stage: string | null;
  status: string | null;
  progress: number | null;
  message: string | null;
  data: Record<string, unknown> | null;
  ts: number;
}

export interface TranscriptLine {
  start: number;
  end: number;
  text: string;
}

export interface Transcript {
  language: string;
  duration_s: number;
  segments: (TranscriptLine & { id: number })[];
}

export interface SystemInfo {
  gpus: { name: string; memory_total_mb: number; driver: string }[];
  ffmpeg: boolean;
  nvenc: boolean;
}
```

`frontend/src/lib/api.ts`:
```ts
import type { Job, Project, StageInfo, SystemInfo, Transcript } from "./types";

const BASE = "/api";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

function detailMessage(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length && typeof detail[0]?.msg === "string") return detail[0].msg;
  return fallback;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>) };
  if (init.body && !(init.body instanceof FormData)) headers["Content-Type"] = "application/json";
  const res = await fetch(BASE + path, { ...init, headers });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(res.status, detailMessage(body, res.statusText || `Request failed (${res.status})`));
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

function upload(file: File, onProgress: (fraction: number) => void): Promise<Project> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${BASE}/projects/upload`);
    xhr.responseType = "json";
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response as Project);
      else reject(new ApiError(xhr.status, detailMessage(xhr.response, "Upload failed")));
    };
    xhr.onerror = () => reject(new ApiError(0, "Upload failed — is the ClipForge API running?"));
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}

export const api = {
  listProjects: () => request<Project[]>("/projects"),
  getProject: (id: string) => request<Project>(`/projects/${id}`),
  createFromUrl: (url: string) => request<Project>("/projects", { method: "POST", body: JSON.stringify({ url }) }),
  upload,
  retry: (projectId: string) => request<Project>(`/projects/${projectId}/retry`, { method: "POST" }),
  cancelJob: (jobId: string) => request<Job>(`/jobs/${jobId}/cancel`, { method: "POST" }),
  deleteProject: (id: string) => request<void>(`/projects/${id}`, { method: "DELETE" }),
  stages: () => request<StageInfo[]>("/pipeline/stages"),
  transcript: (projectId: string) => request<Transcript>(`/projects/${projectId}/transcript`),
  system: () => request<SystemInfo>("/system"),
};

export function jobEventsUrl(jobId: string): string {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}${BASE}/jobs/${jobId}/events`;
}
```

`frontend/src/lib/theme.ts`:
```ts
export type Theme = "dark" | "light";
const KEY = "clipforge-theme";

export function getStoredTheme(): Theme {
  try {
    return localStorage.getItem(KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    /* storage unavailable (private mode) — theme still applies for this visit */
  }
}

export function applyStoredTheme(): void {
  applyTheme(getStoredTheme());
}
```

`frontend/src/lib/useSmoothScroll.ts`:
```ts
import Lenis from "lenis";
import { useEffect } from "react";

export function useSmoothScroll(): void {
  useEffect(() => {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    const lenis = new Lenis({ autoRaf: true, lerp: 0.12 });
    return () => lenis.destroy();
  }, []);
}
```

- [ ] **Step 7: Implement components**

`frontend/src/components/Logo.tsx`:
```tsx
import { useId } from "react";

export function Logo({ className }: { className?: string }) {
  const id = useId();
  return (
    <svg viewBox="0 0 64 64" className={className} aria-hidden="true">
      <defs>
        <linearGradient id={`${id}a`} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#8b5cf6" />
          <stop offset=".55" stopColor="#6366f1" />
          <stop offset="1" stopColor="#22d3ee" />
        </linearGradient>
        <linearGradient id={`${id}e`} x1="0" y1="1" x2="0" y2="0">
          <stop offset="0" stopColor="#f97316" />
          <stop offset="1" stopColor="#facc15" />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="16" fill={`url(#${id}a)`} />
      <path d="M22 18 46 32 22 46Z" fill="#07060d" />
      <path d="m40 44 6-10 6 10z" fill={`url(#${id}e)`} />
    </svg>
  );
}
```

`frontend/src/components/Grain.tsx`:
```tsx
const NOISE =
  "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.8' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E\")";

export function Grain() {
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none fixed inset-0 z-50 opacity-[0.05] mix-blend-overlay"
      style={{ backgroundImage: NOISE }}
    />
  );
}
```

`frontend/src/components/PageTransition.tsx`:
```tsx
import { motion } from "motion/react";
import type { ReactNode } from "react";

export function PageTransition({ children }: { children: ReactNode }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16, filter: "blur(6px)" }}
      animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
      exit={{ opacity: 0, y: -8, filter: "blur(4px)" }}
      transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
    >
      {children}
    </motion.div>
  );
}
```

`frontend/src/components/Skeleton.tsx`:
```tsx
import clsx from "clsx";

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={clsx(
        "animate-shimmer rounded-xl bg-[length:200%_100%]",
        "bg-[linear-gradient(90deg,var(--surface)_25%,var(--surface-2)_50%,var(--surface)_75%)]",
        className,
      )}
    />
  );
}
```

`frontend/src/components/MagneticButton.tsx`:
```tsx
import { motion, useSpring } from "motion/react";
import { useRef, type ComponentProps } from "react";

type Props = ComponentProps<typeof motion.button> & { strength?: number };

export function MagneticButton({ strength = 0.25, children, ...props }: Props) {
  const ref = useRef<HTMLButtonElement>(null);
  const x = useSpring(0, { stiffness: 300, damping: 20 });
  const y = useSpring(0, { stiffness: 300, damping: 20 });
  return (
    <motion.button
      ref={ref}
      style={{ x, y }}
      whileTap={{ scale: 0.96 }}
      onPointerMove={(e) => {
        const r = ref.current?.getBoundingClientRect();
        if (!r) return;
        x.set((e.clientX - (r.left + r.width / 2)) * strength);
        y.set((e.clientY - (r.top + r.height / 2)) * strength);
      }}
      onPointerLeave={() => {
        x.set(0);
        y.set(0);
      }}
      {...props}
    >
      {children}
    </motion.button>
  );
}
```

`frontend/src/components/StatusChip.tsx`:
```tsx
import clsx from "clsx";
import type { JobStatus } from "../lib/types";

const STYLES: Record<JobStatus, { label: string; className: string }> = {
  queued: { label: "Queued", className: "bg-surface-2 text-muted" },
  running: { label: "Processing", className: "bg-violet-brand/15 text-violet-400" },
  succeeded: { label: "Ready", className: "bg-emerald-500/15 text-emerald-400" },
  failed: { label: "Failed", className: "bg-red-500/15 text-red-400" },
  cancelled: { label: "Cancelled", className: "bg-surface-2 text-muted" },
};

export function StatusChip({ status }: { status: JobStatus }) {
  const style = STYLES[status];
  return (
    <span className={clsx("inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium", style.className)}>
      {status === "running" && <span className="size-1.5 animate-pulse rounded-full bg-current" />}
      {style.label}
    </span>
  );
}
```

`frontend/src/components/NotFound.tsx`:
```tsx
import { Link } from "react-router";
import { PageTransition } from "./PageTransition";

export function NotFound({ message = "This page doesn't exist." }: { message?: string }) {
  return (
    <PageTransition>
      <div className="mx-auto flex max-w-md flex-col items-center px-4 py-32 text-center">
        <p className="font-display text-7xl font-semibold text-gradient">404</p>
        <p className="mt-4 text-muted">{message}</p>
        <Link to="/" className="mt-8 rounded-full bg-fg px-5 py-2.5 text-sm font-semibold text-bg">
          Back to ClipForge
        </Link>
      </div>
    </PageTransition>
  );
}
```

`frontend/src/components/AppShell.tsx`:
```tsx
import { Moon, Sun } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router";
import { applyTheme, getStoredTheme, type Theme } from "../lib/theme";
import { useSmoothScroll } from "../lib/useSmoothScroll";
import { Grain } from "./Grain";
import { Logo } from "./Logo";

export function AppShell({ children }: { children: ReactNode }) {
  useSmoothScroll();
  const [theme, setTheme] = useState<Theme>(getStoredTheme);
  const next: Theme = theme === "dark" ? "light" : "dark";

  return (
    <div className="relative min-h-dvh overflow-x-clip">
      <Grain />
      <header className="sticky top-0 z-40 border-b border-border/60 bg-bg/70 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
          <Link to="/" className="flex items-center gap-2.5" aria-label="ClipForge home">
            <Logo className="size-8" />
            <span className="font-display text-lg font-semibold tracking-tight">
              Clip<span className="text-gradient">Forge</span>
            </span>
          </Link>
          <nav className="flex items-center gap-1">
            <Link to="/" className="rounded-full px-4 py-2 text-sm text-muted transition hover:bg-surface-2 hover:text-fg">
              New project
            </Link>
            <button
              type="button"
              aria-label={`Switch to ${next} theme`}
              onClick={() => {
                applyTheme(next);
                setTheme(next);
              }}
              className="grid size-9 place-items-center rounded-full text-muted transition hover:bg-surface-2 hover:text-fg"
            >
              {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
            </button>
          </nav>
        </div>
      </header>
      <main>{children}</main>
    </div>
  );
}
```

- [ ] **Step 8: App entry, routes and page stubs**

`frontend/src/features/home/HomePage.tsx` (stub — Task 13 replaces it):
```tsx
import { PageTransition } from "../../components/PageTransition";

export default function HomePage() {
  return (
    <PageTransition>
      <h1 className="px-6 py-32 text-center font-display text-6xl font-semibold text-gradient">ClipForge</h1>
    </PageTransition>
  );
}
```

`frontend/src/features/processing/ProcessingPage.tsx` (stub — Task 14 replaces it):
```tsx
import { PageTransition } from "../../components/PageTransition";

export default function ProcessingPage() {
  return <PageTransition><p className="px-6 py-32 text-center text-muted">Processing…</p></PageTransition>;
}
```

`frontend/src/App.tsx`:
```tsx
import { AnimatePresence } from "motion/react";
import { Route, Routes, useLocation } from "react-router";
import { AppShell } from "./components/AppShell";
import { NotFound } from "./components/NotFound";
import HomePage from "./features/home/HomePage";
import ProcessingPage from "./features/processing/ProcessingPage";

export default function App() {
  const location = useLocation();
  return (
    <AppShell>
      <AnimatePresence mode="wait">
        <Routes location={location} key={location.pathname}>
          <Route path="/" element={<HomePage />} />
          <Route path="/projects/:projectId" element={<ProcessingPage />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </AnimatePresence>
    </AppShell>
  );
}
```

`frontend/src/main.tsx`:
```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MotionConfig } from "motion/react";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import App from "./App";
import "./index.css";
import { applyStoredTheme } from "./lib/theme";

applyStoredTheme();

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <MotionConfig reducedMotion="user">
          <App />
        </MotionConfig>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
```

- [ ] **Step 9: Run tests, typecheck and build**

Run: `npx vitest run` → Expected: all passed.
Run: `npm run build` → Expected: `tsc` reports no errors and Vite prints `✓ built in …`.

- [ ] **Step 10: Commit**

```bash
git add frontend
git commit -m "feat(frontend): scaffold Vite React app with design system, app shell and API client"
```

---

### Task 13: Home screen (hero, URL input, drop zone, recent projects)

**Files:**
- Create: `frontend/src/lib/url.ts`, `frontend/src/lib/format.ts`, `frontend/src/components/StaticGradient.tsx`, `frontend/src/components/ShaderBackground.tsx`, `frontend/src/features/home/{HeroHeadline,HeroInput,DropZone,RecentProjects}.tsx`, `frontend/src/lib/url.test.ts`, `frontend/src/lib/format.test.ts`, `frontend/src/features/home/HomePage.test.tsx`
- Modify: `frontend/src/features/home/HomePage.tsx` (full replacement)

**Interfaces:**
- Consumes: Task 12 `api`, `ApiError`, types, `PageTransition`, `MagneticButton`, `Skeleton`, `StatusChip`, test helpers.
- Produces: `normalizeSourceUrl(input: string) -> string | null`; `UPLOAD_EXTENSIONS: string[]`; `fileExtension(name) -> string`; `projectTitle(p: Project) -> string`; `formatDuration(seconds) -> string` (`m:ss` / `h:mm:ss`); `formatTimestamp(seconds) -> string` (`m:ss`); `formatRelative(iso, now = Date.now()) -> string`; default-export `ShaderBackground`; `StaticGradient`.

- [ ] **Step 1: Write the failing tests**

`frontend/src/lib/url.test.ts`:
```ts
import { describe, expect, it } from "vitest";
import { normalizeSourceUrl } from "./url";

describe("normalizeSourceUrl", () => {
  it.each([
    ["https://www.youtube.com/watch?v=abc", "https://www.youtube.com/watch?v=abc"],
    ["youtube.com/watch?v=abc", "https://youtube.com/watch?v=abc"],
    ["  youtu.be/abc?t=30  ", "https://youtu.be/abc?t=30"],
    ["https://www.youtube.com/shorts/xyz", "https://www.youtube.com/shorts/xyz"],
    ["http://vimeo.com/123", "http://vimeo.com/123"],
  ])("accepts %s", (input, expected) => {
    expect(normalizeSourceUrl(input)).toBe(expected);
  });

  it.each(["", "   ", "hello", "javascript:alert(1)", "ftp://example.com/a.mp4", "https://"])(
    "rejects %s",
    (input) => {
      expect(normalizeSourceUrl(input)).toBeNull();
    },
  );
});
```

`frontend/src/lib/format.test.ts`:
```ts
import { describe, expect, it } from "vitest";
import { makeProject } from "../test/fixtures";
import { fileExtension, formatDuration, formatRelative, formatTimestamp, projectTitle } from "./format";

describe("format", () => {
  it("formats durations", () => {
    expect(formatDuration(5)).toBe("0:05");
    expect(formatDuration(725)).toBe("12:05");
    expect(formatDuration(3723)).toBe("1:02:03");
  });

  it("formats transcript timestamps", () => {
    expect(formatTimestamp(0)).toBe("0:00");
    expect(formatTimestamp(61.9)).toBe("1:01");
  });

  it("formats relative times", () => {
    const now = Date.parse("2026-10-03T12:00:00Z");
    expect(formatRelative("2026-10-03T11:59:40+00:00", now)).toBe("just now");
    expect(formatRelative("2026-10-03T11:55:00+00:00", now)).toBe("5 min ago");
    expect(formatRelative("2026-10-03T09:00:00+00:00", now)).toBe("3 h ago");
    expect(formatRelative("2026-09-01T09:00:00+00:00", now)).toMatch(/2026|Sep/);
  });

  it("picks the best project title", () => {
    expect(projectTitle(makeProject({ title: "My Talk" }))).toBe("My Talk");
    expect(projectTitle(makeProject({ title: null, source_type: "upload", original_filename: "a b.mp4" }))).toBe("a b.mp4");
    expect(projectTitle(makeProject({ title: null, source_url: "https://youtu.be/abc" }))).toBe("youtu.be/abc");
  });

  it("extracts lowercase extensions", () => {
    expect(fileExtension("My Clip.MP4")).toBe(".mp4");
    expect(fileExtension("noext")).toBe("");
  });
});
```

`frontend/src/features/home/HomePage.test.tsx`:
```tsx
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { ApiError, api } from "../../lib/api";
import { makeJob, makeProject } from "../../test/fixtures";
import { renderWithProviders } from "../../test/utils";
import HomePage from "./HomePage";

vi.mock("../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api")>();
  return {
    ...actual,
    api: { ...actual.api, createFromUrl: vi.fn(), listProjects: vi.fn(), upload: vi.fn() },
  };
});
vi.mock("../../components/ShaderBackground", () => ({ default: () => null }));

beforeEach(() => {
  vi.mocked(api.listProjects).mockResolvedValue([]);
  vi.mocked(api.createFromUrl).mockReset();
  vi.mocked(api.upload).mockReset();
});

it("creates a project from a pasted link and opens it", async () => {
  vi.mocked(api.createFromUrl).mockResolvedValue(makeProject({ id: "p1" }));
  renderWithProviders(<HomePage />);
  await userEvent.type(screen.getByLabelText(/video link/i), "youtube.com/watch?v=abc");
  await userEvent.click(screen.getByRole("button", { name: /forge clips/i }));
  await waitFor(() => expect(api.createFromUrl).toHaveBeenCalledWith("https://youtube.com/watch?v=abc"));
  expect(await screen.findByTestId("location")).toHaveTextContent("/projects/p1");
});

it("explains invalid links without calling the API", async () => {
  renderWithProviders(<HomePage />);
  await userEvent.type(screen.getByLabelText(/video link/i), "hello");
  await userEvent.click(screen.getByRole("button", { name: /forge clips/i }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/doesn't look like a video link/i);
  expect(api.createFromUrl).not.toHaveBeenCalled();
});

it("shows server errors", async () => {
  vi.mocked(api.createFromUrl).mockRejectedValue(new ApiError(422, "Enter a full http(s) link"));
  renderWithProviders(<HomePage />);
  await userEvent.type(screen.getByLabelText(/video link/i), "https://youtu.be/x");
  await userEvent.click(screen.getByRole("button", { name: /forge clips/i }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Enter a full http(s) link");
});

it("rejects unsupported upload types", async () => {
  const user = userEvent.setup({ applyAccept: false });
  renderWithProviders(<HomePage />);
  await user.upload(screen.getByTestId("file-input"), new File(["x"], "notes.txt", { type: "text/plain" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/unsupported file type/i);
  expect(api.upload).not.toHaveBeenCalled();
});

it("uploads a video and opens the project", async () => {
  vi.mocked(api.upload).mockImplementation(async (_file, onProgress) => {
    onProgress(0.5);
    return makeProject({ id: "p2" });
  });
  const user = userEvent.setup({ applyAccept: false });
  renderWithProviders(<HomePage />);
  await user.upload(screen.getByTestId("file-input"), new File(["x"], "talk.MP4", { type: "video/mp4" }));
  expect(await screen.findByTestId("location")).toHaveTextContent("/projects/p2");
});

it("lists recent projects with their status", async () => {
  vi.mocked(api.listProjects).mockResolvedValue([
    makeProject({ id: "p3", title: "My Talk", latest_job: makeJob({ status: "succeeded" }) }),
  ]);
  renderWithProviders(<HomePage />);
  expect(await screen.findByText("My Talk")).toBeInTheDocument();
  expect(screen.getByText("Ready")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/lib src/features/home`
Expected: FAIL — cannot resolve `./url`, `./format`; HomePage tests fail to find the labelled input.

- [ ] **Step 3: Implement lib helpers**

`frontend/src/lib/url.ts`:
```ts
export const UPLOAD_EXTENSIONS = [".mp4", ".mkv", ".mov", ".webm", ".m4v", ".avi"];

export function normalizeSourceUrl(input: string): string | null {
  let candidate = input.trim();
  if (!candidate) return null;
  if (!/^[a-z][a-z0-9+.-]*:/i.test(candidate)) candidate = `https://${candidate}`;
  try {
    const url = new URL(candidate);
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    if (!url.hostname.includes(".")) return null;
    return url.toString();
  } catch {
    return null;
  }
}
```

`frontend/src/lib/format.ts`:
```ts
import type { Project } from "./types";

const pad = (n: number) => String(n).padStart(2, "0");

export function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

export function formatTimestamp(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  return `${Math.floor(total / 60)}:${pad(total % 60)}`;
}

export function formatRelative(iso: string, now: number = Date.now()): string {
  const diff = (now - Date.parse(iso)) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function projectTitle(project: Project): string {
  if (project.title) return project.title;
  if (project.original_filename) return project.original_filename;
  if (project.source_url) return project.source_url.replace(/^https?:\/\/(www\.)?/, "");
  return "Untitled project";
}

export function fileExtension(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot).toLowerCase() : "";
}
```

- [ ] **Step 4: Implement the animated background**

`frontend/src/components/StaticGradient.tsx`:
```tsx
export function StaticGradient() {
  return (
    <div
      aria-hidden="true"
      className="absolute inset-0 bg-[radial-gradient(60%_50%_at_70%_20%,rgb(139_92_246/0.35),transparent),radial-gradient(50%_40%_at_20%_80%,rgb(34_211_238/0.18),transparent)]"
    />
  );
}
```

`frontend/src/components/ShaderBackground.tsx`:
```tsx
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { useReducedMotion } from "motion/react";
import { useMemo, useRef, useState } from "react";
import { Vector2, type ShaderMaterial } from "three";
import { StaticGradient } from "./StaticGradient";

const vertexShader = /* glsl */ `
  varying vec2 vUv;
  void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }
`;

const fragmentShader = /* glsl */ `
  uniform float uTime;
  uniform vec2 uRes;
  varying vec2 vUv;
  float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
  float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), u.x),
               mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x), u.y);
  }
  float fbm(vec2 p) {
    float v = 0.0, a = 0.5;
    for (int i = 0; i < 5; i++) { v += a * noise(p); p *= 2.0; a *= 0.5; }
    return v;
  }
  void main() {
    vec2 uv = vUv;
    uv.x *= uRes.x / max(uRes.y, 1.0);
    float t = uTime * 0.05;
    float n = fbm(uv * 2.0 + vec2(t, -t));
    float n2 = fbm(uv * 3.0 - vec2(t * 1.3, t * 0.7) + n);
    vec3 ink = vec3(0.027, 0.024, 0.051);
    vec3 violet = vec3(0.545, 0.361, 0.965);
    vec3 cyan = vec3(0.133, 0.827, 0.933);
    vec3 col = mix(ink, violet, smoothstep(0.45, 0.9, n2) * 0.55);
    col = mix(col, cyan, smoothstep(0.6, 1.0, n) * 0.35);
    col *= smoothstep(1.2, 0.2, length(vUv - 0.5) * 1.6);
    gl_FragColor = vec4(col, 1.0);
  }
`;

function NebulaPlane() {
  const material = useRef<ShaderMaterial>(null);
  const size = useThree((s) => s.size);
  const uniforms = useMemo(() => ({ uTime: { value: 0 }, uRes: { value: new Vector2(1, 1) } }), []);
  useFrame((_, delta) => {
    if (!material.current) return;
    material.current.uniforms.uTime.value += delta;
    material.current.uniforms.uRes.value.set(size.width, size.height);
  });
  return (
    <mesh>
      <planeGeometry args={[2, 2]} />
      <shaderMaterial ref={material} vertexShader={vertexShader} fragmentShader={fragmentShader} uniforms={uniforms} depthWrite={false} />
    </mesh>
  );
}

function canUseWebGL(): boolean {
  try {
    const canvas = document.createElement("canvas");
    return !!(canvas.getContext("webgl2") || canvas.getContext("webgl"));
  } catch {
    return false;
  }
}

export default function ShaderBackground() {
  const reduced = useReducedMotion();
  const [supported] = useState(canUseWebGL);
  if (reduced || !supported) return <StaticGradient />;
  return (
    <div aria-hidden="true" className="absolute inset-0 opacity-90 [html[data-theme=light]_&]:opacity-25">
      <Canvas dpr={[1, 1.5]} gl={{ antialias: false, powerPreference: "low-power" }}>
        <NebulaPlane />
      </Canvas>
    </div>
  );
}
```

- [ ] **Step 5: Implement the home components**

`frontend/src/features/home/HeroHeadline.tsx`:
```tsx
import { useGSAP } from "@gsap/react";
import { gsap } from "gsap";
import { SplitText } from "gsap/SplitText";
import { useRef } from "react";

gsap.registerPlugin(SplitText, useGSAP);

export function HeroHeadline() {
  const ref = useRef<HTMLHeadingElement>(null);

  useGSAP(
    () => {
      if (!ref.current || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
      const split = SplitText.create(ref.current.querySelector("[data-split]"), { type: "chars", mask: "chars" });
      gsap.from(split.chars, { yPercent: 110, duration: 0.9, ease: "expo.out", stagger: 0.02 });
      gsap.from(ref.current.querySelector("[data-glow]"), {
        y: 24, opacity: 0, filter: "blur(12px)", duration: 1.1, ease: "expo.out", delay: 0.35,
      });
      return () => split.revert();
    },
    { scope: ref },
  );

  return (
    <h1 ref={ref} className="font-display text-5xl font-semibold leading-[1.02] tracking-tight text-balance sm:text-7xl">
      <span data-split className="block">Long videos in.</span>
      <span data-glow className="block text-gradient">Viral shorts out.</span>
    </h1>
  );
}
```

`frontend/src/features/home/HeroInput.tsx`:
```tsx
import clsx from "clsx";
import { ArrowRight, Link2, LoaderCircle } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState, type FormEvent } from "react";
import { MagneticButton } from "../../components/MagneticButton";
import { normalizeSourceUrl } from "../../lib/url";

interface Props {
  onSubmit: (url: string) => void;
  pending: boolean;
  serverError: string | null;
  className?: string;
}

export function HeroInput({ onSubmit, pending, serverError, className }: Props) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const shown = error ?? serverError;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const url = normalizeSourceUrl(value);
    if (!url) {
      setError("That doesn't look like a video link. Try https://youtube.com/watch?v=…");
      return;
    }
    setError(null);
    onSubmit(url);
  };

  return (
    <form onSubmit={submit} noValidate className={clsx("mx-auto w-full max-w-2xl", className)}>
      <div className="rounded-2xl bg-[linear-gradient(120deg,var(--color-violet-brand),var(--color-indigo-brand),var(--color-cyan-brand))] p-px shadow-[0_0_60px_-15px_var(--color-violet-brand)] transition-shadow focus-within:shadow-[0_0_90px_-10px_var(--color-violet-brand)]">
        <div className="flex items-center gap-2 rounded-[15px] bg-bg/90 p-2 pl-4 backdrop-blur-xl">
          <Link2 className="size-5 shrink-0 text-muted" aria-hidden="true" />
          <label htmlFor="source-url" className="sr-only">Video link</label>
          <input
            id="source-url"
            value={value}
            onChange={(e) => {
              setValue(e.target.value);
              setError(null);
            }}
            placeholder="Paste a YouTube link…"
            autoComplete="off"
            inputMode="url"
            aria-invalid={!!shown}
            aria-describedby={shown ? "source-url-error" : undefined}
            className="min-w-0 flex-1 bg-transparent py-3 text-base outline-none placeholder:text-muted"
          />
          <MagneticButton
            type="submit"
            disabled={pending}
            aria-label={pending ? "Forging…" : "Forge clips"}
            className="inline-flex shrink-0 items-center gap-2 rounded-xl bg-fg px-5 py-3 text-sm font-semibold text-bg disabled:opacity-60"
          >
            {pending ? <LoaderCircle className="size-4 animate-spin" /> : <>Forge clips <ArrowRight className="size-4" /></>}
          </MagneticButton>
        </div>
      </div>
      <AnimatePresence>
        {shown && (
          <motion.p
            id="source-url-error"
            role="alert"
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="mt-3 text-sm text-red-400"
          >
            {shown}
          </motion.p>
        )}
      </AnimatePresence>
    </form>
  );
}
```

`frontend/src/features/home/DropZone.tsx`:
```tsx
import clsx from "clsx";
import { Upload } from "lucide-react";
import { motion } from "motion/react";
import { useRef, useState, type DragEvent } from "react";
import { api } from "../../lib/api";
import { fileExtension } from "../../lib/format";
import type { Project } from "../../lib/types";
import { UPLOAD_EXTENSIONS } from "../../lib/url";

export function DropZone({ onUploaded, className }: { onUploaded: (p: Project) => void; className?: string }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleFile = async (file: File) => {
    if (!UPLOAD_EXTENSIONS.includes(fileExtension(file.name))) {
      setError(`Unsupported file type. Use ${UPLOAD_EXTENSIONS.join(", ")}.`);
      return;
    }
    setError(null);
    setProgress(0);
    try {
      onUploaded(await api.upload(file, setProgress));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
      setProgress(null);
    }
  };

  const onDrag = (e: DragEvent, over: boolean) => {
    e.preventDefault();
    setDragging(over);
  };

  return (
    <div className={className}>
      <motion.div animate={{ scale: dragging ? 1.02 : 1 }} transition={{ type: "spring", stiffness: 300, damping: 22 }}>
        <button
          type="button"
          disabled={progress !== null}
          onClick={() => inputRef.current?.click()}
          onDragEnter={(e) => onDrag(e, true)}
          onDragOver={(e) => onDrag(e, true)}
          onDragLeave={(e) => onDrag(e, false)}
          onDrop={(e) => {
            onDrag(e, false);
            const file = e.dataTransfer.files[0];
            if (file) void handleFile(file);
          }}
          className={clsx(
            "relative flex w-full flex-col items-center gap-3 overflow-hidden rounded-2xl border border-dashed px-6 py-10 transition",
            dragging
              ? "border-cyan-brand bg-cyan-brand/10 shadow-[0_0_60px_-20px_var(--color-cyan-brand)]"
              : "border-border bg-surface hover:border-violet-brand/60 hover:bg-surface-2",
          )}
        >
          <span className="grid size-12 place-items-center rounded-xl bg-surface-2">
            <Upload className="size-5" aria-hidden="true" />
          </span>
          <span className="text-sm font-medium">
            {progress === null ? "Drop a video file or click to browse" : `Uploading… ${Math.round(progress * 100)}%`}
          </span>
          <span className="text-xs text-muted">MP4, MKV, MOV, WebM · any length</span>
          {progress !== null && (
            <motion.span
              className="absolute inset-x-0 bottom-0 h-1 origin-left bg-gradient-to-r from-violet-brand to-cyan-brand"
              animate={{ scaleX: progress }}
            />
          )}
        </button>
      </motion.div>
      <input
        ref={inputRef}
        type="file"
        accept={`${UPLOAD_EXTENSIONS.join(",")},video/*`}
        className="sr-only"
        data-testid="file-input"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) void handleFile(file);
          e.target.value = "";
        }}
      />
      {error && <p role="alert" className="mt-3 text-sm text-red-400">{error}</p>}
    </div>
  );
}
```

`frontend/src/features/home/RecentProjects.tsx`:
```tsx
import { useQuery } from "@tanstack/react-query";
import { motion } from "motion/react";
import { Link } from "react-router";
import { Skeleton } from "../../components/Skeleton";
import { StatusChip } from "../../components/StatusChip";
import { api } from "../../lib/api";
import { formatDuration, formatRelative, projectTitle } from "../../lib/format";

export function RecentProjects() {
  const { data, isLoading } = useQuery({ queryKey: ["projects"], queryFn: api.listProjects });

  if (isLoading) {
    return (
      <section className="mx-auto grid max-w-6xl gap-4 px-4 pb-24 sm:grid-cols-2 sm:px-6 lg:grid-cols-3">
        {[0, 1, 2].map((i) => <Skeleton key={i} className="h-28 rounded-2xl" />)}
      </section>
    );
  }
  if (!data?.length) return null;

  return (
    <section className="mx-auto max-w-6xl px-4 pb-24 sm:px-6">
      <h2 className="mb-6 font-display text-2xl font-semibold tracking-tight">Recent projects</h2>
      <motion.ul
        initial="hidden"
        animate="show"
        variants={{ show: { transition: { staggerChildren: 0.06 } } }}
        className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
      >
        {data.slice(0, 9).map((project) => (
          <motion.li key={project.id} variants={{ hidden: { opacity: 0, y: 16 }, show: { opacity: 1, y: 0 } }}>
            <Link
              to={`/projects/${project.id}`}
              className="group block h-full rounded-2xl border border-border bg-surface p-5 transition hover:-translate-y-0.5 hover:border-violet-brand/50 hover:bg-surface-2"
            >
              <div className="flex items-start justify-between gap-3">
                <span className="line-clamp-2 font-medium">{projectTitle(project)}</span>
                {project.latest_job && <StatusChip status={project.latest_job.status} />}
              </div>
              <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
                <span>{project.source_type === "url" ? "Link" : "Upload"}</span>
                {project.duration_s != null && <span>{formatDuration(project.duration_s)}</span>}
                <span>{formatRelative(project.created_at)}</span>
              </div>
            </Link>
          </motion.li>
        ))}
      </motion.ul>
    </section>
  );
}
```

Replace `frontend/src/features/home/HomePage.tsx`:
```tsx
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { motion } from "motion/react";
import { lazy, Suspense } from "react";
import { useNavigate } from "react-router";
import { PageTransition } from "../../components/PageTransition";
import { StaticGradient } from "../../components/StaticGradient";
import { api } from "../../lib/api";
import type { Project } from "../../lib/types";
import { DropZone } from "./DropZone";
import { HeroHeadline } from "./HeroHeadline";
import { HeroInput } from "./HeroInput";
import { RecentProjects } from "./RecentProjects";

const ShaderBackground = lazy(() => import("../../components/ShaderBackground"));

export default function HomePage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const open = (project: Project) => {
    void queryClient.invalidateQueries({ queryKey: ["projects"] });
    navigate(`/projects/${project.id}`);
  };
  const create = useMutation({ mutationFn: (url: string) => api.createFromUrl(url), onSuccess: open });

  return (
    <PageTransition>
      <section className="relative isolate overflow-hidden">
        <div className="absolute inset-0 -z-10">
          <Suspense fallback={<StaticGradient />}>
            <ShaderBackground />
          </Suspense>
          <div className="absolute inset-0 bg-gradient-to-b from-transparent via-bg/30 to-bg" />
        </div>
        <div className="mx-auto flex max-w-4xl flex-col items-center px-4 pb-20 pt-20 text-center sm:px-6 sm:pt-28">
          <motion.span
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className="mb-6 inline-flex items-center gap-2 rounded-full border border-border bg-surface px-4 py-1.5 text-xs text-muted backdrop-blur"
          >
            <Sparkles className="size-3.5 text-violet-brand" aria-hidden="true" />
            AI clip studio · runs on your GPU
          </motion.span>
          <HeroHeadline />
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.5 }}
            className="mt-6 max-w-xl text-balance text-base text-muted sm:text-lg"
          >
            Paste a YouTube link or drop a video. ClipForge transcribes it, finds the moments worth sharing and
            cuts them into captioned vertical shorts.
          </motion.p>
          <HeroInput
            className="mt-10"
            pending={create.isPending}
            serverError={create.error?.message ?? null}
            onSubmit={(url) => create.mutate(url)}
          />
          <div className="my-6 flex w-full max-w-2xl items-center gap-4 text-xs uppercase tracking-[0.2em] text-muted">
            <span className="h-px flex-1 bg-border" />or<span className="h-px flex-1 bg-border" />
          </div>
          <DropZone className="w-full max-w-2xl" onUploaded={open} />
        </div>
      </section>
      <RecentProjects />
    </PageTransition>
  );
}
```

- [ ] **Step 6: Run tests and build**

Run: `npx vitest run` → Expected: all passed.
Run: `npm run build` → Expected: no type errors; `ShaderBackground` emitted as its own chunk.

- [ ] **Step 7: Commit**

```bash
git add frontend
git commit -m "feat(frontend): add animated home screen with link input, drop zone and recent projects"
```

---

### Task 14: Processing screen (live pipeline, transcript stream, errors)

**Files:**
- Create: `frontend/src/features/processing/jobEvents.ts`, `frontend/src/lib/progress.ts`, `frontend/src/lib/useNow.ts`, `frontend/src/features/processing/useJobEvents.ts`, `frontend/src/features/processing/{PipelineConstellation,TranscriptStream,ErrorPanel}.tsx`, `frontend/src/features/processing/jobEvents.test.ts`, `frontend/src/lib/progress.test.ts`, `frontend/src/features/processing/ProcessingPage.test.tsx`
- Modify: `frontend/src/features/processing/ProcessingPage.tsx` (full replacement)

**Interfaces:**
- Consumes: Task 12 `api`, `jobEventsUrl`, types, components; Task 13 `formatTimestamp`, `projectTitle`; backend event conventions (Task 5 table).
- Produces: `StageState {status, progress, message}`; `JobViewState {jobStatus, stages, transcript, logs, error, hint, language}`; `initialJobViewState`; `JobAction = JobEvent | {type: "reset"}`; `jobEventsReducer(state, action)`; `useJobEvents(jobId?) -> JobViewState`; `stageFraction(s?)`, `overallProgress(stages, view)`, `estimateEta(startedAtMs, nowMs, progress)`, `formatEta(seconds | null)`; `useNow(intervalMs)`.

- [ ] **Step 1: Write the failing tests**

`frontend/src/features/processing/jobEvents.test.ts`:
```ts
import { describe, expect, it } from "vitest";
import type { JobEvent } from "../../lib/types";
import { initialJobViewState, jobEventsReducer, type JobAction } from "./jobEvents";

const ev = (e: Partial<JobEvent>): JobEvent => ({
  job_id: "j1", type: "log", stage: null, status: null, progress: null, message: null, data: null, ts: 0, ...e,
});

const reduce = (...actions: JobAction[]) => actions.reduce(jobEventsReducer, initialJobViewState);

describe("jobEventsReducer", () => {
  it("tracks stage lifecycle and progress", () => {
    const s = reduce(
      ev({ type: "stage", stage: "ingest", status: "running", progress: 0 }),
      ev({ type: "progress", stage: "ingest", progress: 0.4, message: "Downloading… 40%" }),
    );
    expect(s.stages.ingest).toEqual({ status: "running", progress: 0.4, message: "Downloading… 40%" });
    const done = jobEventsReducer(s, ev({ type: "stage", stage: "ingest", status: "done", progress: 1 }));
    expect(done.stages.ingest.status).toBe("done");
    expect(done.stages.ingest.progress).toBe(1);
  });

  it("appends transcript segments and language", () => {
    const s = reduce(
      ev({ type: "partial", stage: "transcribe", data: { kind: "segment", start: 0, end: 1, text: "Hello." } }),
      ev({ type: "partial", stage: "transcribe", data: { kind: "segment", start: 1, end: 2, text: "Bye." } }),
      ev({ type: "partial", stage: "transcribe", data: { kind: "language", language: "hi" } }),
    );
    expect(s.transcript.map((l) => l.text)).toEqual(["Hello.", "Bye."]);
    expect(s.language).toBe("hi");
  });

  it("records job outcome with hint", () => {
    const s = reduce(ev({ type: "job", status: "failed", message: "YouTube blocked the download.", data: { hint: "Update yt-dlp" } }));
    expect(s.jobStatus).toBe("failed");
    expect(s.error).toBe("YouTube blocked the download.");
    expect(s.hint).toBe("Update yt-dlp");
  });

  it("keeps unique log notices", () => {
    const s = reduce(ev({ type: "log", message: "No speech" }), ev({ type: "log", message: "No speech" }));
    expect(s.logs).toEqual(["No speech"]);
  });

  it("resets on reconnect so replayed history doesn't duplicate", () => {
    const s = reduce(
      ev({ type: "partial", data: { kind: "segment", start: 0, end: 1, text: "Hi." } }),
      { type: "reset" },
      ev({ type: "partial", data: { kind: "segment", start: 0, end: 1, text: "Hi." } }),
    );
    expect(s.transcript).toHaveLength(1);
  });
});
```

`frontend/src/lib/progress.test.ts`:
```ts
import { describe, expect, it } from "vitest";
import { initialJobViewState } from "../features/processing/jobEvents";
import { estimateEta, formatEta, overallProgress } from "./progress";

const stages = [
  { name: "ingest", label: "Importing video", weight: 1 },
  { name: "transcribe", label: "Transcribing speech", weight: 3 },
];

describe("progress", () => {
  it("weights stage progress", () => {
    const view = {
      ...initialJobViewState,
      stages: {
        ingest: { status: "cached" as const, progress: 1, message: null },
        transcribe: { status: "running" as const, progress: 0.5, message: null },
      },
    };
    expect(overallProgress(stages, view)).toBeCloseTo(0.625);
  });

  it("is complete when the job succeeded", () => {
    expect(overallProgress(stages, { ...initialJobViewState, jobStatus: "succeeded" })).toBe(1);
  });

  it("estimates time left", () => {
    expect(estimateEta(0, 10_000, 0.5)).toBe(10);
    expect(estimateEta(0, 10_000, 0.01)).toBeNull();
    expect(estimateEta(0, 10_000, 1)).toBeNull();
  });

  it("formats eta", () => {
    expect(formatEta(null)).toBe("Estimating time left…");
    expect(formatEta(42)).toBe("~42s left");
    expect(formatEta(200)).toBe("~4 min left");
  });
});
```

`frontend/src/features/processing/ProcessingPage.test.tsx`:
```tsx
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { makeJob, makeProject } from "../../test/fixtures";
import { renderWithProviders } from "../../test/utils";
import { initialJobViewState } from "./jobEvents";
import ProcessingPage from "./ProcessingPage";
import { useJobEvents } from "./useJobEvents";

vi.mock("../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api")>();
  return {
    ...actual,
    api: { ...actual.api, getProject: vi.fn(), stages: vi.fn(), transcript: vi.fn(), retry: vi.fn(), cancelJob: vi.fn() },
  };
});
vi.mock("./useJobEvents", () => ({ useJobEvents: vi.fn() }));

const route = { route: "/projects/p1", path: "/projects/:projectId" };

beforeEach(() => {
  vi.mocked(api.stages).mockResolvedValue([
    { name: "ingest", label: "Importing video", weight: 1 },
    { name: "transcribe", label: "Transcribing speech", weight: 3 },
  ]);
});

it("shows live stages, overall progress and the streamed transcript", async () => {
  vi.mocked(api.getProject).mockResolvedValue(
    makeProject({ title: "My Talk", latest_job: makeJob({ status: "running" }) }),
  );
  vi.mocked(useJobEvents).mockReturnValue({
    ...initialJobViewState,
    jobStatus: "running",
    language: "en",
    stages: {
      ingest: { status: "done", progress: 1, message: null },
      transcribe: { status: "running", progress: 0.5, message: null },
    },
    transcript: [{ start: 0, end: 1, text: "Hello world." }],
  });
  renderWithProviders(<ProcessingPage />, route);

  expect(await screen.findByText("My Talk")).toBeInTheDocument();
  expect(await screen.findByText("Hello world.")).toBeInTheDocument();
  expect(screen.getByText("Importing video").closest("li")).toHaveAttribute("data-status", "done");
  expect(screen.getByText("Transcribing speech").closest("li")).toHaveAttribute("data-status", "running");
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "63");
  expect(screen.getByRole("button", { name: /cancel/i })).toBeInTheDocument();
});

it("explains failures and retries", async () => {
  vi.mocked(api.getProject).mockResolvedValue(makeProject({ latest_job: makeJob({ status: "failed" }) }));
  vi.mocked(api.retry).mockResolvedValue(makeProject({ latest_job: makeJob({ id: "j2", status: "queued" }) }));
  vi.mocked(useJobEvents).mockReturnValue({
    ...initialJobViewState,
    jobStatus: "failed",
    error: "YouTube blocked the download.",
    hint: "Update yt-dlp, then press Retry.",
    stages: { ingest: { status: "failed", progress: 0.2, message: "YouTube blocked the download." } },
  });
  renderWithProviders(<ProcessingPage />, route);

  expect(await screen.findByText("Update yt-dlp, then press Retry.")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /retry/i }));
  expect(api.retry).toHaveBeenCalledWith("p1");
});

it("shows a friendly message for unknown projects", async () => {
  vi.mocked(api.getProject).mockRejectedValue(new Error("Project not found"));
  vi.mocked(useJobEvents).mockReturnValue(initialJobViewState);
  renderWithProviders(<ProcessingPage />, route);
  expect(await screen.findByText(/couldn't find this project/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/features/processing src/lib/progress.test.ts`
Expected: FAIL — cannot resolve `./jobEvents`, `./progress`, `./useJobEvents`.

- [ ] **Step 3: Implement state logic**

`frontend/src/features/processing/jobEvents.ts`:
```ts
import type { JobEvent, JobStatus, StageStatus, TranscriptLine } from "../../lib/types";

export interface StageState {
  status: StageStatus;
  progress: number;
  message: string | null;
}

export interface JobViewState {
  jobStatus: JobStatus | null;
  stages: Record<string, StageState>;
  transcript: TranscriptLine[];
  logs: string[];
  error: string | null;
  hint: string | null;
  language: string | null;
}

export const initialJobViewState: JobViewState = {
  jobStatus: null, stages: {}, transcript: [], logs: [], error: null, hint: null, language: null,
};

export type JobAction = JobEvent | { type: "reset" };

export function jobEventsReducer(state: JobViewState, action: JobAction): JobViewState {
  if (action.type === "reset") return initialJobViewState;
  const event = action;
  switch (event.type) {
    case "stage": {
      if (!event.stage) return state;
      const prev = state.stages[event.stage];
      return {
        ...state,
        stages: {
          ...state.stages,
          [event.stage]: {
            status: (event.status as StageStatus) ?? prev?.status ?? "running",
            progress: event.progress ?? prev?.progress ?? 0,
            message: event.message ?? (event.status === "running" ? null : prev?.message ?? null),
          },
        },
      };
    }
    case "progress": {
      if (!event.stage) return state;
      const prev = state.stages[event.stage];
      return {
        ...state,
        stages: {
          ...state.stages,
          [event.stage]: { status: "running", progress: event.progress ?? prev?.progress ?? 0, message: event.message ?? prev?.message ?? null },
        },
      };
    }
    case "partial": {
      const data = event.data ?? {};
      if (data.kind === "segment") {
        const line: TranscriptLine = { start: Number(data.start), end: Number(data.end), text: String(data.text) };
        return { ...state, transcript: [...state.transcript, line] };
      }
      if (data.kind === "language") return { ...state, language: String(data.language) };
      return state;
    }
    case "log":
      return event.message && !state.logs.includes(event.message)
        ? { ...state, logs: [...state.logs, event.message].slice(-20) }
        : state;
    case "job":
      return {
        ...state,
        jobStatus: event.status as JobStatus,
        error: event.status === "failed" ? event.message : null,
        hint: event.status === "failed" ? ((event.data?.hint as string | undefined) ?? null) : null,
      };
    default:
      return state;
  }
}
```

`frontend/src/lib/progress.ts`:
```ts
import type { JobViewState, StageState } from "../features/processing/jobEvents";
import type { StageInfo } from "./types";

export function stageFraction(stage?: StageState): number {
  if (!stage) return 0;
  if (stage.status === "done" || stage.status === "cached") return 1;
  if (stage.status === "pending") return 0;
  return stage.progress;
}

export function overallProgress(stages: StageInfo[], view: JobViewState): number {
  if (view.jobStatus === "succeeded") return 1;
  const total = stages.reduce((sum, s) => sum + s.weight, 0);
  if (!total) return 0;
  return stages.reduce((sum, s) => sum + s.weight * stageFraction(view.stages[s.name]), 0) / total;
}

export function estimateEta(startedAtMs: number, nowMs: number, progress: number): number | null {
  if (progress < 0.03 || progress >= 1) return null;
  const elapsed = (nowMs - startedAtMs) / 1000;
  if (elapsed <= 0) return null;
  return Math.round((elapsed * (1 - progress)) / progress);
}

export function formatEta(seconds: number | null): string {
  if (seconds == null) return "Estimating time left…";
  if (seconds < 60) return `~${seconds}s left`;
  return `~${Math.round(seconds / 60)} min left`;
}
```

`frontend/src/lib/useNow.ts`:
```ts
import { useEffect, useState } from "react";

export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}
```

`frontend/src/features/processing/useJobEvents.ts`:
```ts
import { useEffect, useReducer } from "react";
import { jobEventsUrl } from "../../lib/api";
import type { JobEvent } from "../../lib/types";
import { initialJobViewState, jobEventsReducer, type JobViewState } from "./jobEvents";

/** Live job state from the WebSocket. The server replays history on connect, so we reset first. */
export function useJobEvents(jobId: string | undefined): JobViewState {
  const [state, dispatch] = useReducer(jobEventsReducer, initialJobViewState);

  useEffect(() => {
    if (!jobId) return;
    let socket: WebSocket | null = null;
    let closed = false;
    let attempt = 0;
    let timer: number | undefined;

    const connect = () => {
      socket = new WebSocket(jobEventsUrl(jobId));
      socket.onopen = () => {
        attempt = 0;
        dispatch({ type: "reset" });
      };
      socket.onmessage = (message) => dispatch(JSON.parse(message.data) as JobEvent);
      socket.onclose = () => {
        if (closed) return;
        timer = window.setTimeout(connect, Math.min(1000 * 2 ** attempt++, 10_000));
      };
    };

    connect();
    return () => {
      closed = true;
      window.clearTimeout(timer);
      socket?.close();
    };
  }, [jobId]);

  return state;
}
```

- [ ] **Step 4: Implement the UI pieces**

`frontend/src/features/processing/PipelineConstellation.tsx`:
```tsx
import clsx from "clsx";
import { AudioLines, Check, Download, Sparkles, X, type LucideIcon } from "lucide-react";
import { motion } from "motion/react";
import { stageFraction } from "../../lib/progress";
import type { StageInfo, StageStatus } from "../../lib/types";
import type { StageState } from "./jobEvents";

const ICONS: Record<string, LucideIcon> = { ingest: Download, transcribe: AudioLines };
const STATUS_TEXT: Record<StageStatus, string> = {
  pending: "Waiting", running: "In progress", done: "Done", cached: "Reused from cache",
  failed: "Failed", cancelled: "Cancelled",
};
const RADIUS = 24;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

function StageNode({ status, progress, Icon }: { status: StageStatus; progress: number; Icon: LucideIcon }) {
  const complete = status === "done" || status === "cached";
  return (
    <div className="relative grid size-14 shrink-0 place-items-center">
      {status === "running" && (
        <motion.span
          className="absolute inset-0 rounded-full bg-violet-brand/30"
          animate={{ scale: [1, 1.45], opacity: [0.6, 0] }}
          transition={{ duration: 1.6, repeat: Infinity, ease: "easeOut" }}
        />
      )}
      <svg viewBox="0 0 56 56" className="absolute inset-0 -rotate-90" aria-hidden="true">
        <circle cx="28" cy="28" r={RADIUS} fill="none" stroke="var(--border)" strokeWidth="3" />
        <motion.circle
          cx="28" cy="28" r={RADIUS} fill="none" stroke="url(#stage-gradient)" strokeWidth="3" strokeLinecap="round"
          strokeDasharray={CIRCUMFERENCE}
          animate={{ strokeDashoffset: CIRCUMFERENCE * (1 - (complete ? 1 : status === "running" ? progress : 0)) }}
          transition={{ type: "spring", stiffness: 80, damping: 20 }}
        />
        <defs>
          <linearGradient id="stage-gradient" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#8b5cf6" />
            <stop offset="1" stopColor="#22d3ee" />
          </linearGradient>
        </defs>
      </svg>
      <span
        className={clsx(
          "relative grid size-10 place-items-center rounded-full transition-colors",
          complete && "bg-gradient-to-br from-violet-brand to-cyan-brand text-white",
          status === "failed" && "bg-red-500/20 text-red-400",
          !complete && status !== "failed" && "bg-surface-2",
        )}
      >
        {complete ? <Check className="size-5" /> : status === "failed" ? <X className="size-5" /> : <Icon className="size-5" />}
      </span>
    </div>
  );
}

export function PipelineConstellation({ stages, state }: { stages: StageInfo[]; state: Record<string, StageState> }) {
  return (
    <ol aria-label="Processing steps" className="mt-10 grid gap-4 sm:auto-cols-fr sm:grid-flow-col">
      {stages.map((stage, index) => {
        const current = state[stage.name];
        const status = current?.status ?? "pending";
        const previousDone = index > 0 && stageFraction(state[stages[index - 1].name]) === 1;
        return (
          <motion.li
            key={stage.name}
            data-status={status}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.08 }}
            className={clsx(
              "relative flex items-center gap-4 rounded-2xl border bg-surface p-4 sm:flex-col sm:items-start",
              status === "running" ? "border-violet-brand/50 shadow-[0_0_40px_-20px_var(--color-violet-brand)]" : "border-border",
            )}
          >
            {index > 0 && (
              <span aria-hidden="true" className="absolute -left-4 top-1/2 hidden h-0.5 w-4 bg-border sm:block">
                <motion.span
                  className="block h-full origin-left bg-gradient-to-r from-violet-brand to-cyan-brand"
                  animate={{ scaleX: previousDone ? 1 : 0 }}
                />
              </span>
            )}
            <StageNode status={status} progress={current?.progress ?? 0} Icon={ICONS[stage.name] ?? Sparkles} />
            <div className="min-w-0">
              <p className="font-medium">{stage.label}</p>
              <p className="truncate text-xs text-muted" aria-live="polite">{current?.message ?? STATUS_TEXT[status]}</p>
            </div>
          </motion.li>
        );
      })}
    </ol>
  );
}
```

`frontend/src/features/processing/TranscriptStream.tsx`:
```tsx
import { motion } from "motion/react";
import { useEffect, useRef } from "react";
import { Skeleton } from "../../components/Skeleton";
import { formatTimestamp } from "../../lib/format";
import type { TranscriptLine } from "../../lib/types";

interface Props {
  lines: TranscriptLine[];
  language: string | null;
  live: boolean;
  logs: string[];
}

export function TranscriptStream({ lines, language, live, logs }: Props) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (live) endRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [lines.length, live]);

  return (
    <section className="mt-10 rounded-3xl border border-border bg-surface p-5 sm:p-6">
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2 className="font-display text-xl font-semibold">Transcript</h2>
        <div className="flex items-center gap-2 text-xs text-muted">
          {language && <span className="rounded-full bg-surface-2 px-3 py-1 uppercase tracking-wider">{language}</span>}
          {lines.length > 0 && <span>{lines.length} segments</span>}
        </div>
      </div>
      {logs.map((log) => (
        <p key={log} className="mb-3 rounded-xl bg-gold/10 px-4 py-2 text-sm text-gold">{log}</p>
      ))}
      {lines.length === 0 ? (
        live ? (
          <div className="space-y-3" aria-label="Listening">
            {[80, 65, 90].map((w) => <Skeleton key={w} className="h-4" />)}
            <p className="pt-2 text-sm text-muted">Listening…</p>
          </div>
        ) : (
          <p className="text-sm text-muted">The transcript will appear here as speech is recognised.</p>
        )
      ) : (
        <div className="max-h-[28rem] overflow-y-auto pr-2" data-lenis-prevent>
          <ul className="space-y-2">
            {lines.map((line, i) => (
              <motion.li
                key={`${line.start}-${i}`}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                className="flex gap-4 text-sm leading-relaxed"
              >
                <span className="w-12 shrink-0 pt-0.5 font-mono text-xs tabular-nums text-muted">{formatTimestamp(line.start)}</span>
                <span>{line.text}</span>
              </motion.li>
            ))}
          </ul>
          <div ref={endRef} />
        </div>
      )}
    </section>
  );
}
```

`frontend/src/features/processing/ErrorPanel.tsx`:
```tsx
import { LoaderCircle, RotateCcw, TriangleAlert } from "lucide-react";
import { motion } from "motion/react";

interface Props {
  title: string;
  message: string | null;
  hint: string | null;
  onRetry: () => void;
  pending: boolean;
}

export function ErrorPanel({ title, message, hint, onRetry, pending }: Props) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.98 }}
      animate={{ opacity: 1, scale: 1 }}
      className="mt-8 flex flex-col gap-4 rounded-2xl border border-red-500/30 bg-red-500/5 p-5 sm:flex-row sm:items-center sm:justify-between"
    >
      <div className="flex gap-3">
        <TriangleAlert className="mt-0.5 size-5 shrink-0 text-red-400" aria-hidden="true" />
        <div>
          <p className="font-medium">{title}</p>
          {message && <p className="mt-1 text-sm text-muted">{message}</p>}
          {hint && <p className="mt-2 text-sm">{hint}</p>}
        </div>
      </div>
      <button
        type="button"
        onClick={onRetry}
        disabled={pending}
        className="inline-flex shrink-0 items-center justify-center gap-2 rounded-xl bg-fg px-4 py-2.5 text-sm font-semibold text-bg disabled:opacity-60"
      >
        {pending ? <LoaderCircle className="size-4 animate-spin" /> : <RotateCcw className="size-4" />}
        Retry
      </button>
    </motion.div>
  );
}
```

Replace `frontend/src/features/processing/ProcessingPage.tsx`:
```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion, useSpring, useTransform } from "motion/react";
import { useEffect, useRef } from "react";
import { useParams } from "react-router";
import { NotFound } from "../../components/NotFound";
import { PageTransition } from "../../components/PageTransition";
import { Skeleton } from "../../components/Skeleton";
import { StatusChip } from "../../components/StatusChip";
import { api } from "../../lib/api";
import { projectTitle } from "../../lib/format";
import { estimateEta, formatEta, overallProgress } from "../../lib/progress";
import { isTerminal, type JobStatus } from "../../lib/types";
import { useNow } from "../../lib/useNow";
import { ErrorPanel } from "./ErrorPanel";
import { PipelineConstellation } from "./PipelineConstellation";
import { TranscriptStream } from "./TranscriptStream";
import { useJobEvents } from "./useJobEvents";

function AnimatedPercent({ value }: { value: number }) {
  const spring = useSpring(value, { stiffness: 120, damping: 20 });
  const text = useTransform(spring, (v) => `${Math.round(v * 100)}%`);
  useEffect(() => spring.set(value), [spring, value]);
  return <motion.span>{text}</motion.span>;
}

export default function ProcessingPage() {
  const { projectId = "" } = useParams();
  const queryClient = useQueryClient();
  const projectQuery = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.getProject(projectId),
    refetchInterval: (q) => (isTerminal(q.state.data?.latest_job?.status) ? false : 4000),
  });
  const stagesQuery = useQuery({ queryKey: ["stages"], queryFn: api.stages, staleTime: Infinity });
  const job = projectQuery.data?.latest_job ?? null;
  const view = useJobEvents(job?.id);
  const status: JobStatus | undefined = view.jobStatus ?? job?.status;

  useEffect(() => {
    if (isTerminal(view.jobStatus)) {
      void queryClient.invalidateQueries({ queryKey: ["project", projectId] });
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    }
  }, [view.jobStatus, projectId, queryClient]);

  const transcriptQuery = useQuery({
    queryKey: ["transcript", projectId],
    queryFn: () => api.transcript(projectId),
    enabled: status === "succeeded",
  });
  const retry = useMutation({
    mutationFn: () => api.retry(projectId),
    onSuccess: (project) => queryClient.setQueryData(["project", projectId], project),
  });
  const cancel = useMutation({ mutationFn: (jobId: string) => api.cancelJob(jobId) });

  const now = useNow(1000);
  const startedAt = useRef<number | null>(null);
  if (status === "running" && startedAt.current === null) startedAt.current = now;
  if (status !== "running") startedAt.current = null;

  if (projectQuery.isError) return <NotFound message="We couldn't find this project." />;
  const project = projectQuery.data;
  if (!project) {
    return (
      <div className="mx-auto max-w-6xl space-y-4 px-4 py-14 sm:px-6">
        <Skeleton className="h-10 w-2/3" />
        <Skeleton className="h-28" />
      </div>
    );
  }

  const stages = stagesQuery.data ?? [];
  const progress = overallProgress(stages, view);
  const eta = startedAt.current !== null ? estimateEta(startedAt.current, now, progress) : null;
  const lines = view.transcript.length ? view.transcript : (transcriptQuery.data?.segments ?? []);
  const active = status === "running" || status === "queued";

  return (
    <PageTransition>
      <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6 sm:py-14">
        <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div className="min-w-0">
            <p className="text-xs uppercase tracking-[0.2em] text-muted">Project</p>
            <h1 className="mt-2 truncate font-display text-3xl font-semibold tracking-tight sm:text-4xl">{projectTitle(project)}</h1>
          </div>
          <div className="flex items-center gap-3">
            {status && <StatusChip status={status} />}
            {active && job && (
              <button
                type="button"
                onClick={() => cancel.mutate(job.id)}
                disabled={cancel.isPending}
                className="rounded-full border border-border px-4 py-1.5 text-sm text-muted transition hover:bg-surface-2 hover:text-fg"
              >
                Cancel
              </button>
            )}
          </div>
        </header>

        <div className="mt-8">
          <div className="flex items-end justify-between">
            <span className="font-display text-5xl font-semibold tabular-nums text-gradient">
              <AnimatedPercent value={progress} />
            </span>
            <span className="text-sm text-muted">
              {status === "succeeded" ? "Transcript ready" : active ? formatEta(eta) : ""}
            </span>
          </div>
          <div
            role="progressbar"
            aria-label="Overall progress"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(progress * 100)}
            className="mt-3 h-2 overflow-hidden rounded-full bg-surface-2"
          >
            <motion.div
              className="h-full origin-left rounded-full bg-gradient-to-r from-violet-brand via-indigo-brand to-cyan-brand"
              animate={{ scaleX: progress }}
              transition={{ type: "spring", stiffness: 60, damping: 18 }}
            />
          </div>
        </div>

        <PipelineConstellation stages={stages} state={view.stages} />

        {status === "failed" && (
          <ErrorPanel
            title="Something went wrong"
            message={view.error ?? job?.error ?? null}
            hint={view.hint ?? job?.error_hint ?? null}
            onRetry={() => retry.mutate()}
            pending={retry.isPending}
          />
        )}
        {status === "cancelled" && (
          <ErrorPanel title="Cancelled" message="This job was cancelled." hint={null} onRetry={() => retry.mutate()} pending={retry.isPending} />
        )}

        <TranscriptStream
          lines={lines}
          language={view.language ?? transcriptQuery.data?.language ?? null}
          live={status === "running"}
          logs={view.logs}
        />
      </div>
    </PageTransition>
  );
}
```

- [ ] **Step 5: Run tests and build**

Run: `npx vitest run` → Expected: all passed.
Run: `npm run build` → Expected: no type errors.

- [ ] **Step 6: Commit**

```bash
git add frontend
git commit -m "feat(frontend): add live processing screen with animated pipeline and transcript stream"
```

---

### Task 15: CLI, setup/dev scripts and end-to-end verification

**Files:**
- Create: `backend/app/cli.py`, `backend/tests/test_cli.py`, `scripts/setup.ps1`, `scripts/dev.ps1`, `.env.example`
- Modify: `README.md` (tick Phase 1 in the roadmap)

**Interfaces:**
- Consumes: `Settings`/`get_settings` (T1), `register_cuda_dlls`/`detect_gpus`/`ffmpeg_has_nvenc` (T2).
- Produces: `python -m app.cli doctor` (exit 0 when ffmpeg+ffprobe+node exist; prints GPU/NVENC/CUDA/model status) and `python -m app.cli download-models`; `main(argv: list[str] | None = None) -> int`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_cli.py`:
```python
from app import cli


def test_doctor_reports_every_check(capsys, monkeypatch, settings):
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    code = cli.main(["doctor"])
    out = capsys.readouterr().out
    assert code in (0, 1)
    for label in ("ffmpeg", "ffprobe", "node", "NVENC", "GPU", "CUDA for Whisper", "Whisper model"):
        assert label in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL — `ImportError: cannot import name 'cli' from 'app'`.

- [ ] **Step 3: Implement the CLI**

`backend/app/cli.py`:
```python
"""Developer utilities: `python -m app.cli doctor` and `python -m app.cli download-models`."""

import argparse
import shutil

from app.config import Settings, get_settings
from app.gpu import detect_gpus, ffmpeg_has_nvenc, register_cuda_dlls


def _line(ok: bool, label: str, detail: str) -> None:
    print(f"[{'ok' if ok else '!!'}] {label}: {detail}")


def _whisper_cache(settings: Settings) -> bool:
    cache = settings.models_dir / "whisper"
    return cache.exists() and any(cache.rglob("model.bin"))


def doctor(settings: Settings) -> int:
    critical_ok = True
    for tool in ("ffmpeg", "ffprobe", "node"):
        path = shutil.which(tool)
        _line(path is not None, tool, path or "not found on PATH")
        critical_ok &= path is not None
    _line(ffmpeg_has_nvenc(), "NVENC", "h264_nvenc available" if ffmpeg_has_nvenc() else "not available (CPU encoding will be used)")
    gpus = detect_gpus()
    _line(bool(gpus), "GPU", ", ".join(f"{g.name} ({g.memory_total_mb} MB)" for g in gpus) or "no NVIDIA GPU detected")
    try:
        import ctranslate2

        cuda_devices = ctranslate2.get_cuda_device_count()
    except Exception as exc:  # noqa: BLE001 — report any loader failure
        cuda_devices = 0
        _line(False, "CUDA for Whisper", f"ctranslate2 failed to load: {exc}")
    else:
        _line(cuda_devices > 0, "CUDA for Whisper", f"{cuda_devices} device(s)" if cuda_devices else "unavailable — Whisper will run on CPU")
    cached = _whisper_cache(settings)
    _line(cached, "Whisper model", f"{settings.whisper_model} cached" if cached else "not downloaded — run `python -m app.cli download-models`")
    return 0 if critical_ok else 1


def download_models(settings: Settings) -> int:
    from faster_whisper import download_model

    target = settings.models_dir / "whisper"
    print(f"Downloading Whisper '{settings.whisper_model}' into {target} …")
    path = download_model(settings.whisper_model, cache_dir=str(target))
    print(f"Whisper model ready at {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="clipforge")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="check ffmpeg, GPU, CUDA and models")
    sub.add_parser("download-models", help="download the Whisper model")
    args = parser.parse_args(argv)
    settings = get_settings()
    register_cuda_dlls()
    if args.command == "doctor":
        return doctor(settings)
    return download_models(settings)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -v`
Expected: all passed.

- [ ] **Step 5: Scripts and env template**

`.env.example`:
```dotenv
# Copy to .env (setup.ps1 does this for you). All settings are optional.
# CLIPFORGE_WORKSPACE_DIR=./workspace
# CLIPFORGE_MODELS_DIR=./models
# CLIPFORGE_WHISPER_MODEL=large-v3-turbo
# CLIPFORGE_WHISPER_DEVICE=auto          # auto | cuda | cpu
# CLIPFORGE_WHISPER_COMPUTE_TYPE=float16 # falls back to int8_float16, then CPU int8
# CLIPFORGE_MAX_DOWNLOAD_HEIGHT=1080
# CLIPFORGE_YTDLP_COOKIES_FILE=C:/path/to/cookies.txt   # for age-restricted / members-only videos
# CLIPFORGE_YTDLP_JS_RUNTIME=node
# CLIPFORGE_JOB_CONCURRENCY=2
```

`scripts/setup.ps1`:
```powershell
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Write-Host "ClipForge setup" -ForegroundColor Magenta
foreach ($cmd in "uv", "node", "npm", "ffmpeg", "ffprobe") {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        throw "Missing '$cmd'. Install it and re-run. (uv: https://docs.astral.sh/uv/ · FFmpeg 8 full build: winget install Gyan.FFmpeg)"
    }
}

Write-Host "`n> Backend dependencies" -ForegroundColor Cyan
Push-Location (Join-Path $root "backend")
try { uv sync; if ($LASTEXITCODE) { throw "uv sync failed" } } finally { Pop-Location }

Write-Host "`n> Frontend dependencies" -ForegroundColor Cyan
Push-Location (Join-Path $root "frontend")
try { npm install; if ($LASTEXITCODE) { throw "npm install failed" } } finally { Pop-Location }

$envFile = Join-Path $root ".env"
if (-not (Test-Path $envFile)) { Copy-Item (Join-Path $root ".env.example") $envFile }

Write-Host "`n> Whisper model (about 1.6 GB, first run only)" -ForegroundColor Cyan
Push-Location (Join-Path $root "backend")
try {
    uv run python -m app.cli download-models; if ($LASTEXITCODE) { throw "model download failed" }
    Write-Host "`n> Health check" -ForegroundColor Cyan
    uv run python -m app.cli doctor
} finally { Pop-Location }

Write-Host "`nDone. Start ClipForge with: ./scripts/dev.ps1" -ForegroundColor Green
```

`scripts/dev.ps1`:
```powershell
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"

Write-Host "Starting ClipForge API on http://127.0.0.1:8000 (new window)…" -ForegroundColor Cyan
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location -LiteralPath '$backend'; uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --reload --reload-dir app"
)

Write-Host "Starting UI on http://localhost:5173 …" -ForegroundColor Cyan
Set-Location -LiteralPath $frontend
npm run dev
```

- [ ] **Step 6: Full automated verification**

Run each and confirm:
1. `cd backend; uv run pytest -v` → all pass.
2. `cd backend; uv run python -m app.cli download-models` → prints `Whisper model ready at …`.
3. `cd backend; uv run python -m app.cli doctor` → `[ok]` for ffmpeg, ffprobe, node, NVENC, GPU, CUDA for Whisper, Whisper model.
4. `cd backend; uv run pytest -m gpu -v` → `test_real_model_runs_on_gpu PASSED` (proves cuBLAS/cuDNN DLLs load and Whisper runs on CUDA).
5. `cd backend; uv run pytest -m network -v` → `test_real_youtube_download PASSED` (if it fails on `js_runtimes`, apply the note in Task 8).
6. `cd frontend; npx vitest run; npm run build` → all pass, build succeeds.

- [ ] **Step 7: Manual end-to-end check (use the run skill or a browser)**

1. `./scripts/dev.ps1` → API window shows `Application startup complete`, UI at `http://localhost:5173`.
2. Home: shader background animates, headline reveals, theme toggle works, layout holds at 375 px width.
3. Paste a short public talk, e.g. `youtu.be/jNQXAC9IVRw` (no `https://`) → navigates to the project page; "Importing video" shows download %, then "Transcribing speech" progresses; transcript lines stream in; status becomes **Ready**; language chip shows `en`.
4. Reload the page mid-transcription → state is restored from the WebSocket replay (no duplicate lines).
5. Upload a local MP4 with a space/accent in its name → same flow succeeds.
6. Submit the same URL again → `Importing video` shows **Reused from cache** only after the download hashes to the same id; transcription shows **Reused from cache** and finishes in seconds.
7. Start a job, press **Cancel** → status **Cancelled**; press **Retry** → resumes and succeeds.
8. Stop the API while a job runs, restart it → the job shows **Failed** with "Press Retry…"; Retry completes it.
9. Paste `hello` → inline error, no request sent.

- [ ] **Step 8: Update the README roadmap and commit**

In `README.md`, change `- [ ] **Phase 1 — Foundation:**` to `- [x] **Phase 1 — Foundation:**`.

```bash
git add backend/app/cli.py backend/tests/test_cli.py scripts .env.example README.md
git commit -m "feat: add doctor/download-models CLI, setup and dev scripts; complete Phase 1"
git push
```

---

## Later phases (separate plans)

Each gets its own plan file once the previous phase ships, following spec §9: **Phase 2** clip engine (LLM provider layer, classify, diarize, analyze/score, shots, reframe, ASS captions, NVENC render, gallery) → **Phase 3** SEO pack → **Phase 4** editor → **Phase 5** polish → **Phase 6** translation, dubbing and performance.

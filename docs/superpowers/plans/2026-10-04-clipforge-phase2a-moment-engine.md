# ClipForge Phase 2A — Moment Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After transcription, ClipForge understands the video, tells speakers apart, and uses a pluggable AI provider (Claude / Gemini / OpenAI / Ollama) to find, align, score (0–100) and rank the most viral moments — shown live in an animated clip gallery, with a Settings screen for API keys and per-project clip options.

**Architecture:** Three new checkpointed stages run after Phase 1's `ingest → transcribe`: `classify` (LLM content profile, per video), `diarize` (pyannote on GPU, per video, optional), and `analyze` (per project: chunked LLM moment proposals → quote-to-word alignment → sentence snapping → audio-energy bonus → IoU dedupe → LLM rerank → virality score → `Clip` rows + thumbnails). An `LLMRouter` wraps provider adapters with schema-repair retries, provider fallback and an on-disk response cache. Keys live in a DB `Setting` row (masked over the API) with `.env` fallback.

**Tech Stack:** Python 3.13 / FastAPI / SQLModel (existing) + `anthropic`, `google-genai`, `openai`, `rapidfuzz`, `numpy`, `pyannote.audio` 4 with CUDA `torch` (cu126 index); React 19 / TanStack Query / Motion (existing).

**Spec:** `docs/superpowers/specs/2026-10-03-shorts-generator-design.md` — implements §3.3 Classify, §3.4 Diarize, §3.5 Analyze, §4 LLM provider layer, §5 API (clips, settings, options), §6 Settings screen, Home options, Clip gallery. Phase 2B (separate plan) covers §3.6 shots, §3.7 reframe, §3.8 captions, §3.10 render.
**Verified library APIs:** `docs/superpowers/research/2026-10-04-phase2-api-findings.md` — read the section for your task before coding; it holds the exact, tested call shapes.

## Global Constraints

- Builds on merged Phase 1 (`main`). Python `>=3.13,<3.14` via uv; backend commands from `backend/`, frontend from `frontend/`. Windows 11; repo path contains a space; subprocess calls use argument lists only.
- Every commit message ends with the trailer `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- **LLM timestamps are never trusted** (spec §3.5): the model returns sentence ids and verbatim quotes; times come only from Whisper word timestamps.
- LLM-facing Pydantic schemas use **no numeric constraints, no `dict` fields, no defaults** (provider structured-output support differs); clamp/validate in code after parsing.
- Default models: Claude `claude-opus-5-5` (adaptive thinking, `output_config.effort`, server-side `fallbacks: "default"` with beta `server-side-fallback-2026-07-01`); Gemini `gemini-2.5-flash`; OpenAI `gpt-5-mini`; Ollama `qwen3:4b` at `http://localhost:11434/v1`. All editable in Settings.
- Effort per task: classify `low`, moments `high`, rerank `medium`.
- Clip options: `clip_count` default 10 (3–30); length default 30–60 s, configurable within 15–90 s; `max ≥ min + 5`.
- Candidate dedupe: temporal IoU > 0.5 keeps the higher score; rerank the top 20; final virality score is an integer 1–99.
- Transcript chunks: ~12-minute windows (720 s) with 60 s overlap.
- Diarization is optional and must never fail a job: missing Hugging Face token, gated model or any pyannote error → recorded as skipped with a user-facing notice.
- Secrets (API keys, HF token) are never returned in full by the API, never logged, and a blank/omitted field on save never wipes a stored key (`""` explicitly clears).
- UI follows Phase 1's design system (tokens `bg-bg`, `text-fg`, `text-muted`, `bg-surface`, `bg-surface-2`, `border-border`, `*-violet-brand`, `*-cyan-brand`, `*-ember`, `*-gold`, `font-display`); dark-first, light theme supported, `prefers-reduced-motion` respected, works at 375 px with no horizontal scroll.

## Review Focus

1. **The LLM paraphrases its quotes** (dropped fillers, different punctuation/case, "3" vs "three", Hindi matras, CJK with no spaces) — alignment must still find the span, fall back to the sentence ids it gave, and silently drop only hopeless candidates; never crash. Tests: Task 7 (`align_quote` variants), Task 8 (garbage-quote fallback).
2. **No usable AI provider** (no key, rejected key, quota exhausted, Ollama not running) — the next configured provider is tried; if none works the job fails with "Open Settings…" guidance and the UI offers an "Open Settings" link. Tests: Task 2 (router), Task 3 (adapter error mapping), Task 12 (ErrorPanel link).
3. **Short or speechless videos, or fewer good moments than requested** — the job succeeds with 0…n clips and a notice; the gallery shows a friendly empty state. Tests: Task 8, Task 12.
4. **Existing Phase 1 database** (no `options` column, no new tables) — upgraded in place on startup without losing projects. Test: Task 1.
5. **Bad model output shapes** (end before start, out-of-range sentence ids, overlapping/duplicate moments, clips longer than the max or shorter than the min, rerank listing unknown ids) — clamped, re-fitted, deduped or ignored. Tests: Task 7, Task 8.

---

## File Map

```
backend/
  pyproject.toml                       + anthropic, google-genai, openai, rapidfuzz, numpy, torch/torchaudio/torchcodec (cu126), pyannote.audio
  app/config.py                        + anthropic_api_key, gemini_api_key, openai_api_key, hf_token (env fallbacks)
  app/models.py                        + Project.options, Setting, Clip tables
  app/options.py                       ProjectOptions + project_options()
  app/db.py                            + add_missing_columns() schema upgrade
  app/repo.py                          + settings + clips functions
  app/audio.py                         read_wav_mono()
  app/media.py                         + extract_frame()
  app/workspace.py                     + VideoPaths.profile / .diarization
  app/llm/base.py                      Effort, LLMError, LLMProvider protocol
  app/llm/cache.py                     LLMCache
  app/llm/router.py                    LLMRouter (repair, retry, fallback, cache)
  app/llm/anthropic_provider.py        Claude adapter
  app/llm/gemini_provider.py           Gemini adapter
  app/llm/openai_provider.py           OpenAI + Ollama adapter
  app/llm/settings.py                  AISettings, load/save, masking, build_providers
  app/llm/factory.py                   router_for(ctx), RouterFactory
  app/llm/prompts/{classify,moments,rerank}.py
  app/analysis/profile.py              ContentProfile, transcript_sample()
  app/analysis/speakers.py             SpeakerTurn, Diarization, assign_speakers(), sentence_speakers()
  app/analysis/chunks.py               TranscriptChunk, chunk_sentences(), render_chunk()
  app/analysis/align.py                align_quote()
  app/analysis/windows.py              expand_to_sentences(), fit_duration(), clip_times(), temporal_iou(), dedupe()
  app/analysis/scoring.py              weights, clamp_sub_scores(), virality_score()
  app/analysis/energy.py               rms_envelope(), energy_score()
  app/analysis/moments.py              LLM schemas (MomentBatch, RerankResult), ScoredCandidate, resolve_moment(), rerank_positions(), finalize()
  app/pipeline/classify.py             ClassifyStage
  app/pipeline/diarize.py              PyannoteDiarizer, DiarizeStage
  app/pipeline/analyze.py              AnalyzeStage
  app/pipeline/registry.py             + new stages
  app/api/schemas.py                   + ClipOut, options/preview fields
  app/api/projects.py                  + options on create, reanalyze, clips, thumbnail, source
  app/api/settings.py                  /api/settings/ai (+ test)
  app/main.py                          + settings router
frontend/src/
  lib/types.ts, lib/api.ts             + clips, options, AI settings
  features/settings/{SettingsPage,ProviderCard,ProviderOrder}.tsx
  features/home/ClipOptions.tsx        options drawer; HomePage/DropZone pass options
  features/clips/{hookTypes.ts,ScoreRing,ClipCard,ClipGallery,ClipModal}.tsx
  features/processing/*                live clips, stage icons, Settings link
  components/AppShell.tsx              + Settings nav link
  App.tsx                              + /settings route
```

---

### Task 1: Database — options, settings and clips

**Files:**
- Create: `backend/app/options.py`, `backend/tests/test_phase2_db.py`
- Modify: `backend/app/models.py`, `backend/app/db.py`, `backend/app/repo.py`

**Interfaces:**
- Consumes: Phase 1 `models.py` (`Project`, `Job`, `utcnow`, `new_id`), `repo._session`, `db.make_engine`.
- Produces:
  - `Project.options: dict | None` (JSON column).
  - `Setting(key: str PK, value: dict JSON, updated_at)`.
  - `Clip(id, project_id, rank: int, start_s: float, end_s: float, title, hook_text, hook_type, why_viral, payoff_summary, score: int, sub_scores: dict[str,int], keywords: list[str], emoji: list[str], speakers: list[str], created_at)`.
  - `ProjectOptions(clip_count=10, min_duration_s=30, max_duration_s=60)` with `.fingerprint() -> str`; `project_options(project) -> ProjectOptions`.
  - `db.add_missing_columns(engine) -> list[str]` (called by `make_engine`).
  - `repo.create_project(..., options: dict | None = None)`, `repo.get_setting(engine, key) -> dict | None`, `repo.put_setting(engine, key, value: dict) -> None`, `repo.replace_clips(engine, project_id, clips: Sequence[Clip]) -> list[Clip]`, `repo.list_clips(engine, project_id) -> list[Clip]` (by rank), `repo.get_clip(engine, clip_id) -> Clip | None`; `delete_project` also deletes clips.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_phase2_db.py`:
```python
import sqlite3

import pytest
from pydantic import ValidationError

from app import repo
from app.db import make_engine
from app.models import Clip, SourceType
from app.options import ProjectOptions, project_options


def make_clip(project_id: str, rank: int, start: float) -> Clip:
    return Clip(
        project_id=project_id, rank=rank, start_s=start, end_s=start + 30, title=f"Clip {rank}",
        hook_text="Hook", hook_type="question", why_viral="Because", payoff_summary="Payoff",
        score=90 - rank, sub_scores={"hook": 8}, keywords=["k"], emoji=["🔥"], speakers=["SPEAKER_00"],
    )


def test_phase1_database_is_upgraded_in_place(tmp_path):
    db = tmp_path / "old db ü" / "clipforge.db"
    db.parent.mkdir()
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE project (id VARCHAR PRIMARY KEY, created_at DATETIME, source_type VARCHAR(6), "
        "source_url VARCHAR, original_filename VARCHAR, title VARCHAR, video_id VARCHAR, duration_s FLOAT)"
    )
    con.execute("INSERT INTO project (id, created_at, source_type, title) VALUES ('old1', '2026-10-01 10:00:00', 'url', 'Old')")
    con.commit()
    con.close()

    engine = make_engine(f"sqlite:///{db.as_posix()}")

    old = repo.get_project(engine, "old1")
    assert old.title == "Old" and old.options is None
    assert project_options(old) == ProjectOptions()
    updated = repo.update_project(engine, "old1", options={"clip_count": 5, "min_duration_s": 20, "max_duration_s": 40})
    assert updated.options["clip_count"] == 5
    assert repo.list_clips(engine, "old1") == []


def test_project_options_defaults_and_validation():
    opts = ProjectOptions()
    assert (opts.clip_count, opts.min_duration_s, opts.max_duration_s) == (10, 30, 60)
    assert ProjectOptions(clip_count=3, min_duration_s=15, max_duration_s=20).max_duration_s == 20
    with pytest.raises(ValidationError):
        ProjectOptions(clip_count=2)
    with pytest.raises(ValidationError):
        ProjectOptions(min_duration_s=40, max_duration_s=42)
    with pytest.raises(ValidationError):
        ProjectOptions(max_duration_s=91)
    assert ProjectOptions().fingerprint() == ProjectOptions().fingerprint()
    assert ProjectOptions().fingerprint() != ProjectOptions(clip_count=11).fingerprint()


def test_create_project_with_options(engine):
    p = repo.create_project(engine, source_type=SourceType.url, source_url="https://youtu.be/x", options={"clip_count": 12})
    assert project_options(repo.get_project(engine, p.id)).clip_count == 12


def test_settings_roundtrip_and_upsert(engine):
    assert repo.get_setting(engine, "ai") is None
    repo.put_setting(engine, "ai", {"a": 1})
    repo.put_setting(engine, "ai", {"a": 2, "b": "x"})
    assert repo.get_setting(engine, "ai") == {"a": 2, "b": "x"}


def test_replace_and_list_clips(engine):
    p = repo.create_project(engine, source_type=SourceType.upload)
    repo.replace_clips(engine, p.id, [make_clip(p.id, 2, 50.0), make_clip(p.id, 1, 10.0)])
    first = repo.list_clips(engine, p.id)
    assert [c.rank for c in first] == [1, 2]
    assert first[0].emoji == ["🔥"] and first[0].sub_scores == {"hook": 8}
    assert repo.get_clip(engine, first[0].id).title == "Clip 1"

    repo.replace_clips(engine, p.id, [make_clip(p.id, 1, 99.0)])
    again = repo.list_clips(engine, p.id)
    assert len(again) == 1 and again[0].start_s == 99.0
    assert repo.get_clip(engine, first[0].id) is None


def test_delete_project_deletes_clips(engine):
    p = repo.create_project(engine, source_type=SourceType.upload)
    [clip] = repo.replace_clips(engine, p.id, [make_clip(p.id, 1, 0.0)])
    repo.delete_project(engine, p.id)
    assert repo.get_clip(engine, clip.id) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_phase2_db.py -v`
Expected: FAIL — `ImportError: cannot import name 'Clip' from 'app.models'`.

- [ ] **Step 3: Implement**

`backend/app/options.py`:
```python
import hashlib

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import Project


class ProjectOptions(BaseModel):
    """Per-project clipping options (spec §3.5: default 30–60 s, configurable 15–90 s)."""

    model_config = ConfigDict(extra="ignore")

    clip_count: int = Field(10, ge=3, le=30)
    min_duration_s: int = Field(30, ge=15, le=85)
    max_duration_s: int = Field(60, ge=20, le=90)

    @model_validator(mode="after")
    def _range(self) -> "ProjectOptions":
        if self.max_duration_s < self.min_duration_s + 5:
            raise ValueError("The longest clip length must be at least 5 seconds more than the shortest.")
        return self

    def fingerprint(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()[:12]


def project_options(project: Project) -> ProjectOptions:
    return ProjectOptions.model_validate(project.options or {})
```

In `backend/app/models.py` add the imports and new fields/tables (keep everything else):
```python
from typing import Any

from sqlalchemy import JSON, Column
```
Add to `Project` (after `duration_s`):
```python
    options: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
```
Append:
```python
class Setting(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    updated_at: datetime = Field(default_factory=utcnow)


class Clip(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    project_id: str = Field(foreign_key="project.id", index=True)
    rank: int
    start_s: float
    end_s: float
    title: str
    hook_text: str
    hook_type: str
    why_viral: str
    payoff_summary: str = ""
    score: int
    sub_scores: dict[str, int] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    keywords: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    emoji: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    speakers: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=utcnow)
```

Replace `backend/app/db.py` with:
```python
import logging
from pathlib import Path

from sqlalchemy import Engine, inspect, text
from sqlmodel import SQLModel, create_engine

from app import models  # noqa: F401  (registers tables on SQLModel.metadata)

logger = logging.getLogger(__name__)


def add_missing_columns(engine: Engine) -> list[str]:
    """Lightweight forward-only migration: add nullable columns that newer code expects.

    create_all() creates missing tables but never alters existing ones, so a database made by an
    older ClipForge would otherwise break on new columns (e.g. Phase 2's Project.options).
    """
    inspector = inspect(engine)
    added: list[str] = []
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            existing = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                if not column.nullable:
                    raise RuntimeError(f"Cannot add required column {table.name}.{column.name} to an existing database")
                ddl_type = column.type.compile(dialect=engine.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {ddl_type}'))
                added.append(f"{table.name}.{column.name}")
    if added:
        logger.info("Upgraded database schema: added %s", ", ".join(added))
    return added


def make_engine(url: str) -> Engine:
    connect_args: dict = {}
    if url.startswith("sqlite:///"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        connect_args["check_same_thread"] = False
    engine = create_engine(url, connect_args=connect_args)
    SQLModel.metadata.create_all(engine)
    add_missing_columns(engine)
    return engine
```

In `backend/app/repo.py`: change the models import to `from app.models import Clip, Job, JobStatus, Project, Setting, SourceType, utcnow`; add `from collections.abc import Sequence`; give `create_project` a keyword `options: dict | None = None` passed into `Project(...)`; in `delete_project` add `s.exec(delete(Clip).where(col(Clip.project_id) == project_id))` before deleting jobs; append:
```python
def get_setting(engine: Engine, key: str) -> dict | None:
    with _session(engine) as s:
        row = s.get(Setting, key)
        return dict(row.value) if row else None


def put_setting(engine: Engine, key: str, value: dict) -> None:
    with _session(engine) as s:
        row = s.get(Setting, key)
        if row is None:
            row = Setting(key=key, value=value)
        else:
            row.value = value
            row.updated_at = utcnow()
        s.add(row)
        s.commit()


def replace_clips(engine: Engine, project_id: str, clips: Sequence[Clip]) -> list[Clip]:
    with _session(engine) as s:
        s.exec(delete(Clip).where(col(Clip.project_id) == project_id))
        for clip in clips:
            s.add(clip)
        s.commit()
    return list_clips(engine, project_id)


def list_clips(engine: Engine, project_id: str) -> list[Clip]:
    with _session(engine) as s:
        stmt = select(Clip).where(col(Clip.project_id) == project_id).order_by(col(Clip.rank))
        return list(s.exec(stmt))


def get_clip(engine: Engine, clip_id: str) -> Clip | None:
    with _session(engine) as s:
        return s.get(Clip, clip_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass (Phase 1 suite + 6 new), zero warnings.

- [ ] **Step 5: Commit**

```bash
git add backend/app/options.py backend/app/models.py backend/app/db.py backend/app/repo.py backend/tests/test_phase2_db.py
git commit -m "feat(backend): add clip/setting tables, project options and in-place schema upgrade"
```

---

### Task 2: LLM core — provider protocol, cache and router

**Files:**
- Create: `backend/app/llm/__init__.py` (empty), `backend/app/llm/base.py`, `backend/app/llm/cache.py`, `backend/app/llm/router.py`, `backend/tests/test_llm_router.py`
- Modify: `backend/tests/fakes.py` (append `FakeLLMProvider`)

**Interfaces:**
- Consumes: `app.pipeline.errors.StageError`, `app.workspace.atomic_write_json`.
- Produces:
  - `Effort = Literal["low","medium","high"]`; `LLMError(message, *, retryable: bool)` with `.message`, `.retryable`; `LLMProvider` Protocol: attributes `name: str`, `model: str`; `generate_json(*, system: str, prompt: str, schema: type[T], effort: Effort) -> T`.
  - `LLMCache(directory: Path)`: `LLMCache.key(*, task, prompt_version, provider, model, system, prompt, schema) -> str`, `.get(key, schema) -> T | None`, `.put(key, value) -> None`.
  - `LLMRouter(providers, *, cache=None, max_repairs=2, retry_delay_s=2.0, sleep=time.sleep)`: `.providers -> list[LLMProvider]`; `.generate_json(*, task, prompt_version, system, prompt, schema, effort) -> T` — raises `StageError` (hint mentions Settings) when nothing works.
  - `tests/fakes.py`: `FakeLLMProvider(name="fake", model="fake-1", responses=...)` — `responses` maps schema class name → list of outcomes (model instance / dict / Exception; consumed in order, last one repeats) or is a callable `(schema=, prompt=, system=) -> outcome`; records `.calls` (dicts with `system`, `prompt`, `schema`, `effort`).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/fakes.py`:
```python
from pydantic import BaseModel as _BaseModel


class FakeLLMProvider:
    """Scriptable LLM provider for tests (no network)."""

    def __init__(self, name: str = "fake", model: str = "fake-1", responses=None) -> None:
        self.name = name
        self.model = model
        self._responses = responses or {}
        self.calls: list[dict] = []

    def generate_json(self, *, system, prompt, schema, effort):
        self.calls.append({"system": system, "prompt": prompt, "schema": schema, "effort": effort})
        if callable(self._responses):
            outcome = self._responses(schema=schema, prompt=prompt, system=system)
        else:
            queue = self._responses[schema.__name__]
            outcome = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, _BaseModel):
            return outcome
        return schema.model_validate(outcome)
```

`backend/tests/test_llm_router.py`:
```python
import pytest
from pydantic import BaseModel

from app.llm.base import LLMError
from app.llm.cache import LLMCache
from app.llm.router import LLMRouter
from app.pipeline.errors import StageError
from tests.fakes import FakeLLMProvider


class Answer(BaseModel):
    value: int


def call(router: LLMRouter, prompt: str = "q") -> Answer:
    return router.generate_json(task="t", prompt_version="v1", system="s", prompt=prompt, schema=Answer, effort="low")


def test_returns_first_provider_result():
    a = FakeLLMProvider("a", responses={"Answer": [{"value": 1}]})
    b = FakeLLMProvider("b", responses={"Answer": [{"value": 2}]})
    assert call(LLMRouter([a, b])).value == 1
    assert b.calls == []


def test_falls_back_on_non_retryable_error():
    a = FakeLLMProvider("a", responses={"Answer": [LLMError("bad key", retryable=False)]})
    b = FakeLLMProvider("b", responses={"Answer": [{"value": 2}]})
    assert call(LLMRouter([a, b])).value == 2
    assert len(a.calls) == 1


def test_retries_transient_error_once_on_same_provider():
    slept = []
    a = FakeLLMProvider("a", responses={"Answer": [LLMError("429", retryable=True), {"value": 3}]})
    assert call(LLMRouter([a], sleep=slept.append, retry_delay_s=1.5)).value == 3
    assert slept == [1.5] and len(a.calls) == 2


def test_second_transient_error_moves_to_next_provider():
    a = FakeLLMProvider("a", responses={"Answer": [LLMError("429", retryable=True)]})
    b = FakeLLMProvider("b", responses={"Answer": [{"value": 4}]})
    assert call(LLMRouter([a, b], sleep=lambda s: None)).value == 4
    assert len(a.calls) == 2


def test_repairs_invalid_json_with_error_feedback():
    a = FakeLLMProvider("a", responses={"Answer": [{"value": "not a number"}, {"value": 5}]})
    assert call(LLMRouter([a])).value == 5
    assert "did not match the required JSON schema" in a.calls[1]["prompt"]
    assert a.calls[1]["prompt"].startswith("q")


def test_gives_up_after_max_repairs_then_tries_next_provider():
    a = FakeLLMProvider("a", responses={"Answer": [{"value": "x"}]})
    b = FakeLLMProvider("b", responses={"Answer": [{"value": 6}]})
    assert call(LLMRouter([a, b], max_repairs=2)).value == 6
    assert len(a.calls) == 3


def test_no_providers_points_to_settings():
    with pytest.raises(StageError) as err:
        call(LLMRouter([]))
    assert "Settings" in err.value.hint


def test_all_providers_failing_lists_them():
    a = FakeLLMProvider("anthropic", responses={"Answer": [LLMError("Claude rejected the API key.", retryable=False)]})
    b = FakeLLMProvider("gemini", responses={"Answer": [LLMError("quota exhausted", retryable=False)]})
    with pytest.raises(StageError) as err:
        call(LLMRouter([a, b]))
    assert "anthropic" in err.value.hint and "gemini" in err.value.hint and "Settings" in err.value.hint


def test_cache_hit_skips_provider(tmp_path):
    cache = LLMCache(tmp_path / "llm cache ü")
    a = FakeLLMProvider("a", responses={"Answer": [{"value": 7}]})
    assert call(LLMRouter([a], cache=cache)).value == 7
    assert call(LLMRouter([a], cache=cache)).value == 7
    assert len(a.calls) == 1
    assert call(LLMRouter([a], cache=cache), prompt="different").value == 7
    assert len(a.calls) == 2


def test_cache_key_depends_on_inputs():
    base = dict(task="t", prompt_version="v1", provider="p", model="m", system="s", prompt="x", schema=Answer)
    assert LLMCache.key(**base) == LLMCache.key(**base)
    for field, value in [("prompt_version", "v2"), ("model", "m2"), ("prompt", "y"), ("provider", "q")]:
        assert LLMCache.key(**base) != LLMCache.key(**(base | {field: value}))


def test_corrupt_cache_entry_is_ignored(tmp_path):
    cache = LLMCache(tmp_path)
    key = LLMCache.key(task="t", prompt_version="v1", provider="a", model="fake-1", system="s", prompt="q", schema=Answer)
    (tmp_path / f"{key}.json").write_text("{not json", encoding="utf-8")
    a = FakeLLMProvider("a", responses={"Answer": [{"value": 8}]})
    assert call(LLMRouter([a], cache=cache)).value == 8
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_llm_router.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.llm'`.

- [ ] **Step 3: Implement**

`backend/app/llm/base.py`:
```python
from typing import Literal, Protocol, TypeVar

from pydantic import BaseModel

Effort = Literal["low", "medium", "high"]
T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """A provider call failed. `retryable` means the same provider may succeed if asked again shortly."""

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.message = message
        self.retryable = retryable


class LLMProvider(Protocol):
    name: str   # "anthropic" | "gemini" | "openai" | "ollama" | test names
    model: str

    def generate_json(self, *, system: str, prompt: str, schema: type[T], effort: Effort) -> T:
        """Return a `schema` instance. Raise LLMError for API failures; may raise
        pydantic.ValidationError when the reply doesn't fit the schema."""
        ...
```

`backend/app/llm/cache.py`:
```python
import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ValidationError

from app.llm.base import T
from app.workspace import atomic_write_json


class LLMCache:
    """Caches validated responses on disk so re-runs (retry, new clip options) don't re-bill the same call."""

    def __init__(self, directory: Path) -> None:
        self._dir = directory

    @staticmethod
    def key(*, task: str, prompt_version: str, provider: str, model: str, system: str, prompt: str,
            schema: type[BaseModel]) -> str:
        payload = json.dumps(
            [task, prompt_version, provider, model, system, prompt, schema.__name__, schema.model_json_schema()],
            ensure_ascii=False, sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

    def get(self, key: str, schema: type[T]) -> T | None:
        path = self._dir / f"{key}.json"
        if not path.exists():
            return None
        try:
            return schema.model_validate_json(path.read_text(encoding="utf-8"))
        except (ValidationError, OSError, ValueError):
            return None

    def put(self, key: str, value: BaseModel) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self._dir / f"{key}.json", value)
```

`backend/app/llm/router.py`:
```python
import logging
import time
from collections.abc import Callable, Sequence

from pydantic import ValidationError

from app.llm.base import Effort, LLMError, LLMProvider, T
from app.llm.cache import LLMCache
from app.pipeline.errors import StageError

logger = logging.getLogger(__name__)

REPAIR_SUFFIX = (
    "\n\nYour previous reply did not match the required JSON schema:\n{error}\n"
    "Reply again with only valid JSON that matches the schema exactly."
)
NO_PROVIDER_HINT = "Open Settings and add an API key (Gemini has a free tier), or enable Ollama for fully local AI."


def _short(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, e['loc'])) or 'root'}: {e['msg']}" for e in exc.errors()[:8])


class LLMRouter:
    """Tries providers in order with schema-repair retries, one transient retry, and a response cache."""

    def __init__(
        self,
        providers: Sequence[LLMProvider],
        *,
        cache: LLMCache | None = None,
        max_repairs: int = 2,
        retry_delay_s: float = 2.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._providers = list(providers)
        self._cache = cache
        self._max_repairs = max_repairs
        self._retry_delay_s = retry_delay_s
        self._sleep = sleep

    @property
    def providers(self) -> list[LLMProvider]:
        return list(self._providers)

    def generate_json(
        self, *, task: str, prompt_version: str, system: str, prompt: str, schema: type[T], effort: Effort
    ) -> T:
        if not self._providers:
            raise StageError("No AI provider is set up.", NO_PROVIDER_HINT)
        failures: list[str] = []
        for provider in self._providers:
            key = LLMCache.key(
                task=task, prompt_version=prompt_version, provider=provider.name, model=provider.model,
                system=system, prompt=prompt, schema=schema,
            )
            if self._cache is not None and (hit := self._cache.get(key, schema)) is not None:
                return hit
            try:
                result = self._call(provider, system=system, prompt=prompt, schema=schema, effort=effort)
            except LLMError as exc:
                logger.warning("LLM provider %s failed on %s: %s", provider.name, task, exc.message)
                failures.append(f"{provider.name}: {exc.message}")
                continue
            if self._cache is not None:
                self._cache.put(key, result)
            return result
        raise StageError(
            "The AI step failed with every configured provider.",
            "Check your API keys, model names and quota in Settings. Details: " + " | ".join(failures),
        )

    def _call(self, provider: LLMProvider, *, system: str, prompt: str, schema: type[T], effort: Effort) -> T:
        attempt_prompt = prompt
        repairs = 0
        retried_transient = False
        while True:
            try:
                result = provider.generate_json(system=system, prompt=attempt_prompt, schema=schema, effort=effort)
                return schema.model_validate(result.model_dump())
            except ValidationError as exc:
                if repairs >= self._max_repairs:
                    raise LLMError(f"replied with invalid JSON {repairs + 1} times", retryable=False) from exc
                repairs += 1
                attempt_prompt = prompt + REPAIR_SUFFIX.format(error=_short(exc))
            except LLMError as exc:
                if exc.retryable and not retried_transient:
                    retried_transient = True
                    self._sleep(self._retry_delay_s)
                    continue
                raise
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass, zero warnings.

- [ ] **Step 5: Commit**

```bash
git add backend/app/llm backend/tests/fakes.py backend/tests/test_llm_router.py
git commit -m "feat(llm): add provider protocol, response cache and fallback router with schema repair"
```

---

### Task 3: Provider adapters — Claude, Gemini, OpenAI/Ollama

**Files:**
- Create: `backend/app/llm/anthropic_provider.py`, `backend/app/llm/gemini_provider.py`, `backend/app/llm/openai_provider.py`, `backend/tests/test_llm_providers.py`
- Modify: `backend/pyproject.toml` (deps)

**Interfaces:**
- Consumes: Task 2 `LLMError`, `Effort`, `T`.
- Produces: `AnthropicProvider(api_key, model="claude-opus-5-5", client=None)` (`name="anthropic"`), `GeminiProvider(api_key, model="gemini-2.5-flash", client=None)` (`name="gemini"`), `OpenAIProvider(api_key, model="gpt-5-mini", base_url=None, name="openai", client=None)` (Ollama = `OpenAIProvider(api_key="ollama", base_url=..., model=..., name="ollama")`). All satisfy `LLMProvider`; all map SDK errors to `LLMError` with an accurate `retryable` flag and a short user-readable message (never including the key).

- [ ] **Step 1: Add dependencies**

Run (from `backend/`): `uv add "anthropic>=0.70" "google-genai>=2.28" "openai>=3.24"`
Expected: `uv.lock` updated, install succeeds.

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_llm_providers.py`:
```python
from types import SimpleNamespace

import anthropic
import httpx
import openai
import pytest
from google.genai import errors as genai_errors
from pydantic import BaseModel

from app.llm.anthropic_provider import AnthropicProvider
from app.llm.base import LLMError
from app.llm.gemini_provider import GeminiProvider
from app.llm.openai_provider import OpenAIProvider


class Answer(BaseModel):
    value: int


def http_response(status: int) -> httpx.Response:
    return httpx.Response(status, request=httpx.Request("POST", "https://api.example.test"))


# ---------- Anthropic ----------
class FakeAnthropicMessages:
    def __init__(self, outcome):
        self.outcome = outcome
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def anthropic_with(outcome) -> tuple[AnthropicProvider, FakeAnthropicMessages]:
    messages = FakeAnthropicMessages(outcome)
    return AnthropicProvider(api_key="sk-test", client=SimpleNamespace(messages=messages)), messages


def test_anthropic_sends_schema_effort_thinking_and_fallbacks():
    provider, messages = anthropic_with(SimpleNamespace(stop_reason="end_turn", parsed_output=Answer(value=1)))
    assert provider.generate_json(system="sys", prompt="hi", schema=Answer, effort="high").value == 1
    kw = messages.kwargs
    assert kw["model"] == "claude-opus-5-5"
    assert kw["system"] == "sys"
    assert kw["messages"] == [{"role": "user", "content": "hi"}]
    assert kw["output_format"] is Answer
    assert kw["thinking"] == {"type": "adaptive"}
    assert kw["output_config"]["effort"] == "high"
    assert kw["extra_body"] == {"fallbacks": "default"}
    assert kw["extra_headers"] == {"anthropic-beta": "server-side-fallback-2026-07-01"}
    assert provider.name == "anthropic"


def test_anthropic_refusal_is_not_retryable():
    provider, _ = anthropic_with(SimpleNamespace(stop_reason="refusal", parsed_output=None))
    with pytest.raises(LLMError) as err:
        provider.generate_json(system="s", prompt="p", schema=Answer, effort="low")
    assert not err.value.retryable


@pytest.mark.parametrize(("exc", "retryable"), [
    (anthropic.RateLimitError("slow down", response=http_response(429), body=None), True),
    (anthropic.AuthenticationError("bad key", response=http_response(401), body=None), False),
    (anthropic.InternalServerError("boom", response=http_response(500), body=None), True),
    (anthropic.BadRequestError("bad", response=http_response(400), body=None), False),
    (anthropic.APIConnectionError(request=httpx.Request("POST", "https://x")), True),
])
def test_anthropic_error_mapping(exc, retryable):
    provider, _ = anthropic_with(exc)
    with pytest.raises(LLMError) as err:
        provider.generate_json(system="s", prompt="p", schema=Answer, effort="low")
    assert err.value.retryable is retryable
    assert "sk-test" not in err.value.message


# ---------- Gemini ----------
class FakeGeminiModels:
    def __init__(self, outcome):
        self.outcome = outcome
        self.kwargs = None

    def generate_content(self, **kwargs):
        self.kwargs = kwargs
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def gemini_with(outcome) -> tuple[GeminiProvider, FakeGeminiModels]:
    models = FakeGeminiModels(outcome)
    return GeminiProvider(api_key="g-test", client=SimpleNamespace(models=models)), models


def test_gemini_uses_json_schema_and_thinking_budget():
    provider, models = gemini_with(SimpleNamespace(parsed=Answer(value=2), text='{"value": 2}'))
    assert provider.generate_json(system="sys", prompt="hi", schema=Answer, effort="medium").value == 2
    config = models.kwargs["config"]
    assert models.kwargs["model"] == "gemini-2.5-flash" and models.kwargs["contents"] == "hi"
    assert config.system_instruction == "sys"
    assert config.response_mime_type == "application/json"
    assert config.response_schema is Answer
    assert config.thinking_config.thinking_budget == 2048


def test_gemini_falls_back_to_text_when_parsed_missing():
    provider, _ = gemini_with(SimpleNamespace(parsed=None, text='{"value": 3}'))
    assert provider.generate_json(system="s", prompt="p", schema=Answer, effort="low").value == 3


@pytest.mark.parametrize(("code", "retryable"), [(429, True), (400, False), (403, False)])
def test_gemini_client_error_mapping(code, retryable):
    exc = genai_errors.ClientError(code, {"error": {"code": code, "message": "nope", "status": "X"}})
    provider, _ = gemini_with(exc)
    with pytest.raises(LLMError) as err:
        provider.generate_json(system="s", prompt="p", schema=Answer, effort="low")
    assert err.value.retryable is retryable


def test_gemini_server_error_is_retryable():
    provider, _ = gemini_with(genai_errors.ServerError(503, {"error": {"code": 503, "message": "busy", "status": "UNAVAILABLE"}}))
    with pytest.raises(LLMError) as err:
        provider.generate_json(system="s", prompt="p", schema=Answer, effort="low")
    assert err.value.retryable


# ---------- OpenAI / Ollama ----------
class FakeCompletions:
    def __init__(self, outcome):
        self.outcome = outcome
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def openai_with(outcome, **kw) -> tuple[OpenAIProvider, FakeCompletions]:
    completions = FakeCompletions(outcome)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return OpenAIProvider(api_key="o-test", client=client, **kw), completions


def parsed_reply(model: BaseModel | None, refusal: str | None = None, content: str | None = None):
    message = SimpleNamespace(parsed=model, refusal=refusal, content=content)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_openai_parse_with_reasoning_effort():
    provider, completions = openai_with(parsed_reply(Answer(value=4)))
    assert provider.generate_json(system="sys", prompt="hi", schema=Answer, effort="high").value == 4
    kw = completions.kwargs
    assert kw["model"] == "gpt-5-mini" and kw["response_format"] is Answer
    assert kw["messages"] == [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
    assert kw["reasoning_effort"] == "high"


def test_ollama_omits_reasoning_effort_and_sets_temperature():
    provider, completions = openai_with(parsed_reply(Answer(value=5)), name="ollama", model="qwen3:4b",
                                        base_url="http://localhost:11434/v1")
    provider.generate_json(system="s", prompt="p", schema=Answer, effort="high")
    assert "reasoning_effort" not in completions.kwargs
    assert completions.kwargs["temperature"] == 0.2
    assert provider.name == "ollama"


def test_openai_refusal_and_content_fallback():
    provider, _ = openai_with(parsed_reply(None, refusal="no"))
    with pytest.raises(LLMError):
        provider.generate_json(system="s", prompt="p", schema=Answer, effort="low")
    provider, _ = openai_with(parsed_reply(None, content='{"value": 6}'))
    assert provider.generate_json(system="s", prompt="p", schema=Answer, effort="low").value == 6


@pytest.mark.parametrize(("exc", "retryable"), [
    (openai.RateLimitError("slow", response=http_response(429), body={"error": {"code": "rate_limit_exceeded"}}), True),
    (openai.RateLimitError("quota", response=http_response(429), body={"error": {"code": "insufficient_quota"}}), False),
    (openai.AuthenticationError("bad key", response=http_response(401), body=None), False),
    (openai.APIConnectionError(request=httpx.Request("POST", "http://localhost:11434/v1")), True),
    (openai.InternalServerError("boom", response=http_response(500), body=None), True),
])
def test_openai_error_mapping(exc, retryable):
    provider, _ = openai_with(exc)
    with pytest.raises(LLMError) as err:
        provider.generate_json(system="s", prompt="p", schema=Answer, effort="low")
    assert err.value.retryable is retryable
    assert "o-test" not in err.value.message
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_llm_providers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.llm.anthropic_provider'`.

- [ ] **Step 4: Implement the adapters**

`backend/app/llm/anthropic_provider.py`:
```python
from typing import Any

import anthropic

from app.llm.base import Effort, LLMError, T

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider:
    """Claude via the official SDK: structured output (Pydantic), adaptive thinking, effort,
    and server-side refusal fallbacks (fallbacks="default")."""

    name = "anthropic"

    def __init__(self, api_key: str, model: str = "claude-opus-5-5", client: Any = None) -> None:
        self.model = model
        self._client = client or anthropic.Anthropic(api_key=api_key, max_retries=2, timeout=600.0)

    def generate_json(self, *, system: str, prompt: str, schema: type[T], effort: Effort) -> T:
        try:
            response = self._client.messages.parse(
                model=self.model,
                max_tokens=16000,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_format=schema,
                thinking={"type": "adaptive"},
                output_config={"effort": effort},
                extra_headers={"anthropic-beta": FALLBACK_BETA},
                extra_body={"fallbacks": "default"},
            )
        except anthropic.RateLimitError as exc:
            raise LLMError("Claude rate limit reached.", retryable=True) from exc
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            raise LLMError("Claude rejected the API key.", retryable=False) from exc
        except anthropic.NotFoundError as exc:
            raise LLMError(f"Claude model '{self.model}' was not found.", retryable=False) from exc
        except anthropic.BadRequestError as exc:
            raise LLMError(f"Claude rejected the request: {exc.message}", retryable=False) from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Claude API error {exc.status_code}.", retryable=exc.status_code >= 500) from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("Couldn't reach the Claude API.", retryable=True) from exc

        if response.stop_reason == "refusal":
            raise LLMError("Claude declined this request.", retryable=False)
        if response.stop_reason == "max_tokens":
            raise LLMError("Claude's reply was cut off (max_tokens).", retryable=False)
        parsed = response.parsed_output
        if parsed is None:
            raise LLMError("Claude returned no structured output.", retryable=False)
        return parsed
```
> SDK check (do this before relying on the test): open the installed SDK's `Messages.parse` (`uv run python -c "import inspect, anthropic.resources.messages as m; print(inspect.signature(m.Messages.parse))"`). If `parse` builds `output_config` itself from `output_format` and would drop your `effort`, merge instead: pass `output_config={"effort": effort}` only if the signature accepts it alongside `output_format`; otherwise pass effort via `extra_body={"output_config": {"effort": effort}, "fallbacks": "default"}` **and** keep `output_format`, then verify with `client.messages.parse(...)`'s request preview (`with_raw_response`) that the final JSON body contains both `output_config.format` and `output_config.effort`. Adjust the test's `output_config` assertion to wherever effort ends up; the requirement is that both schema enforcement and effort reach the API.

`backend/app/llm/gemini_provider.py`:
```python
from typing import Any

from google import genai
from google.genai import errors, types

from app.llm.base import Effort, LLMError, T

THINKING_BUDGET: dict[str, int] = {"low": 0, "medium": 2048, "high": 8192}


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash", client: Any = None) -> None:
        self.model = model
        self._client = client or genai.Client(api_key=api_key)

    def generate_json(self, *, system: str, prompt: str, schema: type[T], effort: Effort) -> T:
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.4,
            response_mime_type="application/json",
            response_schema=schema,
            thinking_config=types.ThinkingConfig(thinking_budget=THINKING_BUDGET[effort]),
            http_options=types.HttpOptions(timeout=600_000),
        )
        try:
            response = self._client.models.generate_content(model=self.model, contents=prompt, config=config)
        except errors.ClientError as exc:
            if exc.code == 429:
                raise LLMError("Gemini quota or rate limit reached.", retryable=True) from exc
            if exc.code in (400, 401, 403):
                raise LLMError(f"Gemini rejected the request or API key ({exc.code}).", retryable=False) from exc
            if exc.code == 404:
                raise LLMError(f"Gemini model '{self.model}' was not found.", retryable=False) from exc
            raise LLMError(f"Gemini error {exc.code}.", retryable=False) from exc
        except errors.ServerError as exc:
            raise LLMError(f"Gemini server error {exc.code}.", retryable=True) from exc
        except errors.APIError as exc:
            raise LLMError(f"Gemini error {exc.code}.", retryable=False) from exc
        except OSError as exc:  # httpx transport errors subclass OSError-compatible exceptions on Windows
            raise LLMError("Couldn't reach the Gemini API.", retryable=True) from exc

        if isinstance(response.parsed, schema):
            return response.parsed
        if response.parsed is not None:
            return schema.model_validate(response.parsed)
        return schema.model_validate_json(response.text or "")
```
> If `errors.ClientError(code, response_json)` has a different constructor in the installed google-genai, adapt the test's construction (not the provider) — check `inspect.signature(errors.APIError.__init__)`. Also catch `httpx.TransportError` explicitly if it is not an `OSError` subclass (check `issubclass(httpx.TransportError, OSError)`); keep `retryable=True` for it.

`backend/app/llm/openai_provider.py`:
```python
from typing import Any

import openai

from app.llm.base import Effort, LLMError, T


class OpenAIProvider:
    """OpenAI (and any OpenAI-compatible server such as Ollama) via chat.completions.parse."""

    def __init__(self, api_key: str, model: str = "gpt-5-mini", base_url: str | None = None,
                 name: str = "openai", client: Any = None) -> None:
        self.name = name
        self.model = model
        self._label = "Ollama" if name == "ollama" else "OpenAI"
        self._client = client or openai.OpenAI(api_key=api_key, base_url=base_url, max_retries=2, timeout=600.0)

    def generate_json(self, *, system: str, prompt: str, schema: type[T], effort: Effort) -> T:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "response_format": schema,
        }
        if self.name == "openai":
            kwargs["reasoning_effort"] = effort
        else:
            kwargs["temperature"] = 0.2
        try:
            completion = self._client.chat.completions.parse(**kwargs)
        except openai.RateLimitError as exc:
            if getattr(exc, "code", None) == "insufficient_quota":
                raise LLMError(f"{self._label} quota exhausted.", retryable=False) from exc
            raise LLMError(f"{self._label} rate limit reached.", retryable=True) from exc
        except (openai.AuthenticationError, openai.PermissionDeniedError) as exc:
            raise LLMError(f"{self._label} rejected the API key.", retryable=False) from exc
        except openai.NotFoundError as exc:
            raise LLMError(f"{self._label} model '{self.model}' was not found.", retryable=False) from exc
        except (openai.LengthFinishReasonError, openai.ContentFilterFinishReasonError) as exc:
            raise LLMError(f"{self._label} reply was cut off or filtered.", retryable=False) from exc
        except openai.BadRequestError as exc:
            raise LLMError(f"{self._label} rejected the request.", retryable=False) from exc
        except (openai.APIConnectionError, openai.APITimeoutError) as exc:
            where = "Is Ollama running?" if self.name == "ollama" else "Check your connection."
            raise LLMError(f"Couldn't reach {self._label}. {where}", retryable=True) from exc
        except openai.APIStatusError as exc:
            raise LLMError(f"{self._label} API error {exc.status_code}.", retryable=exc.status_code >= 500) from exc

        message = completion.choices[0].message
        if message.refusal:
            raise LLMError(f"{self._label} declined this request.", retryable=False)
        if message.parsed is not None:
            return message.parsed
        return schema.model_validate_json(message.content or "")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass, zero warnings.

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/app/llm backend/tests/test_llm_providers.py
git commit -m "feat(llm): add Claude, Gemini and OpenAI/Ollama structured-output adapters"
```

---

### Task 4: AI settings store, router factory and Settings API

**Files:**
- Create: `backend/app/llm/settings.py`, `backend/app/llm/factory.py`, `backend/app/api/settings.py`, `backend/tests/test_ai_settings.py`
- Modify: `backend/app/config.py`, `backend/app/main.py` (include router)

**Interfaces:**
- Consumes: Task 1 `repo.get_setting/put_setting`; Task 2 `LLMRouter`, `LLMCache`, `LLMError`; Task 3 adapters; Phase 1 `PipelineContext`, `Services`, `get_services`.
- Produces:
  - `Settings` gains `anthropic_api_key`, `gemini_api_key`, `openai_api_key`, `hf_token` (all `str = ""`, env `CLIPFORGE_*`).
  - `ProviderName = Literal["anthropic","gemini","openai","ollama"]`, `ALL_PROVIDERS`, `SECRET_FIELDS`.
  - `AISettings` (fields listed below), `AISettingsUpdate` (same fields, all optional), `load_ai_settings(engine, settings) -> AISettings`, `save_ai_settings(engine, settings, update) -> AISettings`, `mask_secret(value) -> str | None`, `build_provider(name, ai) -> LLMProvider | None`, `build_providers(ai) -> list[LLMProvider]`.
  - `RouterFactory = Callable[[PipelineContext], LLMRouter]`; `router_for(ctx) -> LLMRouter` (cache under `videos/<id>/llm/`).
  - REST: `GET /api/settings/ai -> AISettingsOut`; `PUT /api/settings/ai (AISettingsUpdate) -> AISettingsOut`; `POST /api/settings/ai/test {"provider": ProviderName} -> {"ok": bool, "message": str, "latency_ms": int}`. `AISettingsOut` = `AISettings` with every secret masked (`str | None`) plus `configured_providers: list[ProviderName]`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_ai_settings.py`:
```python
from fastapi.testclient import TestClient

from app.api import settings as settings_api
from app.llm.base import LLMError
from app.llm.settings import AISettingsUpdate, build_providers, load_ai_settings, mask_secret, save_ai_settings
from app.main import create_app
from tests.fakes import FakeIngestStage, FakeLLMProvider


def test_mask_secret():
    assert mask_secret("") is None
    assert mask_secret("sk-ant-1234567890abcd") == "••••abcd"
    assert mask_secret("short") == "••••"


def test_defaults_and_env_fallback(engine, settings):
    ai = load_ai_settings(engine, settings)
    assert ai.provider_order == ["anthropic", "gemini", "openai", "ollama"]
    assert ai.anthropic_model == "claude-opus-5-5" and ai.gemini_model == "gemini-2.5-flash"
    assert build_providers(ai) == []
    env = settings.model_copy(update={"gemini_api_key": "env-gemini-key"})
    assert load_ai_settings(engine, env).gemini_api_key == "env-gemini-key"


def test_save_keeps_secret_when_omitted_and_clears_with_empty(engine, settings):
    save_ai_settings(engine, settings, AISettingsUpdate(anthropic_api_key="  sk-ant-secret-9999  "))
    assert load_ai_settings(engine, settings).anthropic_api_key == "sk-ant-secret-9999"
    save_ai_settings(engine, settings, AISettingsUpdate(anthropic_model="claude-sonnet-5-5"))
    ai = load_ai_settings(engine, settings)
    assert ai.anthropic_api_key == "sk-ant-secret-9999" and ai.anthropic_model == "claude-sonnet-5-5"
    save_ai_settings(engine, settings, AISettingsUpdate(anthropic_api_key=""))
    assert load_ai_settings(engine, settings).anthropic_api_key == ""


def test_stored_key_beats_env(engine, settings):
    env = settings.model_copy(update={"openai_api_key": "env-key"})
    save_ai_settings(engine, env, AISettingsUpdate(openai_api_key="db-key"))
    assert load_ai_settings(engine, env).openai_api_key == "db-key"


def test_provider_order_is_completed_and_deduped(engine, settings):
    ai = save_ai_settings(engine, settings, AISettingsUpdate(provider_order=["ollama", "gemini", "ollama"]))
    assert ai.provider_order == ["ollama", "gemini", "anthropic", "openai"]


def test_build_providers_follows_order_and_configuration(engine, settings):
    ai = save_ai_settings(engine, settings, AISettingsUpdate(
        provider_order=["gemini", "anthropic"], gemini_api_key="g", anthropic_api_key="a", ollama_enabled=True,
    ))
    assert [p.name for p in build_providers(ai)] == ["gemini", "anthropic", "ollama"]


def make_client(settings):
    return TestClient(create_app(settings, stages_factory=lambda: [FakeIngestStage()]))


def test_api_masks_secrets_and_reports_configured(settings):
    with make_client(settings) as client:
        res = client.put("/api/settings/ai", json={"gemini_api_key": "AIza-very-secret-1234", "hf_token": "hf_abcdefgh5678"})
        assert res.status_code == 200
        body = client.get("/api/settings/ai").json()
    assert body["gemini_api_key"] == "••••1234" and body["hf_token"] == "••••5678"
    assert body["anthropic_api_key"] is None
    assert body["configured_providers"] == ["gemini"]
    assert "very-secret" not in str(body)


def test_api_rejects_unknown_provider_names(settings):
    with make_client(settings) as client:
        assert client.put("/api/settings/ai", json={"provider_order": ["mystery"]}).status_code == 422


def test_api_test_provider(settings, monkeypatch):
    ok = FakeLLMProvider("gemini", responses={"Ping": [{"ok": True, "reply": "pong"}]})
    monkeypatch.setattr(settings_api, "build_provider", lambda name, ai: ok if name == "gemini" else None)
    with make_client(settings) as client:
        good = client.post("/api/settings/ai/test", json={"provider": "gemini"}).json()
        missing = client.post("/api/settings/ai/test", json={"provider": "openai"}).json()
    assert good["ok"] is True and good["latency_ms"] >= 0
    assert missing["ok"] is False and "not set up" in missing["message"].lower()


def test_api_test_provider_reports_errors(settings, monkeypatch):
    bad = FakeLLMProvider("anthropic", responses={"Ping": [LLMError("Claude rejected the API key.", retryable=False)]})
    monkeypatch.setattr(settings_api, "build_provider", lambda name, ai: bad)
    with make_client(settings) as client:
        res = client.post("/api/settings/ai/test", json={"provider": "anthropic"}).json()
    assert res == {"ok": False, "message": "Claude rejected the API key.", "latency_ms": res["latency_ms"]}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ai_settings.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.llm.settings'`.

- [ ] **Step 3: Implement**

In `backend/app/config.py` add these fields to `Settings` (after `job_concurrency`):
```python
    # Fallbacks for keys not saved in Settings (CLIPFORGE_ANTHROPIC_API_KEY etc. in .env).
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    openai_api_key: str = ""
    hf_token: str = ""
```

`backend/app/llm/settings.py`:
```python
from typing import Literal

from pydantic import BaseModel, field_validator
from sqlalchemy import Engine

from app import repo
from app.config import Settings
from app.llm.anthropic_provider import AnthropicProvider
from app.llm.base import LLMProvider
from app.llm.gemini_provider import GeminiProvider
from app.llm.openai_provider import OpenAIProvider

ProviderName = Literal["anthropic", "gemini", "openai", "ollama"]
ALL_PROVIDERS: tuple[ProviderName, ...] = ("anthropic", "gemini", "openai", "ollama")
SECRET_FIELDS = ("anthropic_api_key", "gemini_api_key", "openai_api_key", "hf_token")
SETTINGS_KEY = "ai"


def _complete_order(order: list[str]) -> list[str]:
    seen = list(dict.fromkeys(order))
    return seen + [p for p in ALL_PROVIDERS if p not in seen]


class AISettings(BaseModel):
    provider_order: list[ProviderName] = list(ALL_PROVIDERS)
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5-5"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    openai_api_key: str = ""
    openai_model: str = "gpt-5-mini"
    ollama_enabled: bool = False
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen3:4b"
    hf_token: str = ""

    @field_validator("provider_order")
    @classmethod
    def _order(cls, value: list[str]) -> list[str]:
        return _complete_order(value)


class AISettingsUpdate(BaseModel):
    """Partial update. For secrets: omitted/None keeps the stored value, "" clears it."""

    provider_order: list[ProviderName] | None = None
    anthropic_api_key: str | None = None
    anthropic_model: str | None = None
    gemini_api_key: str | None = None
    gemini_model: str | None = None
    openai_api_key: str | None = None
    openai_model: str | None = None
    ollama_enabled: bool | None = None
    ollama_base_url: str | None = None
    ollama_model: str | None = None
    hf_token: str | None = None


def _stored(engine: Engine) -> AISettings:
    return AISettings.model_validate(repo.get_setting(engine, SETTINGS_KEY) or {})


def load_ai_settings(engine: Engine, settings: Settings) -> AISettings:
    stored = _stored(engine)
    env = {field: getattr(settings, field) for field in SECRET_FIELDS}
    return stored.model_copy(update={k: v for k, v in env.items() if v and not getattr(stored, k)})


def save_ai_settings(engine: Engine, settings: Settings, update: AISettingsUpdate) -> AISettings:
    changes = update.model_dump(exclude_none=True)
    for field in SECRET_FIELDS:
        if field in changes:
            changes[field] = changes[field].strip()
    for field in ("anthropic_model", "gemini_model", "openai_model", "ollama_model", "ollama_base_url"):
        if field in changes:
            changes[field] = changes[field].strip()
    merged = AISettings.model_validate(_stored(engine).model_dump() | changes)
    repo.put_setting(engine, SETTINGS_KEY, merged.model_dump())
    return load_ai_settings(engine, settings)


def mask_secret(value: str) -> str | None:
    if not value:
        return None
    return "••••" + value[-4:] if len(value) > 8 else "••••"


def build_provider(name: ProviderName, ai: AISettings) -> LLMProvider | None:
    if name == "anthropic" and ai.anthropic_api_key:
        return AnthropicProvider(api_key=ai.anthropic_api_key, model=ai.anthropic_model)
    if name == "gemini" and ai.gemini_api_key:
        return GeminiProvider(api_key=ai.gemini_api_key, model=ai.gemini_model)
    if name == "openai" and ai.openai_api_key:
        return OpenAIProvider(api_key=ai.openai_api_key, model=ai.openai_model)
    if name == "ollama" and ai.ollama_enabled:
        return OpenAIProvider(api_key="ollama", model=ai.ollama_model, base_url=ai.ollama_base_url, name="ollama")
    return None


def build_providers(ai: AISettings) -> list[LLMProvider]:
    return [p for name in ai.provider_order if (p := build_provider(name, ai)) is not None]
```
`backend/app/llm/factory.py`:
```python
from collections.abc import Callable

from app.llm.cache import LLMCache
from app.llm.router import LLMRouter
from app.llm.settings import build_providers, load_ai_settings
from app.pipeline.context import PipelineContext

RouterFactory = Callable[[PipelineContext], LLMRouter]


def router_for(ctx: PipelineContext) -> LLMRouter:
    """Built per stage run so freshly saved keys apply to the next job without a restart."""
    ai = load_ai_settings(ctx.engine, ctx.settings)
    return LLMRouter(build_providers(ai), cache=LLMCache(ctx.video().dir / "llm"))
```

`backend/app/api/settings.py`:
```python
import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ValidationError

from app.api.deps import Services, get_services
from app.llm.base import LLMError
from app.llm.settings import (
    SECRET_FIELDS, AISettings, AISettingsUpdate, ProviderName, build_provider,
    load_ai_settings, mask_secret, save_ai_settings,
)

router = APIRouter(tags=["settings"])


class AISettingsOut(BaseModel):
    provider_order: list[ProviderName]
    anthropic_api_key: str | None
    anthropic_model: str
    gemini_api_key: str | None
    gemini_model: str
    openai_api_key: str | None
    openai_model: str
    ollama_enabled: bool
    ollama_base_url: str
    ollama_model: str
    hf_token: str | None
    configured_providers: list[ProviderName]


class ProviderTestRequest(BaseModel):
    provider: ProviderName


class ProviderTestResult(BaseModel):
    ok: bool
    message: str
    latency_ms: int


class Ping(BaseModel):
    ok: bool
    reply: str


def _out(ai: AISettings) -> AISettingsOut:
    data = ai.model_dump()
    for field in SECRET_FIELDS:
        data[field] = mask_secret(data[field])
    configured = [name for name in ai.provider_order if build_provider(name, ai) is not None]
    return AISettingsOut(**data, configured_providers=configured)


@router.get("/settings/ai", response_model=AISettingsOut)
def get_ai_settings(svc: Services = Depends(get_services)) -> AISettingsOut:
    return _out(load_ai_settings(svc.engine, svc.settings))


@router.put("/settings/ai", response_model=AISettingsOut)
def put_ai_settings(update: AISettingsUpdate, svc: Services = Depends(get_services)) -> AISettingsOut:
    return _out(save_ai_settings(svc.engine, svc.settings, update))


@router.post("/settings/ai/test", response_model=ProviderTestResult)
def test_provider(body: ProviderTestRequest, svc: Services = Depends(get_services)) -> ProviderTestResult:
    provider = build_provider(body.provider, load_ai_settings(svc.engine, svc.settings))
    if provider is None:
        return ProviderTestResult(ok=False, message="This provider is not set up yet.", latency_ms=0)
    started = time.perf_counter()
    try:
        provider.generate_json(
            system="You are a connectivity check for ClipForge.",
            prompt='Reply with ok=true and reply="pong".', schema=Ping, effort="low",
        )
    except LLMError as exc:
        return ProviderTestResult(ok=False, message=exc.message, latency_ms=int((time.perf_counter() - started) * 1000))
    except ValidationError:
        return ProviderTestResult(ok=False, message="The model replied, but not in the expected JSON format.",
                                  latency_ms=int((time.perf_counter() - started) * 1000))
    return ProviderTestResult(ok=True, message=f"Connected to {provider.model}.",
                              latency_ms=int((time.perf_counter() - started) * 1000))
```

In `backend/app/main.py`: change `from app.api import jobs, projects, system` to `from app.api import jobs, projects, settings as settings_api, system` and add `app.include_router(settings_api.router, prefix="/api")` after the jobs router.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass, zero warnings.

- [ ] **Step 5: Commit**

```bash
git add backend/app/config.py backend/app/llm/settings.py backend/app/llm/factory.py backend/app/api/settings.py backend/app/main.py backend/tests/test_ai_settings.py
git commit -m "feat(llm): add AI settings store with masked secrets, router factory and settings API"
```

---
### Task 5: Classify stage — content profile

**Files:**
- Create: `backend/app/analysis/__init__.py` (empty), `backend/app/analysis/profile.py`, `backend/app/llm/prompts/__init__.py` (empty), `backend/app/llm/prompts/classify.py`, `backend/app/pipeline/classify.py`, `backend/tests/builders.py`, `backend/tests/test_classify.py`
- Modify: `backend/app/workspace.py` (add `VideoPaths.profile`, `VideoPaths.diarization`)

**Interfaces:**
- Consumes: Phase 1 `Transcript`, `VideoMeta` (`app.pipeline.ingest`), `PipelineContext`, `atomic_write_json`, `read_json`; Task 4 `RouterFactory`, `router_for`; Task 2 `LLMRouter`.
- Produces:
  - `VideoPaths.profile` (`profile.json`), `VideoPaths.diarization` (`diarization.json`).
  - `ContentType = Literal["podcast","talking_head","gaming","screen_tutorial","vlog","other"]`; `ContentProfile(content_type, speaker_count_estimate: int, topics: list[str], tone: str, summary: str)`; `transcript_sample(transcript, *, head=700, middle=300, tail=200) -> str`.
  - `prompts.classify`: `VERSION`, `SYSTEM`, `build_prompt(*, title, channel, description, duration_s, language, sample) -> str`.
  - `ClassifyStage(router_factory=router_for)`: `name="classify"`, `label="Understanding content"`, `weight=0.5`, `uses_gpu=False`; writes `profile.json`; emits `partial {kind:"profile", content_type, speakers, topics}`.
  - `tests/builders.py`: `make_transcript(sentences, *, sentence_s=3.0, gap_s=0.2, language="en") -> Transcript`; `write_wav(path, samples, sample_rate=16000)`; `prepare_video(ctx, transcript, *, title="My Talk", profile=None, diarization=None, source=None, loud_spans=()) -> VideoPaths` (writes transcript/meta/audio, optional profile/diarization/source; sets `ctx.video_id` and the project's `video_id`); `fixed_router(provider) -> RouterFactory`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/app/workspace.py` `VideoPaths` (needed by the builders):
```python
    @property
    def profile(self) -> Path:
        return self.dir / "profile.json"

    @property
    def diarization(self) -> Path:
        return self.dir / "diarization.json"
```

`backend/tests/builders.py`:
```python
import shutil
import wave
from pathlib import Path

import numpy as np

from app import repo
from app.llm.router import LLMRouter
from app.pipeline.context import PipelineContext
from app.pipeline.ingest import VideoMeta
from app.pipeline.transcript import Transcript, Word, build_sentences
from app.workspace import VideoPaths, atomic_write_json


def make_transcript(sentences: list[str], *, sentence_s: float = 3.0, gap_s: float = 0.2,
                    language: str = "en") -> Transcript:
    words: list[Word] = []
    t = 0.0
    for sentence in sentences:
        tokens = sentence.split()
        step = sentence_s / len(tokens)
        for token in tokens:
            words.append(Word(text=" " + token, start=round(t, 3), end=round(t + step * 0.9, 3)))
            t += step
        t += gap_s
    return Transcript(language=language, duration_s=round(t, 3), words=words, sentences=build_sentences(words))


def write_wav(path: Path, samples: np.ndarray, sample_rate: int = 16000) -> None:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())


def prepare_video(ctx: PipelineContext, transcript: Transcript, *, title: str = "My Talk", profile=None,
                  diarization=None, source: Path | None = None,
                  loud_spans: tuple[tuple[float, float], ...] = ()) -> VideoPaths:
    ctx.video_id = ctx.video_id or f"vid{ctx.project_id}"
    repo.update_project(ctx.engine, ctx.project_id, video_id=ctx.video_id, title=title)
    vp = ctx.video()
    atomic_write_json(vp.transcript, transcript)
    atomic_write_json(vp.meta, VideoMeta(video_id=ctx.video_id, source_file="source.mp4", title=title,
                                         channel="Chan", duration_s=transcript.duration_s))
    sr = 16000
    rng = np.random.default_rng(0)
    samples = rng.normal(0, 0.02, int(transcript.duration_s * sr) + sr).astype(np.float32)
    for start, end in loud_spans:
        samples[int(start * sr):int(end * sr)] *= 15
    write_wav(vp.audio, samples, sr)
    if profile is not None:
        atomic_write_json(vp.profile, profile)
    if diarization is not None:
        atomic_write_json(vp.diarization, diarization)
    if source is not None:
        shutil.copy(source, vp.dir / "source.mp4")
    return vp


def fixed_router(provider):
    return lambda ctx: LLMRouter([provider])
```

`backend/tests/test_classify.py`:
```python
from app.analysis.profile import ContentProfile, transcript_sample
from app.pipeline.classify import ClassifyStage
from app.pipeline.transcript import Transcript
from app.workspace import read_json
from tests.builders import fixed_router, make_transcript, prepare_video
from tests.fakes import FakeLLMProvider

PROFILE = {"content_type": "podcast", "speaker_count_estimate": 25, "topics": [f"t{i}" for i in range(12)],
           "tone": "casual", "summary": "Two friends talk about habits."}


def test_classify_writes_clamped_profile_and_emits_partial(make_ctx, bus):
    ctx = make_ctx()
    prepare_video(ctx, make_transcript(["Hello there friend.", "We talk about habits today."]), title="Habits Pod")
    fake = FakeLLMProvider(responses={"ContentProfile": [PROFILE]})
    stage = ClassifyStage(router_factory=fixed_router(fake))
    assert not stage.is_done(ctx)

    stage.run(ctx)

    profile = ContentProfile.model_validate(read_json(ctx.video().profile))
    assert profile.content_type == "podcast"
    assert profile.speaker_count_estimate == 10
    assert len(profile.topics) == 8
    assert stage.is_done(ctx)
    call = fake.calls[0]
    assert call["effort"] == "low"
    assert "Habits Pod" in call["prompt"] and "en" in call["prompt"] and "habits today" in call["prompt"]
    partial = [e.data for e in bus.history(ctx.job_id) if e.type == "partial"][-1]
    assert partial == {"kind": "profile", "content_type": "podcast", "speakers": 10, "topics": profile.topics}


def test_speaker_count_floor(make_ctx):
    ctx = make_ctx()
    prepare_video(ctx, make_transcript(["Just me talking here."]))
    fake = FakeLLMProvider(responses={"ContentProfile": [PROFILE | {"speaker_count_estimate": 0}]})
    ClassifyStage(router_factory=fixed_router(fake)).run(ctx)
    assert read_json(ctx.video().profile)["speaker_count_estimate"] == 1


def test_no_speech_skips_the_llm(make_ctx):
    ctx = make_ctx()
    prepare_video(ctx, Transcript(language="en", duration_s=12.0))
    fake = FakeLLMProvider(responses={"ContentProfile": [PROFILE]})
    ClassifyStage(router_factory=fixed_router(fake)).run(ctx)
    assert fake.calls == []
    assert read_json(ctx.video().profile)["content_type"] == "other"


def test_transcript_sample_keeps_head_middle_tail():
    t = make_transcript([f"word{i} filler filler." for i in range(600)])
    sample = transcript_sample(t, head=10, middle=6, tail=4)
    assert sample.startswith("word0") and sample.count("[…]") == 2 and sample.rstrip().endswith("filler.")
    short = make_transcript(["Only a few words."])
    assert transcript_sample(short) == "Only a few words."
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_classify.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.analysis'`.

- [ ] **Step 3: Implement**

`backend/app/analysis/profile.py`:
```python
from typing import Literal

from pydantic import BaseModel

from app.pipeline.transcript import Transcript

ContentType = Literal["podcast", "talking_head", "gaming", "screen_tutorial", "vlog", "other"]


class ContentProfile(BaseModel):
    content_type: ContentType
    speaker_count_estimate: int
    topics: list[str]
    tone: str
    summary: str


def _join(words: list[str]) -> str:
    return "".join(words).strip()


def transcript_sample(transcript: Transcript, *, head: int = 700, middle: int = 300, tail: int = 200) -> str:
    words = [w.text for w in transcript.words]
    if len(words) <= head + middle + tail:
        return _join(words)
    mid = len(words) // 2
    parts = [_join(words[:head]), _join(words[mid - middle // 2: mid + middle // 2]), _join(words[-tail:])]
    return "\n[…]\n".join(parts)
```

`backend/app/llm/prompts/classify.py`:
```python
VERSION = "classify-v1"

SYSTEM = (
    "You classify long-form videos for ClipForge, a tool that cuts them into vertical short clips. "
    "Base every answer only on the evidence given. Be concise and literal."
)


def _mmss(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 3600}:{total % 3600 // 60:02d}:{total % 60:02d}" if total >= 3600 else f"{total // 60}:{total % 60:02d}"


def build_prompt(*, title: str | None, channel: str | None, description: str | None, duration_s: float,
                 language: str, sample: str) -> str:
    return f"""Classify this video.

Title: {title or "(unknown)"}
Channel: {channel or "(unknown)"}
Duration: {_mmss(duration_s)}
Spoken language code: {language}
Description: {(description or "(none)")[:1500]}

Transcript sample:
{sample}

Answer with:
- content_type: one of podcast (two or more people in conversation or interview), talking_head (one person speaking to camera, incl. lectures and educational), gaming (gameplay with commentary), screen_tutorial (screen recording or software walkthrough), vlog (mixed footage, travel, lifestyle), other.
- speaker_count_estimate: how many different people speak.
- topics: 3 to 6 short topic tags, in the transcript's language.
- tone: 1 to 3 words (for example "energetic", "calm and educational").
- summary: one sentence describing the video."""
```

`backend/app/pipeline/classify.py`:
```python
from app.analysis.profile import ContentProfile, transcript_sample
from app.llm.factory import RouterFactory, router_for
from app.llm.prompts import classify as prompt
from app.pipeline.context import PipelineContext
from app.pipeline.ingest import VideoMeta
from app.pipeline.transcript import Transcript
from app.workspace import atomic_write_json, read_json


class ClassifyStage:
    name = "classify"
    label = "Understanding content"
    weight = 0.5
    uses_gpu = False

    def __init__(self, router_factory: RouterFactory = router_for) -> None:
        self._router_factory = router_factory

    def is_done(self, ctx: PipelineContext) -> bool:
        return ctx.video_id is not None and ctx.video().profile.exists()

    def run(self, ctx: PipelineContext) -> None:
        vp = ctx.video()
        transcript = Transcript.model_validate(read_json(vp.transcript))
        meta = VideoMeta.model_validate(read_json(vp.meta))
        if not transcript.words:
            profile = ContentProfile(content_type="other", speaker_count_estimate=1, topics=[],
                                     tone="unknown", summary="No speech was detected.")
        else:
            ctx.progress(self.name, 0.2, "Reading the transcript…")
            profile = self._router_factory(ctx).generate_json(
                task="classify", prompt_version=prompt.VERSION, system=prompt.SYSTEM,
                prompt=prompt.build_prompt(
                    title=meta.title, channel=meta.channel, description=meta.description,
                    duration_s=transcript.duration_s, language=transcript.language,
                    sample=transcript_sample(transcript),
                ),
                schema=ContentProfile, effort="low",
            )
            profile = profile.model_copy(update={
                "speaker_count_estimate": max(1, min(10, profile.speaker_count_estimate)),
                "topics": [t.strip() for t in profile.topics if t.strip()][:8],
            })
        atomic_write_json(vp.profile, profile)
        ctx.emit("partial", stage=self.name, data={
            "kind": "profile", "content_type": profile.content_type,
            "speakers": profile.speaker_count_estimate, "topics": profile.topics,
        })
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass, zero warnings.

- [ ] **Step 5: Commit**

```bash
git add backend/app/workspace.py backend/app/analysis backend/app/llm/prompts backend/app/pipeline/classify.py backend/tests/builders.py backend/tests/test_classify.py
git commit -m "feat(pipeline): add classify stage producing a content profile"
```

---

### Task 6: Diarize stage — who speaks when (optional, GPU)

**Files:**
- Create: `backend/app/audio.py`, `backend/app/analysis/speakers.py`, `backend/app/pipeline/diarize.py`, `backend/tests/test_speakers.py`, `backend/tests/test_diarize.py`, `backend/tests/test_diarize_gpu.py`
- Modify: `backend/pyproject.toml` (torch cu126 + pyannote)

**Interfaces:**
- Consumes: Task 4 `load_ai_settings` (for `hf_token`); Task 5 `ContentProfile`, `VideoPaths.profile/.diarization`, test builders; Phase 1 `StageCancelled`.
- Produces:
  - `app.audio.read_wav_mono(path) -> tuple[np.ndarray(float32), int]`; `app.audio.iter_wav_blocks(path, block_frames) -> Iterator[np.ndarray]`.
  - `SpeakerTurn(start, end, speaker)`; `Diarization(skipped=False, reason_code: str | None=None, reason: str | None=None, turns=[], word_speakers: list[str|None]=[], speaker_count=0)`; `assign_speakers(words, turns, *, tolerance_s=0.5) -> list[str | None]`; `sentence_speakers(sentences, word_speakers) -> list[str | None]`.
  - `Diarizer` Protocol `diarize(audio: Path, *, max_speakers: int, cancel: threading.Event) -> list[SpeakerTurn]`; `DiarizationUnavailable(Exception)`; `PyannoteDiarizer(token)`.
  - `DiarizeStage(diarizer_factory=PyannoteDiarizer)`: `name="diarize"`, `label="Identifying speakers"`, `weight=1.0`, `uses_gpu=True`; always writes `diarization.json`; never fails the job except on cancel. `reason_code ∈ {"single_speaker","no_token","error"}`.

- [ ] **Step 1: Add dependencies (CUDA torch + pyannote)**

Edit `backend/pyproject.toml` — add to `dependencies`: `"numpy>=2.2"`, `"torch"`, `"torchaudio"`, `"torchcodec"`, `"pyannote.audio>=4.0.7"`; and append (verbatim from the findings doc §"CUDA torch in pyproject"):
```toml
[tool.uv.sources]
torch = { index = "pytorch-cu126" }
torchaudio = { index = "pytorch-cu126" }
torchcodec = { index = "pytorch-cu126" }

[[tool.uv.index]]
name = "pytorch-cu126"
url = "https://download.pytorch.org/whl/cu126"
explicit = true
```
Run: `uv sync` then `uv run python -c "import torch; print(torch.__version__, torch.cuda.is_available())"`
Expected: `2.14.1+cu126 True` (version may be newer; `+cu126` and `True` are what matter).
Then run `uv run pytest -m gpu -q` — the Phase 1 Whisper GPU test must still pass (proves torch's CUDA libraries and ctranslate2's coexist in one process).

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_speakers.py`:
```python
import numpy as np

from app.analysis.speakers import SpeakerTurn, assign_speakers, sentence_speakers
from app.audio import iter_wav_blocks, read_wav_mono
from app.pipeline.transcript import Word, build_sentences
from tests.builders import write_wav


def w(text, start, end):
    return Word(text=text, start=start, end=end)


def test_assign_speakers_by_word_midpoint_with_tolerance():
    words = [w(" a", 0.0, 0.4), w(" b", 0.5, 0.9), w(" c", 2.0, 2.4), w(" d", 5.0, 5.2), w(" e", 9.0, 9.2)]
    turns = [SpeakerTurn(start=0.0, end=1.0, speaker="A"), SpeakerTurn(start=1.9, end=4.0, speaker="B"),
             SpeakerTurn(start=5.5, end=6.0, speaker="A")]
    assert assign_speakers(words, turns) == ["A", "A", "B", "A", None]
    assert assign_speakers(words, []) == [None] * 5


def test_sentence_speakers_majority():
    words = [w(" Hi", 0, 0.2), w(" there.", 0.3, 0.5), w(" Yes", 1, 1.2), w(" yes", 1.3, 1.4), w(" no.", 1.5, 1.6)]
    sentences = build_sentences(words)
    assert sentence_speakers(sentences, ["A", "A", "B", None, "B"]) == ["A", "B"]
    assert sentence_speakers(sentences, [None] * 5) == [None, None]


def test_read_wav_roundtrip_and_blocks(tmp_path):
    path = tmp_path / "a ü.wav"
    samples = np.linspace(-0.5, 0.5, 16000, dtype=np.float32)
    write_wav(path, samples)
    data, sr = read_wav_mono(path)
    assert sr == 16000 and data.dtype == np.float32 and abs(float(data[-1]) - 0.5) < 1e-3
    blocks = list(iter_wav_blocks(path, 4000))
    assert [len(b) for b in blocks] == [4000, 4000, 4000, 4000]
```

`backend/tests/test_diarize.py`:
```python
import threading

import pytest

from app.analysis.profile import ContentProfile
from app.analysis.speakers import Diarization, SpeakerTurn
from app.llm.settings import AISettingsUpdate, save_ai_settings
from app.pipeline.diarize import DiarizationUnavailable, DiarizeStage
from app.pipeline.errors import StageCancelled
from app.workspace import read_json
from tests.builders import make_transcript, prepare_video

PODCAST = ContentProfile(content_type="podcast", speaker_count_estimate=2, topics=[], tone="x", summary="y")
SOLO = ContentProfile(content_type="talking_head", speaker_count_estimate=1, topics=[], tone="x", summary="y")
TRANSCRIPT = make_transcript(["Hello and welcome.", "Thanks for having me.", "So tell me more."])


class FakeDiarizer:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    def diarize(self, audio, *, max_speakers, cancel):
        self.calls.append(max_speakers)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def stage_with(outcome):
    fake = FakeDiarizer(outcome)
    tokens = []
    return DiarizeStage(diarizer_factory=lambda token: tokens.append(token) or fake), fake, tokens


def result(ctx) -> Diarization:
    return Diarization.model_validate(read_json(ctx.video().diarization))


def test_single_speaker_is_skipped_without_model(make_ctx):
    ctx = make_ctx()
    prepare_video(ctx, TRANSCRIPT, profile=SOLO)
    stage, fake, _ = stage_with([])
    stage.run(ctx)
    assert result(ctx).reason_code == "single_speaker" and fake.calls == []


def test_missing_token_is_skipped_with_notice_and_rerun_once_token_added(make_ctx, bus, engine, settings):
    ctx = make_ctx()
    prepare_video(ctx, TRANSCRIPT, profile=PODCAST)
    stage, fake, _ = stage_with([SpeakerTurn(start=0, end=100, speaker="SPEAKER_00")])
    stage.run(ctx)
    assert result(ctx).reason_code == "no_token"
    assert any("Hugging Face" in (e.message or "") for e in bus.history(ctx.job_id) if e.type == "log")
    assert stage.is_done(ctx)
    save_ai_settings(engine, settings, AISettingsUpdate(hf_token="hf_token_value_1234"))
    assert not stage.is_done(ctx)


def test_runs_diarizer_and_assigns_words(make_ctx, engine, settings):
    save_ai_settings(engine, settings, AISettingsUpdate(hf_token="hf_token_value_1234"))
    ctx = make_ctx()
    prepare_video(ctx, TRANSCRIPT, profile=PODCAST)
    turns = [SpeakerTurn(start=0.0, end=3.1, speaker="SPEAKER_00"), SpeakerTurn(start=3.1, end=99, speaker="SPEAKER_01")]
    stage, fake, tokens = stage_with(turns)
    stage.run(ctx)
    d = result(ctx)
    assert not d.skipped and d.speaker_count == 2
    assert d.word_speakers[0] == "SPEAKER_00" and d.word_speakers[-1] == "SPEAKER_01"
    assert tokens == ["hf_token_value_1234"] and fake.calls == [3]
    assert stage.is_done(ctx)


def test_diarizer_failure_degrades_gracefully(make_ctx, bus, engine, settings):
    save_ai_settings(engine, settings, AISettingsUpdate(hf_token="hf_token_value_1234"))
    ctx = make_ctx()
    prepare_video(ctx, TRANSCRIPT, profile=PODCAST)
    stage, _, _ = stage_with(DiarizationUnavailable("Accept the model terms first."))
    stage.run(ctx)
    d = result(ctx)
    assert d.skipped and d.reason_code == "error" and "terms" in d.reason
    assert any("Speaker detection" in (e.message or "") for e in bus.history(ctx.job_id) if e.type == "log")

    ctx2 = make_ctx()
    prepare_video(ctx2, TRANSCRIPT, profile=PODCAST)
    crash, _, _ = stage_with(RuntimeError("CUDA exploded"))
    crash.run(ctx2)
    assert result(ctx2).reason_code == "error"


def test_cancel_propagates(make_ctx, engine, settings):
    save_ai_settings(engine, settings, AISettingsUpdate(hf_token="hf_token_value_1234"))
    ctx = make_ctx()
    prepare_video(ctx, TRANSCRIPT, profile=PODCAST)
    stage, _, _ = stage_with(StageCancelled())
    with pytest.raises(StageCancelled):
        stage.run(ctx)
```

`backend/tests/test_diarize_gpu.py`:
```python
import os
import threading

import pytest

from app.gpu import register_cuda_dlls
from app.media import extract_audio
from app.pipeline.diarize import PyannoteDiarizer


@pytest.mark.gpu
@pytest.mark.skipif(not os.environ.get("CLIPFORGE_HF_TOKEN"), reason="needs CLIPFORGE_HF_TOKEN with pyannote terms accepted")
def test_real_pyannote_runs(sample_video, tmp_path):
    register_cuda_dlls()
    audio = tmp_path / "a.wav"
    extract_audio(sample_video, audio)
    turns = PyannoteDiarizer(os.environ["CLIPFORGE_HF_TOKEN"]).diarize(audio, max_speakers=2, cancel=threading.Event())
    assert isinstance(turns, list)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_speakers.py tests/test_diarize.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.audio'`.

- [ ] **Step 4: Implement**

`backend/app/audio.py`:
```python
import wave
from collections.abc import Iterator
from pathlib import Path

import numpy as np


def _decode(frames: bytes, channels: int, width: int) -> np.ndarray:
    if width != 2:
        raise ValueError(f"Expected 16-bit PCM WAV, got {width * 8}-bit")
    data = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    return data.reshape(-1, channels).mean(axis=1) if channels > 1 else data


def read_wav_mono(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wf:
        return _decode(wf.readframes(wf.getnframes()), wf.getnchannels(), wf.getsampwidth()), wf.getframerate()


def iter_wav_blocks(path: Path, block_frames: int) -> Iterator[np.ndarray]:
    """Stream a long WAV in fixed-size mono float32 blocks (memory stays flat for 2 h videos)."""
    with wave.open(str(path), "rb") as wf:
        channels, width = wf.getnchannels(), wf.getsampwidth()
        while frames := wf.readframes(block_frames):
            yield _decode(frames, channels, width)
```

`backend/app/analysis/speakers.py`:
```python
import bisect
from collections import Counter
from collections.abc import Sequence

from pydantic import BaseModel, Field

from app.pipeline.transcript import Sentence, Word


class SpeakerTurn(BaseModel):
    start: float
    end: float
    speaker: str


class Diarization(BaseModel):
    skipped: bool = False
    reason_code: str | None = None   # single_speaker | no_token | error
    reason: str | None = None
    turns: list[SpeakerTurn] = Field(default_factory=list)
    word_speakers: list[str | None] = Field(default_factory=list)
    speaker_count: int = 0


def assign_speakers(words: Sequence[Word], turns: Sequence[SpeakerTurn], *, tolerance_s: float = 0.5) -> list[str | None]:
    ordered = sorted(turns, key=lambda t: t.start)
    starts = [t.start for t in ordered]
    out: list[str | None] = []
    for word in words:
        mid = (word.start + word.end) / 2
        i = bisect.bisect_right(starts, mid) - 1
        if i >= 0 and ordered[i].end >= mid:
            out.append(ordered[i].speaker)
            continue
        best, gap = None, tolerance_s
        for j in (i, i + 1):
            if 0 <= j < len(ordered):
                distance = min(abs(mid - ordered[j].start), abs(mid - ordered[j].end))
                if distance <= gap:
                    best, gap = ordered[j].speaker, distance
        out.append(best)
    return out


def sentence_speakers(sentences: Sequence[Sentence], word_speakers: Sequence[str | None]) -> list[str | None]:
    out: list[str | None] = []
    for s in sentences:
        votes = Counter(sp for sp in word_speakers[s.word_start:s.word_end] if sp)
        out.append(votes.most_common(1)[0][0] if votes else None)
    return out
```

`backend/app/pipeline/diarize.py`:
```python
import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from app.analysis.profile import ContentProfile
from app.analysis.speakers import Diarization, SpeakerTurn, assign_speakers
from app.audio import read_wav_mono
from app.llm.settings import load_ai_settings
from app.pipeline.context import PipelineContext
from app.pipeline.errors import StageCancelled
from app.pipeline.transcript import Transcript
from app.workspace import atomic_write_json, read_json

logger = logging.getLogger(__name__)
MODEL_ID = "pyannote/speaker-diarization-community-1"
TERMS_HINT = f"Accept the model terms at https://huggingface.co/{MODEL_ID} with the account that owns your token."


class DiarizationUnavailable(Exception):
    """The diarization model can't be used (gated, bad token, missing)."""


class Diarizer(Protocol):
    def diarize(self, audio: Path, *, max_speakers: int, cancel: threading.Event) -> list[SpeakerTurn]: ...


DiarizerFactory = Callable[[str], Diarizer]


class PyannoteDiarizer:
    def __init__(self, token: str) -> None:
        self._token = token
        self._pipeline = None
        self._lock = threading.Lock()

    def _load(self):
        import torch
        from pyannote.audio import Pipeline

        try:
            pipeline = Pipeline.from_pretrained(MODEL_ID, token=self._token)
        except Exception as exc:  # gated repo, revoked token, network
            raise DiarizationUnavailable(f"Couldn't load the speaker model. {TERMS_HINT}") from exc
        if pipeline is None:
            raise DiarizationUnavailable(f"Couldn't load the speaker model. {TERMS_HINT}")
        if torch.cuda.is_available():
            pipeline.to(torch.device("cuda"))
        return pipeline

    def diarize(self, audio: Path, *, max_speakers: int, cancel: threading.Event) -> list[SpeakerTurn]:
        import torch

        with self._lock:
            if self._pipeline is None:
                self._pipeline = self._load()
            samples, sample_rate = read_wav_mono(audio)
            if cancel.is_set():
                raise StageCancelled()
            output = self._pipeline(
                {"waveform": torch.from_numpy(samples)[None, :], "sample_rate": sample_rate},
                min_speakers=1, max_speakers=max_speakers,
            )
            annotation = output.exclusive_speaker_diarization
            return [SpeakerTurn(start=float(turn.start), end=float(turn.end), speaker=str(label))
                    for turn, _, label in annotation.itertracks(yield_label=True)]


class DiarizeStage:
    name = "diarize"
    label = "Identifying speakers"
    weight = 1.0
    uses_gpu = True

    def __init__(self, diarizer_factory: DiarizerFactory = PyannoteDiarizer) -> None:
        self._factory = diarizer_factory
        self._diarizers: dict[str, Diarizer] = {}

    def is_done(self, ctx: PipelineContext) -> bool:
        if ctx.video_id is None or not ctx.video().diarization.exists():
            return False
        result = Diarization.model_validate(read_json(ctx.video().diarization))
        if result.skipped and result.reason_code in ("no_token", "error"):
            # Try again once the user has (re)entered a Hugging Face token.
            return not load_ai_settings(ctx.engine, ctx.settings).hf_token
        return True

    def _save(self, ctx: PipelineContext, result: Diarization) -> None:
        atomic_write_json(ctx.video().diarization, result)

    def run(self, ctx: PipelineContext) -> None:
        vp = ctx.video()
        profile = ContentProfile.model_validate(read_json(vp.profile))
        transcript = Transcript.model_validate(read_json(vp.transcript))
        if not transcript.words or (profile.content_type != "podcast" and profile.speaker_count_estimate < 2):
            self._save(ctx, Diarization(skipped=True, reason_code="single_speaker", reason="Only one speaker expected."))
            return
        token = load_ai_settings(ctx.engine, ctx.settings).hf_token
        if not token:
            self._save(ctx, Diarization(skipped=True, reason_code="no_token", reason="No Hugging Face token."))
            ctx.emit("log", stage=self.name,
                     message="Add a free Hugging Face token in Settings so ClipForge can tell speakers apart.")
            return
        ctx.progress(self.name, 0.1, "Listening for different voices…")
        diarizer = self._diarizers.get(token) or self._diarizers.setdefault(token, self._factory(token))
        try:
            turns = diarizer.diarize(vp.audio, max_speakers=min(8, max(2, profile.speaker_count_estimate + 1)),
                                     cancel=ctx.cancel_event)
        except StageCancelled:
            raise
        except DiarizationUnavailable as exc:
            self._save(ctx, Diarization(skipped=True, reason_code="error", reason=str(exc)))
            ctx.emit("log", stage=self.name, message=f"Speaker detection is unavailable: {exc}")
            return
        except Exception as exc:  # never fail the whole job over an optional enhancement
            logger.exception("Diarization failed")
            self._save(ctx, Diarization(skipped=True, reason_code="error", reason=f"{type(exc).__name__}: {exc}"))
            ctx.emit("log", stage=self.name, message="Speaker detection failed, so clips won't follow speakers this time.")
            return
        speakers = sorted({t.speaker for t in turns})
        self._save(ctx, Diarization(turns=turns, word_speakers=assign_speakers(transcript.words, turns),
                                    speaker_count=len(speakers)))
        ctx.emit("partial", stage=self.name, data={"kind": "speakers", "count": len(speakers)})
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest -q` then `uv run pytest -m gpu -q`
Expected: all pass, zero warnings; the GPU Whisper test still passes; `test_real_pyannote_runs` is skipped unless `CLIPFORGE_HF_TOKEN` is set.

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/app/audio.py backend/app/analysis/speakers.py backend/app/pipeline/diarize.py backend/tests/test_speakers.py backend/tests/test_diarize.py backend/tests/test_diarize_gpu.py
git commit -m "feat(pipeline): add optional pyannote diarization stage with graceful degradation"
```

---

### Task 7: Moment-finding building blocks (pure logic)

**Files:**
- Create: `backend/app/analysis/chunks.py`, `backend/app/analysis/align.py`, `backend/app/analysis/windows.py`, `backend/app/analysis/scoring.py`, `backend/app/analysis/energy.py`, `backend/tests/test_analysis_logic.py`
- Modify: `backend/pyproject.toml` (`rapidfuzz`)

**Interfaces:**
- Consumes: Phase 1 `Word`, `Sentence`; Task 6 `iter_wav_blocks`; test builders.
- Produces:
  - `TranscriptChunk(index, first_sentence, last_sentence, start_s, end_s)` (sentence indices inclusive); `chunk_sentences(sentences, *, window_s=720.0, overlap_s=60.0) -> list[TranscriptChunk]`; `render_chunk(sentences, chunk, speakers: list[str|None] | None = None) -> str` (one line per sentence: `[S{id}] (m:ss) {SPEAKER: }text`).
  - `align_quote(words, quote, *, lo=0, hi=None, min_score=80.0) -> tuple[int, int] | None` (word index range, end exclusive).
  - `expand_to_sentences(sentences, start_word, end_word) -> tuple[int, int]`; `fit_duration(sentences, first, last, *, min_s, max_s) -> tuple[int, int] | None`; `clip_times(sentences, first, last, duration_s, *, lead_s=0.15, tail_s=0.35) -> tuple[float, float]`; `temporal_iou(a, b) -> float`; `dedupe(items, *, span, score, threshold=0.5) -> list`.
  - `SUB_SCORES`, `WEIGHTS`, `clamp_sub_scores(raw) -> dict[str, int]`, `base_score(sub, content_type) -> float`, `virality_score(sub, content_type, *, energy=0.0, rerank_position=None, rerank_total=0, self_contained=True) -> int` (1–99).
  - `HOP_S = 0.5`; `rms_envelope_wav(path, hop_s=HOP_S) -> np.ndarray` (dB per hop); `energy_score(envelope_db, start_s, end_s, hop_s=HOP_S) -> float` (0–1).

- [ ] **Step 1: Add dependency**

Run: `uv add "rapidfuzz>=3.14"`

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_analysis_logic.py`:
```python
import numpy as np
import pytest

from app.analysis.align import align_quote
from app.analysis.chunks import chunk_sentences, render_chunk
from app.analysis.energy import energy_score, rms_envelope_wav
from app.analysis.scoring import SUB_SCORES, base_score, clamp_sub_scores, virality_score
from app.analysis.windows import clip_times, dedupe, expand_to_sentences, fit_duration, temporal_iou
from app.pipeline.transcript import Word, build_sentences
from tests.builders import make_transcript, write_wav


def words_of(text: str) -> list[Word]:
    return [Word(text=" " + tok, start=i * 0.5, end=i * 0.5 + 0.4) for i, tok in enumerate(text.split())]


# ---------- alignment ----------
WORDS = words_of("Hello, world. The quick brown fox jumps over the lazy dog! Then it slept for three hours.")


@pytest.mark.parametrize("quote", [
    "the quick brown fox",
    "THE QUICK, brown fox",
    "the quick brown fox jumps",
    "quick brown fox jumps over",
])
def test_align_quote_tolerates_case_and_punctuation(quote):
    span = align_quote(WORDS, quote)
    assert span is not None
    assert "quick" in "".join(w.text for w in WORDS[span[0]:span[1]])


def test_align_quote_exact_indices():
    assert align_quote(WORDS, "the quick brown fox") == (2, 6)


def test_align_quote_survives_a_dropped_word():
    span = align_quote(WORDS, "the quick brown fox jumps over lazy dog")
    assert span is not None and span[0] == 2


def test_align_quote_rejects_unrelated_text():
    assert align_quote(WORDS, "completely different sentence about taxes") is None
    assert align_quote(WORDS, "") is None


def test_align_quote_respects_window():
    assert align_quote(WORDS, "the quick brown fox", lo=8) is None
    assert align_quote(WORDS, "the lazy dog", lo=8) == (8, 11)


def test_align_quote_cjk_and_hindi():
    cjk = [Word(text=t, start=i, end=i + 0.5) for i, t in enumerate(["你好", "。", "世界", "很", "大", "。"])]
    assert align_quote(cjk, "世界很大") == (2, 5)
    hindi = [Word(text=" " + t, start=i, end=i + 0.5) for i, t in enumerate("आज हम आदतों के बारे में बात करेंगे।".split())]
    assert align_quote(hindi, "आदतों के बारे में") == (2, 6)


# ---------- chunks ----------
def test_chunk_sentences_windows_with_overlap():
    t = make_transcript([f"Sentence number {i} here." for i in range(400)], sentence_s=3.0, gap_s=0.0)
    chunks = chunk_sentences(t.sentences, window_s=300, overlap_s=30)
    assert chunks[0].first_sentence == 0 and chunks[-1].last_sentence == len(t.sentences) - 1
    for a, b in zip(chunks, chunks[1:]):
        assert b.first_sentence <= a.last_sentence
        assert t.sentences[a.last_sentence].end - t.sentences[b.first_sentence].start >= 30 - 3
        assert a.end_s - a.start_s <= 300
    assert len(chunk_sentences(t.sentences[:5])) == 1
    assert chunk_sentences([]) == []


def test_render_chunk_lines():
    t = make_transcript(["Hello there.", "General Kenobi."])
    [chunk] = chunk_sentences(t.sentences)
    text = render_chunk(t.sentences, chunk, ["A", None])
    assert text.splitlines() == ["[S0] (0:00) A: Hello there.", "[S1] (0:03) General Kenobi."]


# ---------- windows ----------
T = make_transcript([f"This is sentence {i}." for i in range(40)], sentence_s=3.0, gap_s=0.2)  # 3.2 s per sentence


def test_expand_to_sentences():
    s = T.sentences
    assert expand_to_sentences(s, s[3].word_start + 1, s[5].word_end - 1) == (3, 5)


def test_fit_duration_grows_and_shrinks():
    s = T.sentences
    first, last = fit_duration(s, 10, 10, min_s=15, max_s=30)
    assert 15 <= s[last].end - s[first].start <= 30 and first == 10
    first, last = fit_duration(s, 0, 30, min_s=15, max_s=30)
    assert first == 0 and s[last].end - s[first].start <= 30
    first, last = fit_duration(s, 38, 39, min_s=15, max_s=30)  # near the end: grows backwards
    assert s[last].end - s[first].start >= 15
    assert fit_duration(s[:2], 0, 1, min_s=30, max_s=60) is None


def test_clip_times_pads_without_eating_neighbours():
    s = T.sentences
    start, end = clip_times(s, 5, 8, T.duration_s)
    assert s[4].end < start <= s[5].start and s[8].end <= end < s[9].start
    start0, _ = clip_times(s, 0, 2, T.duration_s)
    assert start0 == 0.0


def test_iou_and_dedupe():
    assert temporal_iou((0, 10), (0, 10)) == 1.0
    assert temporal_iou((0, 10), (20, 30)) == 0.0
    assert temporal_iou((0, 10), (5, 15)) == pytest.approx(5 / 15)
    items = [("a", (0, 30), 50), ("b", (2, 31), 80), ("c", (40, 70), 60), ("d", (25, 55), 70)]
    kept = dedupe(items, span=lambda x: x[1], score=lambda x: x[2])
    assert [k[0] for k in kept] == ["b", "d", "c"]


# ---------- scoring ----------
def test_clamp_and_score_bounds():
    sub = clamp_sub_scores({"hook": 14, "emotion": -3, "novelty": 6.6})
    assert sub == {"hook": 10, "emotion": 0, "novelty": 7, "value": 0, "shareability": 0, "loop": 0}
    top = {k: 10 for k in SUB_SCORES}
    assert virality_score(top, "podcast", energy=1.0, rerank_position=0, rerank_total=10) == 99
    assert virality_score({k: 0 for k in SUB_SCORES}, "podcast", rerank_position=9, rerank_total=10, self_contained=False) == 1
    assert base_score(top, "gaming") == pytest.approx(100.0)


def test_rerank_and_audio_move_scores():
    mid = {k: 6 for k in SUB_SCORES}
    first = virality_score(mid, "talking_head", rerank_position=0, rerank_total=5)
    last = virality_score(mid, "talking_head", rerank_position=4, rerank_total=5)
    assert first > last
    assert virality_score(mid, "gaming", energy=1.0) > virality_score(mid, "gaming", energy=0.0)
    assert virality_score(mid, "unknown-type") == virality_score(mid, "other")


# ---------- energy ----------
def test_energy_prefers_loud_spans(tmp_path):
    sr = 16000
    samples = np.random.default_rng(1).normal(0, 0.02, sr * 60).astype(np.float32)
    samples[sr * 30: sr * 40] *= 20
    path = tmp_path / "e.wav"
    write_wav(path, samples, sr)
    env = rms_envelope_wav(path)
    assert len(env) == 120
    assert energy_score(env, 30, 40) > 0.8
    assert energy_score(env, 0, 10) < 0.2
    assert energy_score(env, 200, 210) == 0.0
    assert energy_score(np.array([]), 0, 10) == 0.0
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_analysis_logic.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.analysis.align'`.

- [ ] **Step 4: Implement**

`backend/app/analysis/align.py`:
```python
import bisect
import unicodedata
from collections.abc import Sequence

from rapidfuzz import fuzz

from app.pipeline.transcript import Word


def _norm(text: str) -> str:
    # Drop spaces and punctuation entirely so scripts with and without spaces (Latin, Devanagari, CJK)
    # compare the same way; both sides are normalized identically.
    return "".join(ch for ch in unicodedata.normalize("NFKC", text).casefold() if ch.isalnum())


def align_quote(words: Sequence[Word], quote: str, *, lo: int = 0, hi: int | None = None,
                min_score: float = 80.0) -> tuple[int, int] | None:
    """Find the word range [start, end) in words[lo:hi] that best matches `quote` (fuzzy).

    LLMs paraphrase slightly (punctuation, case, fillers, digits); we never trust their timestamps,
    so this maps their verbatim-ish quotes back onto Whisper's words.
    """
    hi = len(words) if hi is None else min(hi, len(words))
    lo = max(0, lo)
    target = _norm(quote)
    if not target or lo >= hi:
        return None
    offsets: list[int] = []
    pieces: list[str] = []
    position = 0
    for word in words[lo:hi]:
        token = _norm(word.text)
        offsets.append(position)
        pieces.append(token)
        position += len(token)
    text = "".join(pieces)
    if not text:
        return None
    if len(target) >= len(text):
        return (lo, hi) if fuzz.ratio(target, text) >= min_score else None
    alignment = fuzz.partial_ratio_alignment(target, text)
    if alignment is None or alignment.score < min_score:
        return None
    start = max(0, bisect.bisect_right(offsets, alignment.dest_start) - 1)
    end = bisect.bisect_left(offsets, alignment.dest_end)
    return lo + start, lo + max(end, start + 1)
```

`backend/app/analysis/chunks.py`:
```python
from collections.abc import Sequence

from pydantic import BaseModel

from app.pipeline.transcript import Sentence


class TranscriptChunk(BaseModel):
    index: int
    first_sentence: int
    last_sentence: int  # inclusive
    start_s: float
    end_s: float


def chunk_sentences(sentences: Sequence[Sentence], *, window_s: float = 720.0,
                    overlap_s: float = 60.0) -> list[TranscriptChunk]:
    chunks: list[TranscriptChunk] = []
    i, n = 0, len(sentences)
    while i < n:
        start_s = sentences[i].start
        j = i
        while j + 1 < n and sentences[j + 1].end - start_s <= window_s:
            j += 1
        chunks.append(TranscriptChunk(index=len(chunks), first_sentence=i, last_sentence=j,
                                      start_s=start_s, end_s=sentences[j].end))
        if j == n - 1:
            break
        k = j
        while k > i and sentences[j].end - sentences[k].start < overlap_s:
            k -= 1
        i = max(k, i + 1)
    return chunks


def mmss(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 3600}:{total % 3600 // 60:02d}:{total % 60:02d}" if total >= 3600 else f"{total // 60}:{total % 60:02d}"


def render_chunk(sentences: Sequence[Sentence], chunk: TranscriptChunk,
                 speakers: Sequence[str | None] | None = None) -> str:
    lines = []
    for s in sentences[chunk.first_sentence:chunk.last_sentence + 1]:
        who = f"{speakers[s.id]}: " if speakers and speakers[s.id] else ""
        lines.append(f"[S{s.id}] ({mmss(s.start)}) {who}{s.text}")
    return "\n".join(lines)
```

`backend/app/analysis/windows.py`:
```python
import bisect
from collections.abc import Callable, Sequence
from typing import TypeVar

from app.pipeline.transcript import Sentence

Item = TypeVar("Item")


def sentence_of_word(sentences: Sequence[Sentence], word_index: int) -> int:
    starts = [s.word_start for s in sentences]
    return max(0, min(len(sentences) - 1, bisect.bisect_right(starts, word_index) - 1))


def expand_to_sentences(sentences: Sequence[Sentence], start_word: int, end_word: int) -> tuple[int, int]:
    """Whole sentences covering words [start_word, end_word)."""
    return sentence_of_word(sentences, start_word), sentence_of_word(sentences, max(start_word, end_word - 1))


def fit_duration(sentences: Sequence[Sentence], first: int, last: int, *, min_s: float,
                 max_s: float) -> tuple[int, int] | None:
    def length(a: int, b: int) -> float:
        return sentences[b].end - sentences[a].start

    while length(first, last) < min_s and last + 1 < len(sentences) and length(first, last + 1) <= max_s:
        last += 1
    while length(first, last) < min_s and first > 0 and length(first - 1, last) <= max_s:
        first -= 1
    while length(first, last) > max_s and last > first:
        last -= 1
    duration = length(first, last)
    if duration > max_s or duration < min_s * 0.6:
        return None
    return first, last


def clip_times(sentences: Sequence[Sentence], first: int, last: int, duration_s: float, *,
               lead_s: float = 0.15, tail_s: float = 0.35) -> tuple[float, float]:
    start = max(0.0, sentences[first].start - lead_s)
    end = min(duration_s, sentences[last].end + tail_s)
    if first > 0:
        start = max(start, min(sentences[first].start, sentences[first - 1].end + 0.05))
    if last + 1 < len(sentences):
        end = min(end, max(sentences[last].end, sentences[last + 1].start - 0.05))
    return round(start, 3), round(end, 3)


def temporal_iou(a: tuple[float, float], b: tuple[float, float]) -> float:
    inter = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    union = max(a[1], b[1]) - min(a[0], b[0])
    return inter / union if union > 0 else 0.0


def dedupe(items: Sequence[Item], *, span: Callable[[Item], tuple[float, float]],
           score: Callable[[Item], float], threshold: float = 0.5) -> list[Item]:
    kept: list[Item] = []
    for item in sorted(items, key=score, reverse=True):
        if all(temporal_iou(span(item), span(other)) <= threshold for other in kept):
            kept.append(item)
    return kept
```

`backend/app/analysis/scoring.py`:
```python
from collections.abc import Mapping

SUB_SCORES = ("hook", "emotion", "novelty", "value", "shareability", "loop")

WEIGHTS: dict[str, dict[str, float]] = {
    "podcast":         {"hook": .25, "emotion": .20, "novelty": .15, "value": .15, "shareability": .15, "loop": .10},
    "talking_head":    {"hook": .25, "emotion": .10, "novelty": .15, "value": .25, "shareability": .15, "loop": .10},
    "screen_tutorial": {"hook": .20, "emotion": .05, "novelty": .15, "value": .35, "shareability": .15, "loop": .10},
    "gaming":          {"hook": .20, "emotion": .30, "novelty": .15, "value": .05, "shareability": .20, "loop": .10},
    "vlog":            {"hook": .25, "emotion": .25, "novelty": .15, "value": .10, "shareability": .15, "loop": .10},
    "other":           {"hook": .25, "emotion": .15, "novelty": .15, "value": .20, "shareability": .15, "loop": .10},
}
AUDIO_POINTS = {"gaming": 10.0, "vlog": 6.0}  # hype moments matter more where the transcript can't show them
DEFAULT_AUDIO_POINTS = 3.0
RERANK_SPREAD = 6.0
NOT_SELF_CONTAINED_PENALTY = 8.0


def clamp_sub_scores(raw: Mapping[str, float]) -> dict[str, int]:
    return {k: int(max(0, min(10, round(float(raw.get(k, 0)))))) for k in SUB_SCORES}


def base_score(sub: Mapping[str, int], content_type: str) -> float:
    weights = WEIGHTS.get(content_type, WEIGHTS["other"])
    return sum(weights[k] * sub.get(k, 0) for k in SUB_SCORES) * 10.0


def virality_score(sub: Mapping[str, int], content_type: str, *, energy: float = 0.0,
                   rerank_position: int | None = None, rerank_total: int = 0, self_contained: bool = True) -> int:
    score = base_score(sub, content_type) + AUDIO_POINTS.get(content_type, DEFAULT_AUDIO_POINTS) * energy
    if rerank_position is not None and rerank_total > 1:
        score += RERANK_SPREAD - 2 * RERANK_SPREAD * rerank_position / (rerank_total - 1)
    if not self_contained:
        score -= NOT_SELF_CONTAINED_PENALTY
    return int(max(1, min(99, round(score))))
```

`backend/app/analysis/energy.py`:
```python
from pathlib import Path

import numpy as np

from app.audio import iter_wav_blocks

HOP_S = 0.5
LOUDNESS_RANGE_DB = 12.0


def rms_envelope_wav(path: Path, hop_s: float = HOP_S, sample_rate: int = 16000) -> np.ndarray:
    """Loudness (dB) per hop, streamed so long videos don't load the whole WAV into memory."""
    hop = int(sample_rate * hop_s)
    values: list[float] = []
    for block in iter_wav_blocks(path, hop):
        if len(block) < hop:
            break
        values.append(float(np.sqrt(np.mean(block.astype(np.float64) ** 2))))
    return 20.0 * np.log10(np.asarray(values, dtype=np.float64) + 1e-6)


def energy_score(envelope_db: np.ndarray, start_s: float, end_s: float, hop_s: float = HOP_S) -> float:
    """0–1: how much louder the clip's peaks are than the video's typical level (hype, laughter, shouting)."""
    if envelope_db.size == 0:
        return 0.0
    a = int(start_s / hop_s)
    b = max(int(end_s / hop_s), a + 1)
    segment = envelope_db[a:b]
    if segment.size == 0:
        return 0.0
    lift = float(np.percentile(segment, 90) - np.median(envelope_db))
    return float(np.clip(lift / LOUDNESS_RANGE_DB, 0.0, 1.0))
```
> Spec §3.5 mentions "laughter/cheer detection". Ruling for this plan: a loudness-lift signal covers laughter, cheering and shouting peaks well enough for ranking; a dedicated laughter classifier is out of scope (record this in the report).

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass, zero warnings.

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/app/analysis backend/tests/test_analysis_logic.py
git commit -m "feat(analysis): add chunking, fuzzy quote alignment, sentence fitting, dedupe, scoring and loudness"
```

---

### Task 8: Analyze stage — find, score and save the moments

**Files:**
- Create: `backend/app/analysis/moments.py`, `backend/app/llm/prompts/moments.py`, `backend/app/llm/prompts/rerank.py`, `backend/app/pipeline/analyze.py`, `backend/tests/test_moments.py`, `backend/tests/test_analyze.py`
- Modify: `backend/app/media.py` (add `extract_frame`), `backend/app/workspace.py` (add `Workspace.clip_dir`), `backend/tests/conftest.py` (add `long_video` fixture)

**Interfaces:**
- Consumes: Tasks 1–7 (Clip, repo.replace_clips, ProjectOptions/project_options, RouterFactory/router_for, ContentProfile, Diarization/sentence_speakers, chunk_sentences/render_chunk/mmss, align_quote, windows, scoring, energy), Phase 1 `Transcript`, `media._run/_tool/MediaError`.
- Produces:
  - `HookType` Literal (`question, bold_claim, number, conflict, story, contrarian, reveal, humor`); LLM schemas `SubScores`, `MomentCandidate`, `MomentBatch(moments)`, `RerankItem(candidate_id, rank)`, `RerankResult(ranking)`.
  - `ScoredCandidate` (internal); `resolve_moment(moment, *, cand_id, transcript, chunk, options, content_type, envelope) -> ScoredCandidate | None`; `rerank_positions(result, ids) -> dict[str, int]`; `finalize(candidates, positions, content_type) -> list[ScoredCandidate]`.
  - `media.extract_frame(src, at_s, dst, *, width=640) -> None`; `Workspace.clip_dir(project_id, clip_id) -> Path` (created) → thumbnail at `<clip_dir>/thumb.jpg`.
  - `AnalyzeStage(router_factory=router_for)`: `name="analyze"`, `label="Finding viral moments"`, `weight=2.5`, `uses_gpu=False`; writes `projects/<id>/analysis.json` (`AnalysisRecord`), replaces the project's `Clip` rows, thumbnails, emits `partial {kind:"clip", clip: <Clip as JSON>}` per final clip (rank order) and progress messages per chunk.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/conftest.py`:
```python
@pytest.fixture(scope="session")
def long_video(media_dir) -> Path:
    out = media_dir / "long talk.mp4"
    _ffmpeg(
        "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=5:duration=200",
        "-f", "lavfi", "-i", "sine=frequency=330:duration=200",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out),
    )
    return out
```

`backend/tests/test_moments.py`:
```python
import numpy as np

from app.analysis.chunks import chunk_sentences
from app.analysis.moments import MomentCandidate, RerankItem, RerankResult, finalize, rerank_positions, resolve_moment
from app.options import ProjectOptions
from tests.builders import make_transcript

T = make_transcript([f"Point number {i} is about something important." for i in range(60)], sentence_s=3.0, gap_s=0.2)
CHUNK = chunk_sentences(T.sentences)[0]
OPTS = ProjectOptions(min_duration_s=15, max_duration_s=30)
ENV = np.zeros(800)


def moment(**over) -> MomentCandidate:
    base = dict(
        start_sentence=10, end_sentence=14,
        start_quote="Point number 10 is about something", end_quote="number 14 is about something important.",
        hook_type="bold_claim", payoff_summary="p", self_contained=True,
        scores={"hook": 8, "emotion": 6, "novelty": 7, "value": 7, "shareability": 6, "loop": 4},
        title="  A great title  ", hook_text="one two three four five six seven eight nine ten eleven",
        why_viral="w", keywords=["a", "b", "c", "d", "e", "f", "g"], emoji=["🔥", "💡", "🚀", "✨"],
    )
    return MomentCandidate.model_validate(base | over)


def resolve(m):
    return resolve_moment(m, cand_id="c0-0", transcript=T, chunk=CHUNK, options=OPTS, content_type="talking_head", envelope=ENV)


def test_resolves_quotes_to_sentence_aligned_times():
    c = resolve(moment())
    s = T.sentences
    assert c.first_sentence == 10 and s[c.last_sentence].end - s[c.first_sentence].start <= 30
    assert s[9].end < c.start_s <= s[10].start
    assert 15 <= c.end_s - c.start_s <= 30.5
    assert c.title == "A great title" and len(c.hook_text.split()) <= 10
    assert len(c.keywords) == 6 and len(c.emoji) == 3 and 1 <= c.base <= 100


def test_garbage_quotes_fall_back_to_sentence_ids():
    c = resolve(moment(start_quote="zzz qqq", end_quote="xxx yyy"))
    assert c is not None and c.first_sentence == 10


def test_garbage_quotes_and_bad_ids_are_dropped():
    assert resolve(moment(start_quote="zzz qqq", end_quote="xxx yyy", start_sentence=500, end_sentence=501)) is None
    assert resolve(moment(start_quote="zzz qqq", end_quote="xxx yyy", start_sentence=20, end_sentence=12)) is None


def test_reversed_quotes_still_produce_a_clip():
    c = resolve(moment(start_quote="number 14 is about something important", end_quote="Point number 10 is about"))
    assert c is not None and 15 <= c.end_s - c.start_s <= 30.5


def test_rerank_positions_ignores_unknown_and_appends_missing():
    result = RerankResult(ranking=[RerankItem(candidate_id="b", rank=1), RerankItem(candidate_id="zzz", rank=2),
                                   RerankItem(candidate_id="b", rank=3), RerankItem(candidate_id="a", rank=4)])
    assert rerank_positions(result, ["a", "b", "c"]) == {"b": 0, "a": 1, "c": 2}


def test_finalize_orders_by_score_with_rerank_boost():
    a = resolve(moment())
    b = a.model_copy(update={"id": "c0-1", "start_s": a.start_s + 100, "end_s": a.end_s + 100})
    out = finalize([a, b], {"c0-1": 0, "c0-0": 1}, "talking_head")
    assert [c.id for c in out] == ["c0-1", "c0-0"] and out[0].score > out[1].score
```

`backend/tests/test_analyze.py`:
```python
import pytest

from app import repo
from app.analysis.profile import ContentProfile
from app.analysis.speakers import Diarization
from app.options import ProjectOptions
from app.pipeline.analyze import AnalyzeStage
from app.pipeline.errors import StageError
from app.pipeline.transcript import Transcript
from app.workspace import read_json
from tests.builders import fixed_router, make_transcript, prepare_video
from tests.fakes import FakeLLMProvider

PROFILE = ContentProfile(content_type="talking_head", speaker_count_estimate=1, topics=["habits"], tone="calm", summary="s")
SKIPPED = Diarization(skipped=True, reason_code="single_speaker")
TRANSCRIPT = make_transcript([f"Point number {i} is about something important." for i in range(60)], sentence_s=3.0, gap_s=0.2)


def moment(first: int, last: int, hook: int, title: str) -> dict:
    return {
        "start_sentence": first, "end_sentence": last,
        "start_quote": f"Point number {first} is about something", "end_quote": f"number {last} is about something important.",
        "hook_type": "question", "payoff_summary": "p", "self_contained": True,
        "scores": {"hook": hook, "emotion": 6, "novelty": 6, "value": 6, "shareability": 6, "loop": 5},
        "title": title, "hook_text": "Did you know this", "why_viral": "Because", "keywords": ["important"], "emoji": ["💡"],
    }


def provider(moments: list[dict], ranking: list[str] | None = None) -> FakeLLMProvider:
    def respond(schema, prompt, system):
        if schema.__name__ == "MomentBatch":
            return {"moments": moments}
        ids = ranking or [line.split()[1] for line in prompt.splitlines() if line.startswith("ID ")]
        return {"ranking": [{"candidate_id": cid, "rank": i + 1} for i, cid in enumerate(ids)]}
    return FakeLLMProvider(responses=respond)


def setup(make_ctx, long_video, options: ProjectOptions | None = None, transcript: Transcript = TRANSCRIPT):
    ctx = make_ctx(options=(options or ProjectOptions(min_duration_s=15, max_duration_s=30)).model_dump())
    prepare_video(ctx, transcript, profile=PROFILE, diarization=SKIPPED, source=long_video, loud_spans=((60, 75),))
    return ctx


def test_finds_scores_saves_and_thumbnails(make_ctx, long_video, engine, workspace, bus):
    ctx = setup(make_ctx, long_video)
    fake = provider([moment(2, 6, 5, "Early"), moment(20, 24, 9, "Loud and great"), moment(40, 44, 7, "Late")])
    stage = AnalyzeStage(router_factory=fixed_router(fake))
    assert not stage.is_done(ctx)

    stage.run(ctx)

    clips = repo.list_clips(engine, ctx.project_id)
    assert [c.rank for c in clips] == [1, 2, 3]
    assert clips[0].title == "Loud and great" and clips[0].score >= clips[1].score >= clips[2].score
    assert all(1 <= c.score <= 99 and 15 <= c.end_s - c.start_s <= 30.5 for c in clips)
    assert all((workspace.clip_dir(ctx.project_id, c.id) / "thumb.jpg").exists() for c in clips)
    efforts = {call["schema"].__name__: call["effort"] for call in fake.calls}
    assert efforts == {"MomentBatch": "high", "RerankResult": "medium"}
    partial_ids = [e.data["clip"]["id"] for e in bus.history(ctx.job_id) if e.type == "partial" and e.data["kind"] == "clip"]
    assert partial_ids == [c.id for c in clips]
    assert stage.is_done(ctx)


def test_changing_options_invalidates_and_limits_clip_count(make_ctx, long_video, engine):
    ctx = setup(make_ctx, long_video)
    fake = provider([moment(i, i + 4, 5 + (i % 4), f"M{i}") for i in range(0, 55, 6)])
    stage = AnalyzeStage(router_factory=fixed_router(fake))
    stage.run(ctx)
    assert len(repo.list_clips(engine, ctx.project_id)) == 10
    repo.update_project(engine, ctx.project_id, options=ProjectOptions(clip_count=3, min_duration_s=15, max_duration_s=30).model_dump())
    assert not stage.is_done(ctx)
    stage.run(ctx)
    assert len(repo.list_clips(engine, ctx.project_id)) == 3


def test_overlapping_moments_are_deduped(make_ctx, long_video, engine):
    ctx = setup(make_ctx, long_video)
    AnalyzeStage(router_factory=fixed_router(provider([moment(10, 14, 9, "A"), moment(11, 15, 6, "B")]))).run(ctx)
    assert [c.title for c in repo.list_clips(engine, ctx.project_id)] == ["A"]


def test_no_speech_gives_zero_clips_and_notice(make_ctx, long_video, engine, bus):
    ctx = setup(make_ctx, long_video, transcript=Transcript(language="en", duration_s=200.0))
    fake = provider([])
    AnalyzeStage(router_factory=fixed_router(fake)).run(ctx)
    assert repo.list_clips(engine, ctx.project_id) == [] and fake.calls == []
    assert any("no moments" in (e.message or "") for e in bus.history(ctx.job_id) if e.type == "log")


def test_nothing_clip_worthy_is_not_an_error(make_ctx, long_video, engine):
    ctx = setup(make_ctx, long_video)
    AnalyzeStage(router_factory=fixed_router(provider([]))).run(ctx)
    assert repo.list_clips(engine, ctx.project_id) == []
    assert read_json(ctx.workspace.project_dir(ctx.project_id) / "analysis.json")["clips"] == 0


def test_llm_failure_fails_the_stage(make_ctx, long_video):
    ctx = setup(make_ctx, long_video)
    from app.llm.base import LLMError
    bad = FakeLLMProvider(responses={"MomentBatch": [LLMError("Gemini rejected the request or API key (400).", retryable=False)]})
    with pytest.raises(StageError) as err:
        AnalyzeStage(router_factory=fixed_router(bad)).run(ctx)
    assert "Settings" in err.value.hint
```
> The `make_ctx` fixture forwards `**project_fields` to `repo.create_project`, so `options=` works once Task 1 added that parameter.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_moments.py tests/test_analyze.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.analysis.moments'`.

- [ ] **Step 3: Implement media/workspace helpers**

Append to `backend/app/media.py`:
```python
def extract_frame(src: Path, at_s: float, dst: Path, *, width: int = 640) -> None:
    """Grab one JPEG frame (used for clip thumbnails)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.stem + ".tmp" + dst.suffix)  # keep .jpg so ffmpeg picks the image muxer
    try:
        _run([
            _tool("ffmpeg"), "-y", "-v", "error", "-ss", f"{max(0.0, at_s):.3f}", "-i", str(src),
            "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "3", str(tmp),
        ])
        if not tmp.exists():
            raise MediaError(f"No frame at {at_s:.1f}s")
        os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)
```
Add to `Workspace` in `backend/app/workspace.py`:
```python
    def clip_dir(self, project_id: str, clip_id: str) -> Path:
        path = self.project_dir(project_id) / "clips" / clip_id
        path.mkdir(parents=True, exist_ok=True)
        return path
```

- [ ] **Step 4: Implement moment schemas and resolution**

`backend/app/analysis/moments.py`:
```python
from collections.abc import Sequence
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field

from app.analysis.align import align_quote
from app.analysis.chunks import TranscriptChunk
from app.analysis.energy import energy_score
from app.analysis.scoring import clamp_sub_scores, virality_score
from app.analysis.windows import clip_times, expand_to_sentences, fit_duration
from app.options import ProjectOptions
from app.pipeline.transcript import Transcript

HookType = Literal["question", "bold_claim", "number", "conflict", "story", "contrarian", "reveal", "humor"]


# ---- LLM-facing schemas: no numeric constraints, no dicts, no defaults ----
class SubScores(BaseModel):
    hook: int
    emotion: int
    novelty: int
    value: int
    shareability: int
    loop: int


class MomentCandidate(BaseModel):
    start_sentence: int
    end_sentence: int
    start_quote: str
    end_quote: str
    hook_type: HookType
    payoff_summary: str
    self_contained: bool
    scores: SubScores
    title: str
    hook_text: str
    why_viral: str
    keywords: list[str]
    emoji: list[str]


class MomentBatch(BaseModel):
    moments: list[MomentCandidate]


class RerankItem(BaseModel):
    candidate_id: str
    rank: int


class RerankResult(BaseModel):
    ranking: list[RerankItem]


# ---- internal ----
class ScoredCandidate(BaseModel):
    id: str
    start_s: float
    end_s: float
    first_sentence: int
    last_sentence: int
    title: str
    hook_text: str
    hook_type: str
    why_viral: str
    payoff_summary: str
    self_contained: bool
    sub_scores: dict[str, int]
    keywords: list[str]
    emoji: list[str]
    energy: float
    base: float
    score: int = 0
    speakers: list[str] = Field(default_factory=list)


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def _clean(items: Sequence[str], limit: int) -> list[str]:
    return [i.strip() for i in items if i and i.strip()][:limit]


def resolve_moment(moment: MomentCandidate, *, cand_id: str, transcript: Transcript, chunk: TranscriptChunk,
                   options: ProjectOptions, content_type: str, envelope: np.ndarray) -> ScoredCandidate | None:
    sentences, words = transcript.sentences, transcript.words
    ids_valid = chunk.first_sentence <= moment.start_sentence <= moment.end_sentence <= chunk.last_sentence
    lo_sent = _clamp(min(moment.start_sentence, moment.end_sentence) - 3, chunk.first_sentence, chunk.last_sentence)
    hi_sent = _clamp(max(moment.start_sentence, moment.end_sentence) + 3, chunk.first_sentence, chunk.last_sentence)
    chunk_lo, chunk_hi = sentences[chunk.first_sentence].word_start, sentences[chunk.last_sentence].word_end
    win_lo, win_hi = sentences[lo_sent].word_start, sentences[hi_sent].word_end

    start_span = (align_quote(words, moment.start_quote, lo=win_lo, hi=win_hi)
                  or align_quote(words, moment.start_quote, lo=chunk_lo, hi=chunk_hi))
    end_span = align_quote(words, moment.end_quote, lo=start_span[0] if start_span else win_lo, hi=chunk_hi)

    if start_span and end_span and end_span[1] > start_span[0]:
        first, last = expand_to_sentences(sentences, start_span[0], end_span[1])
    elif ids_valid:
        first, last = moment.start_sentence, moment.end_sentence
    else:
        return None

    fitted = fit_duration(sentences, first, last, min_s=options.min_duration_s, max_s=options.max_duration_s)
    if fitted is None:
        return None
    first, last = fitted
    start_s, end_s = clip_times(sentences, first, last, transcript.duration_s)
    sub = clamp_sub_scores(moment.scores.model_dump())
    energy = energy_score(envelope, start_s, end_s)
    return ScoredCandidate(
        id=cand_id, start_s=start_s, end_s=end_s, first_sentence=first, last_sentence=last,
        title=moment.title.strip()[:80], hook_text=" ".join(moment.hook_text.split()[:10]),
        hook_type=moment.hook_type, why_viral=moment.why_viral.strip(), payoff_summary=moment.payoff_summary.strip(),
        self_contained=moment.self_contained, sub_scores=sub,
        keywords=_clean(moment.keywords, 6), emoji=_clean(moment.emoji, 3), energy=energy,
        base=float(virality_score(sub, content_type, energy=energy, self_contained=moment.self_contained)),
    )


def rerank_positions(result: RerankResult, ids: Sequence[str]) -> dict[str, int]:
    known = set(ids)
    order: list[str] = []
    for item in sorted(result.ranking, key=lambda r: r.rank):
        if item.candidate_id in known and item.candidate_id not in order:
            order.append(item.candidate_id)
    order += [i for i in ids if i not in order]
    return {cid: position for position, cid in enumerate(order)}


def finalize(candidates: Sequence[ScoredCandidate], positions: dict[str, int], content_type: str) -> list[ScoredCandidate]:
    scored = [
        c.model_copy(update={"score": virality_score(
            c.sub_scores, content_type, energy=c.energy, rerank_position=positions.get(c.id),
            rerank_total=len(positions), self_contained=c.self_contained,
        )})
        for c in candidates
    ]
    return sorted(scored, key=lambda c: (-c.score, c.start_s))
```

- [ ] **Step 5: Implement prompts**

`backend/app/llm/prompts/moments.py`:
```python
from app.analysis.profile import ContentProfile

VERSION = "moments-v1"

SYSTEM = """You are a senior short-form video editor who has cut thousands of viral clips for YouTube Shorts, TikTok and Instagram Reels. You read a transcript excerpt and pick the moments most likely to stop the scroll and be watched to the end.

What makes a great clip:
- It opens on a hook within the first 3 seconds: a question, a bold or contrarian claim, a surprising number, conflict, the start of a story, or a reveal. No warm-up, no "so, um, anyway".
- It is self-contained: a viewer with no context understands it.
- It delivers a payoff before it ends: an answer, punchline, insight, twist or emotional peak.
- It carries emotional charge, novelty, practical value or quotability, ideally several.
- It ends cleanly on a complete thought; a bonus if the ending loops back to the opening.

Rules:
- Use only the transcript you are given. Every sentence is tagged like [S12]; refer to sentences by these numbers (start_sentence, end_sentence).
- start_quote: copy the first 6-15 words of the clip exactly as written in the transcript. end_quote: copy the last 6-15 words exactly. Do not fix grammar, translate or paraphrase.
- Respect the requested minimum and maximum clip length; timestamps are shown for guidance.
- Moments must not overlap each other.
- Scores are integers from 0 to 10 and must be honest: most moments are 4-7; reserve 9-10 for exceptional ones.
- Write title, hook_text, why_viral, payoff_summary and keywords in the same language as the transcript.
- title: at most 60 characters, curiosity-driven, never misleading. hook_text: at most 8 words, punchy, shown on screen in the first seconds.
- keywords: 3-6 words or short phrases that appear in the clip and deserve visual emphasis in captions. emoji: up to 3 relevant emoji.
- If nothing in the excerpt is clip-worthy, return an empty list."""


def build_prompt(*, profile: ContentProfile, title: str | None, chunk_text: str, min_s: int, max_s: int,
                 max_moments: int) -> str:
    topics = ", ".join(profile.topics) or "unknown"
    return f"""Video: "{title or 'Untitled'}" ({profile.content_type.replace('_', ' ')}; topics: {topics}). {profile.summary}

Find up to {max_moments} moments, each {min_s}-{max_s} seconds long.

Transcript excerpt (timestamps are m:ss from the start of the video):
{chunk_text}"""
```

`backend/app/llm/prompts/rerank.py`:
```python
from collections.abc import Sequence

from app.analysis.moments import ScoredCandidate

VERSION = "rerank-v1"

SYSTEM = """You are the final editor deciding which clips get published. Compare the candidates against each other and rank them by how likely each is to be watched to the end and shared. Prefer strong hooks, clear payoffs and clips that stand alone. Return every candidate ID exactly once; rank 1 is the best."""


def build_prompt(*, candidates: Sequence[ScoredCandidate], excerpts: dict[str, str]) -> str:
    blocks = []
    for c in candidates:
        blocks.append(
            f"ID {c.id} | {round(c.end_s - c.start_s)}s | hook: {c.hook_type}\n"
            f"Title: {c.title}\nOn-screen hook: {c.hook_text}\nWhy: {c.why_viral}\n"
            f"Excerpt: {excerpts.get(c.id, '')[:500]}"
        )
    return "Rank these candidate clips:\n\n" + "\n\n".join(blocks)
```

- [ ] **Step 6: Implement the stage**

`backend/app/pipeline/analyze.py`:
```python
import logging
import math
import shutil

from pydantic import BaseModel

from app import repo
from app.analysis.chunks import chunk_sentences, mmss, render_chunk
from app.analysis.energy import rms_envelope_wav
from app.analysis.moments import MomentBatch, RerankResult, ScoredCandidate, finalize, rerank_positions, resolve_moment
from app.analysis.profile import ContentProfile
from app.analysis.speakers import Diarization, sentence_speakers
from app.analysis.windows import dedupe
from app.llm.factory import RouterFactory, router_for
from app.llm.prompts import moments as moments_prompt
from app.llm.prompts import rerank as rerank_prompt
from app.media import MediaError, extract_frame
from app.models import Clip, Project
from app.options import ProjectOptions, project_options
from app.pipeline.context import PipelineContext
from app.pipeline.ingest import VideoMeta
from app.pipeline.transcript import Transcript, join_words
from app.workspace import atomic_write_json, read_json

logger = logging.getLogger(__name__)
MAX_RERANK = 20


class AnalysisRecord(BaseModel):
    options_fingerprint: str
    candidates_found: int
    clips: int
    providers: list[str]


class AnalyzeStage:
    name = "analyze"
    label = "Finding viral moments"
    weight = 2.5
    uses_gpu = False

    def __init__(self, router_factory: RouterFactory = router_for) -> None:
        self._router_factory = router_factory

    @staticmethod
    def _record_path(ctx: PipelineContext):
        return ctx.workspace.project_dir(ctx.project_id) / "analysis.json"

    def is_done(self, ctx: PipelineContext) -> bool:
        path = self._record_path(ctx)
        project = repo.get_project(ctx.engine, ctx.project_id)
        if project is None or not path.exists():
            return False
        record = AnalysisRecord.model_validate(read_json(path))
        return record.options_fingerprint == project_options(project).fingerprint()

    def run(self, ctx: PipelineContext) -> None:
        project = repo.get_project(ctx.engine, ctx.project_id)
        options = project_options(project)
        vp = ctx.video()
        transcript = Transcript.model_validate(read_json(vp.transcript))
        profile = ContentProfile.model_validate(read_json(vp.profile))
        meta = VideoMeta.model_validate(read_json(vp.meta))
        diarization = (Diarization.model_validate(read_json(vp.diarization)) if vp.diarization.exists()
                       else Diarization(skipped=True, reason_code="missing"))
        sentences = transcript.sentences

        if not sentences or transcript.duration_s < options.min_duration_s * 0.6:
            self._finish(ctx, project, options, [], found=0, providers=[])
            ctx.emit("log", stage=self.name,
                     message="This video is too short or has no speech, so there are no moments to clip.")
            return

        speakers = sentence_speakers(sentences, diarization.word_speakers) if diarization.word_speakers else None
        envelope = rms_envelope_wav(vp.audio)
        router = self._router_factory(ctx)
        chunks = chunk_sentences(sentences)
        per_chunk = max(3, math.ceil(options.clip_count * 1.5 / len(chunks)) + 2)

        candidates: list[ScoredCandidate] = []
        for chunk in chunks:
            ctx.check_cancelled()
            batch = router.generate_json(
                task="moments", prompt_version=moments_prompt.VERSION, system=moments_prompt.SYSTEM,
                prompt=moments_prompt.build_prompt(
                    profile=profile, title=meta.title, chunk_text=render_chunk(sentences, chunk, speakers),
                    min_s=options.min_duration_s, max_s=options.max_duration_s, max_moments=per_chunk,
                ),
                schema=MomentBatch, effort="high",
            )
            for n, moment in enumerate(batch.moments):
                resolved = resolve_moment(moment, cand_id=f"c{chunk.index}-{n}", transcript=transcript, chunk=chunk,
                                          options=options, content_type=profile.content_type, envelope=envelope)
                if resolved is not None:
                    candidates.append(resolved)
            ctx.progress(self.name, 0.75 * (chunk.index + 1) / len(chunks),
                         f"Scanned {mmss(chunk.end_s)} of {mmss(transcript.duration_s)} · {len(candidates)} candidate moments")

        found = len(candidates)
        shortlist = sorted(dedupe(candidates, span=lambda c: (c.start_s, c.end_s), score=lambda c: c.base),
                           key=lambda c: c.base, reverse=True)[:MAX_RERANK]
        positions: dict[str, int] = {}
        if len(shortlist) >= 2:
            ctx.check_cancelled()
            ctx.progress(self.name, 0.8, "Ranking the best moments…")
            excerpts = {c.id: join_words(transcript.words[sentences[c.first_sentence].word_start:
                                                           sentences[c.last_sentence].word_end]) for c in shortlist}
            ranking = router.generate_json(
                task="rerank", prompt_version=rerank_prompt.VERSION, system=rerank_prompt.SYSTEM,
                prompt=rerank_prompt.build_prompt(candidates=shortlist, excerpts=excerpts),
                schema=RerankResult, effort="medium",
            )
            positions = rerank_positions(ranking, [c.id for c in shortlist])
        final = finalize(shortlist, positions, profile.content_type)[: options.clip_count]
        if speakers:
            final = [c.model_copy(update={"speakers": sorted({s for s in speakers[c.first_sentence:c.last_sentence + 1] if s})})
                     for c in final]
        self._finish(ctx, project, options, final, found=found, providers=[p.name for p in router.providers])

    def _finish(self, ctx: PipelineContext, project: Project, options: ProjectOptions,
                final: list[ScoredCandidate], *, found: int, providers: list[str]) -> None:
        ctx.progress(self.name, 0.9, "Saving clips…")
        shutil.rmtree(ctx.workspace.project_dir(project.id) / "clips", ignore_errors=True)
        clips = repo.replace_clips(ctx.engine, project.id, [
            Clip(project_id=project.id, rank=i + 1, start_s=c.start_s, end_s=c.end_s, title=c.title,
                 hook_text=c.hook_text, hook_type=c.hook_type, why_viral=c.why_viral,
                 payoff_summary=c.payoff_summary, score=c.score, sub_scores=c.sub_scores,
                 keywords=c.keywords, emoji=c.emoji, speakers=c.speakers)
            for i, c in enumerate(final)
        ])
        source = ctx.video().find_source() if final else None
        for clip in clips:
            if source is not None:
                try:
                    extract_frame(source, (clip.start_s + clip.end_s) / 2,
                                  ctx.workspace.clip_dir(project.id, clip.id) / "thumb.jpg")
                except MediaError:
                    logger.warning("No thumbnail for clip %s", clip.id)
            ctx.emit("partial", stage=self.name, data={"kind": "clip", "clip": clip.model_dump(mode="json")})
        atomic_write_json(self._record_path(ctx), AnalysisRecord(
            options_fingerprint=options.fingerprint(), candidates_found=found, clips=len(clips), providers=providers,
        ))
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass, zero warnings.

- [ ] **Step 8: Commit**

```bash
git add backend/app/analysis/moments.py backend/app/llm/prompts backend/app/pipeline/analyze.py backend/app/media.py backend/app/workspace.py backend/tests/conftest.py backend/tests/test_moments.py backend/tests/test_analyze.py
git commit -m "feat(pipeline): add analyze stage — LLM moments, alignment, dedupe, rerank, virality scores, thumbnails"
```

---

### Task 9: Wire the stages, options and clip endpoints into the API

**Files:**
- Create: `backend/tests/test_clips_api.py`
- Modify: `backend/app/pipeline/registry.py`, `backend/app/api/schemas.py`, `backend/app/api/projects.py`, `backend/tests/test_api.py` (only if an assertion breaks because `ProjectOut` gained fields)

**Interfaces:**
- Consumes: Tasks 1, 5, 6, 8; Phase 1 API.
- Produces:
  - `default_stages_factory` → `[ingest, transcribe, classify, diarize, analyze]`.
  - `ProjectOut` gains `options: ProjectOptions` and `preview_playable: bool` (source is `.mp4/.m4v/.webm/.mov`); `project_out(engine, workspace, project)`.
  - `ClipOut` (all `Clip` fields except `created_at`).
  - `POST /api/projects` body `{url, options?: ProjectOptions}`; `POST /api/projects/upload` accepts optional form fields `clip_count`, `min_duration_s`, `max_duration_s`; 422 with a readable message on invalid options.
  - `POST /api/projects/{id}/reanalyze` body `ProjectOptions` → `ProjectOut` (409 while a job is active).
  - `GET /api/projects/{id}/clips -> list[ClipOut]`; `GET /api/clips/{id}/thumbnail` (image/jpeg, 404 if missing); `GET /api/projects/{id}/source` (the source video, HTTP Range supported).

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_clips_api.py`:
```python
import time

import pytest
from fastapi.testclient import TestClient

from app import repo
from app.main import create_app
from app.models import Clip
from tests.fakes import FakeIngestStage, FakeTranscribeStage


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings, stages_factory=lambda: [FakeIngestStage(), FakeTranscribeStage()])) as c:
        yield c


def wait_done(client, job_id):
    for _ in range(300):
        if client.get(f"/api/jobs/{job_id}").json()["status"] in ("succeeded", "failed"):
            return
        time.sleep(0.02)
    raise AssertionError("job stuck")


def test_create_with_options_and_defaults(client):
    with_opts = client.post("/api/projects", json={"url": "https://youtu.be/a", "options": {"clip_count": 5, "min_duration_s": 20, "max_duration_s": 40}}).json()
    assert with_opts["options"] == {"clip_count": 5, "min_duration_s": 20, "max_duration_s": 40}
    plain = client.post("/api/projects", json={"url": "https://youtu.be/b"}).json()
    assert plain["options"] == {"clip_count": 10, "min_duration_s": 30, "max_duration_s": 60}
    assert plain["preview_playable"] is False


def test_invalid_options_rejected(client):
    res = client.post("/api/projects", json={"url": "https://youtu.be/a", "options": {"min_duration_s": 50, "max_duration_s": 52}})
    assert res.status_code == 422


def test_upload_form_options(client, sample_video):
    with sample_video.open("rb") as f:
        res = client.post("/api/projects/upload", files={"file": ("a.mp4", f, "video/mp4")},
                          data={"clip_count": "4", "min_duration_s": "15", "max_duration_s": "25"})
    assert res.status_code == 201
    assert res.json()["options"]["clip_count"] == 4


def test_clips_listing_thumbnail_and_source(client, settings, sample_video):
    project = client.post("/api/projects", json={"url": "https://youtu.be/a"}).json()
    wait_done(client, project["latest_job"]["id"])
    services = client.app.state.services
    [clip] = repo.replace_clips(services.engine, project["id"], [Clip(
        project_id=project["id"], rank=1, start_s=1.0, end_s=31.0, title="T", hook_text="H", hook_type="question",
        why_viral="W", score=88, sub_scores={"hook": 9}, keywords=["k"], emoji=["🔥"], speakers=[],
    )])
    listed = client.get(f"/api/projects/{project['id']}/clips").json()
    assert listed[0]["id"] == clip.id and listed[0]["score"] == 88 and listed[0]["emoji"] == ["🔥"]
    assert client.get(f"/api/clips/{clip.id}/thumbnail").status_code == 404
    (services.workspace.clip_dir(project["id"], clip.id) / "thumb.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    thumb = client.get(f"/api/clips/{clip.id}/thumbnail")
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/jpeg"

    vp = services.workspace.video("fakevideo0001")
    (vp.dir / "source.mp4").write_bytes(sample_video.read_bytes())
    ranged = client.get(f"/api/projects/{project['id']}/source", headers={"Range": "bytes=0-99"})
    assert ranged.status_code == 206 and len(ranged.content) == 100
    assert client.get(f"/api/projects/{project['id']}").json()["preview_playable"] is True


def test_reanalyze_updates_options_and_starts_job(client):
    project = client.post("/api/projects", json={"url": "https://youtu.be/a"}).json()
    wait_done(client, project["latest_job"]["id"])
    res = client.post(f"/api/projects/{project['id']}/reanalyze", json={"clip_count": 3, "min_duration_s": 15, "max_duration_s": 30})
    assert res.status_code == 200
    body = res.json()
    assert body["options"]["clip_count"] == 3 and body["latest_job"]["id"] != project["latest_job"]["id"]


def test_unknown_ids_404(client):
    assert client.get("/api/projects/nope/clips").status_code == 404
    assert client.get("/api/clips/nope/thumbnail").status_code == 404
    assert client.get("/api/projects/nope/source").status_code == 404


def test_default_registry_order(settings):
    from app.pipeline.registry import default_stages_factory
    assert [s.name for s in default_stages_factory(settings)()] == ["ingest", "transcribe", "classify", "diarize", "analyze"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_clips_api.py -v`
Expected: FAIL (missing `options` in response, 404/405 for new routes, registry order).

- [ ] **Step 3: Implement**

`backend/app/pipeline/registry.py` — add imports and the three stages after `TranscribeStage(...)`:
```python
from app.pipeline.analyze import AnalyzeStage
from app.pipeline.classify import ClassifyStage
from app.pipeline.diarize import DiarizeStage
```
```python
        ClassifyStage(),
        DiarizeStage(),
        AnalyzeStage(),
```

`backend/app/api/schemas.py` — add `from app.options import ProjectOptions, project_options`, `from app.models import Clip` and `from app.workspace import Workspace`; add to `ProjectOut`:
```python
    options: ProjectOptions = ProjectOptions()
    preview_playable: bool = False
```
replace `project_out` and add `ClipOut`:
```python
PLAYABLE_SUFFIXES = {".mp4", ".m4v", ".webm", ".mov"}


def project_out(engine: Engine, workspace: Workspace, project: Project) -> ProjectOut:
    job = repo.latest_job(engine, project.id)
    out = ProjectOut.model_validate(project.model_dump(exclude={"options"}))
    out.options = project_options(project)
    out.latest_job = JobOut.model_validate(job) if job else None
    source = workspace.video(project.video_id).find_source() if project.video_id else None
    out.preview_playable = bool(source and source.suffix.lower() in PLAYABLE_SUFFIXES)
    return out


class ClipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    rank: int
    start_s: float
    end_s: float
    title: str
    hook_text: str
    hook_type: str
    why_viral: str
    payoff_summary: str
    score: int
    sub_scores: dict[str, int]
    keywords: list[str]
    emoji: list[str]
    speakers: list[str]
```
> `workspace.video(...)` creates the directory as a side effect; that is harmless (the id always exists once ingest ran).

`backend/app/api/projects.py`:
- Update every `project_out(svc.engine, project)` call to `project_out(svc.engine, svc.workspace, project)`.
- `CreateFromUrl` (in schemas) gains `options: ProjectOptions | None = None`; in `create_from_url` pass `options=(body.options or ProjectOptions()).model_dump()` to `repo.create_project`.
- `create_from_upload` gains form parameters and builds options before creating the project:
```python
from fastapi import Form
from pydantic import ValidationError

from app.options import ProjectOptions


@router.post("/projects/upload", status_code=201, response_model=ProjectOut)
async def create_from_upload(
    file: UploadFile,
    clip_count: int | None = Form(None),
    min_duration_s: int | None = Form(None),
    max_duration_s: int | None = Form(None),
    svc: Services = Depends(get_services),
) -> ProjectOut:
    provided = {k: v for k, v in {"clip_count": clip_count, "min_duration_s": min_duration_s,
                                  "max_duration_s": max_duration_s}.items() if v is not None}
    try:
        options = ProjectOptions.model_validate(provided)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors()[0]["msg"]) from exc
    # ... existing extension check, then:
    project = repo.create_project(svc.engine, source_type=SourceType.upload, original_filename=name,
                                  title=Path(name).stem, options=options.model_dump())
    # ... rest unchanged
```
- New endpoints:
```python
from fastapi.responses import FileResponse

from app.api.schemas import ClipOut


@router.post("/projects/{project_id}/reanalyze", response_model=ProjectOut)
def reanalyze_project(project_id: str, options: ProjectOptions, svc: Services = Depends(get_services)) -> ProjectOut:
    project = _get_project_or_404(svc, project_id)
    job = repo.latest_job(svc.engine, project_id)
    if job is not None and job.status not in TERMINAL_STATUSES:
        raise HTTPException(409, "This project is already processing")
    project = repo.update_project(svc.engine, project_id, options=options.model_dump())
    return _start_job(svc, project)


@router.get("/projects/{project_id}/clips", response_model=list[ClipOut])
def list_project_clips(project_id: str, svc: Services = Depends(get_services)) -> list[ClipOut]:
    _get_project_or_404(svc, project_id)
    return [ClipOut.model_validate(c) for c in repo.list_clips(svc.engine, project_id)]


@router.get("/clips/{clip_id}/thumbnail")
def clip_thumbnail(clip_id: str, svc: Services = Depends(get_services)) -> FileResponse:
    clip = repo.get_clip(svc.engine, clip_id)
    if clip is None:
        raise HTTPException(404, "Clip not found")
    path = svc.workspace.projects_dir / clip.project_id / "clips" / clip.id / "thumb.jpg"
    if not path.exists():
        raise HTTPException(404, "No thumbnail yet")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/projects/{project_id}/source")
def project_source(project_id: str, svc: Services = Depends(get_services)) -> FileResponse:
    project = _get_project_or_404(svc, project_id)
    source = svc.workspace.video(project.video_id).find_source() if project.video_id else None
    if source is None:
        raise HTTPException(404, "The video hasn't been imported yet")
    return FileResponse(source)
```
> `clip_thumbnail` builds the path without `clip_dir()` so a GET never creates directories. Starlette's `FileResponse` answers `Range` requests with 206 (verify with the test; if the installed Starlette doesn't, report it rather than hand-rolling range support).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass (fix only assertions in `test_api.py` that compared whole `ProjectOut` dicts, if any), zero warnings.

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/registry.py backend/app/api backend/tests/test_clips_api.py backend/tests/test_api.py
git commit -m "feat(api): add clip options, reanalyze, clip listing, thumbnails and source streaming; register new stages"
```

---
### Task 10: Frontend — API types and the Settings screen

**Files:**
- Create: `frontend/src/features/settings/SettingsPage.tsx`, `frontend/src/features/settings/ProviderCard.tsx`, `frontend/src/features/settings/ProviderOrder.tsx`, `frontend/src/features/settings/SettingsPage.test.tsx`
- Modify: `frontend/src/lib/types.ts`, `frontend/src/lib/api.ts`, `frontend/src/lib/api.test.ts`, `frontend/src/App.tsx`, `frontend/src/components/AppShell.tsx`, `frontend/src/test/fixtures.ts`

**Interfaces:**
- Consumes: Task 4 settings API, Task 9 project/clip API.
- Produces (TypeScript):
  - `ProjectOptions {clip_count, min_duration_s, max_duration_s}`; `Project` gains `options: ProjectOptions`, `preview_playable: boolean`.
  - `HookType` union; `SubScores`; `Clip {id, project_id, rank, start_s, end_s, title, hook_text, hook_type, why_viral, payoff_summary, score, sub_scores, keywords, emoji, speakers}`.
  - `ProviderName`; `AISettings` (mirrors `AISettingsOut`); `AISettingsUpdate = Partial<...>` (secrets: omit = keep, `""` = clear); `ProviderTestResult {ok, message, latency_ms}`.
  - `api.createFromUrl(url, options?)`, `api.upload(file, onProgress, options?)`, `api.clips(projectId)`, `api.reanalyze(projectId, options)`, `api.getAISettings()`, `api.saveAISettings(update)`, `api.testProvider(provider)`; `clipThumbnailUrl(clipId)`, `projectSourceUrl(projectId)`.
  - Route `/settings` → `SettingsPage` (default export); AppShell nav link "Settings".
  - Fixtures: `makeClip(overrides)`, `makeAISettings(overrides)`; `makeProject` gains `options` + `preview_playable`.

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/test/fixtures.ts`:
```ts
import type { AISettings, Clip } from "../lib/types";

export function makeClip(overrides: Partial<Clip> = {}): Clip {
  return {
    id: "c1", project_id: "p1", rank: 1, start_s: 62, end_s: 101, title: "Why procrastinators wait",
    hook_text: "Nobody talks about this", hook_type: "bold_claim", why_viral: "Relatable confession with a twist.",
    payoff_summary: "The monkey takes the wheel.", score: 91,
    sub_scores: { hook: 9, emotion: 8, novelty: 7, value: 6, shareability: 9, loop: 5 },
    keywords: ["monkey", "deadline"], emoji: ["🐒"], speakers: [],
    ...overrides,
  };
}

export function makeAISettings(overrides: Partial<AISettings> = {}): AISettings {
  return {
    provider_order: ["anthropic", "gemini", "openai", "ollama"],
    anthropic_api_key: null, anthropic_model: "claude-opus-5-5",
    gemini_api_key: "••••1234", gemini_model: "gemini-2.5-flash",
    openai_api_key: null, openai_model: "gpt-5-mini",
    ollama_enabled: false, ollama_base_url: "http://localhost:11434/v1", ollama_model: "qwen3:4b",
    hf_token: null, configured_providers: ["gemini"],
    ...overrides,
  };
}
```
and add `options: { clip_count: 10, min_duration_s: 30, max_duration_s: 60 }, preview_playable: false,` to `makeProject`'s defaults.

Append to `frontend/src/lib/api.test.ts` (inside the `describe`):
```ts
  it("sends clip options with createFromUrl", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ id: "p1" }, 201));
    vi.stubGlobal("fetch", fetchMock);
    await api.createFromUrl("https://youtu.be/x", { clip_count: 5, min_duration_s: 15, max_duration_s: 30 });
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      url: "https://youtu.be/x", options: { clip_count: 5, min_duration_s: 15, max_duration_s: 30 },
    });
  });

  it("puts partial AI settings", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}));
    vi.stubGlobal("fetch", fetchMock);
    await api.saveAISettings({ gemini_api_key: "k" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/settings/ai");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body)).toEqual({ gemini_api_key: "k" });
  });
```

`frontend/src/features/settings/SettingsPage.test.tsx`:
```tsx
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { makeAISettings } from "../../test/fixtures";
import { renderWithProviders } from "../../test/utils";
import SettingsPage from "./SettingsPage";

vi.mock("../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api")>();
  return { ...actual, api: { ...actual.api, getAISettings: vi.fn(), saveAISettings: vi.fn(), testProvider: vi.fn() } };
});

beforeEach(() => {
  vi.mocked(api.getAISettings).mockResolvedValue(makeAISettings());
  vi.mocked(api.saveAISettings).mockImplementation(async () => makeAISettings({ anthropic_api_key: "••••9999", configured_providers: ["anthropic", "gemini"] }));
  vi.mocked(api.testProvider).mockResolvedValue({ ok: true, message: "Connected to gemini-2.5-flash.", latency_ms: 420 });
});

const card = async (name: RegExp) => (await screen.findByRole("heading", { name })).closest("article")!;

it("shows saved keys masked and never asks for them again", async () => {
  renderWithProviders(<SettingsPage />, { route: "/settings", path: "/settings" });
  const gemini = await card(/google gemini/i);
  expect(within(gemini).getByText(/configured/i)).toBeInTheDocument();
  expect(within(gemini).getByLabelText(/api key/i)).toHaveAttribute("placeholder", expect.stringContaining("••••1234"));
  expect(within(gemini).getByLabelText(/api key/i)).toHaveValue("");
});

it("saves only what changed", async () => {
  const user = userEvent.setup();
  renderWithProviders(<SettingsPage />, { route: "/settings", path: "/settings" });
  const claude = await card(/claude/i);
  await user.type(within(claude).getByLabelText(/api key/i), "sk-ant-new-9999");
  await user.click(screen.getByRole("button", { name: /save changes/i }));
  await waitFor(() => expect(api.saveAISettings).toHaveBeenCalledWith({ anthropic_api_key: "sk-ant-new-9999" }));
  expect(await screen.findByText(/saved/i)).toBeInTheDocument();
});

it("removing a key sends an empty string", async () => {
  const user = userEvent.setup();
  renderWithProviders(<SettingsPage />, { route: "/settings", path: "/settings" });
  const gemini = await card(/google gemini/i);
  await user.click(within(gemini).getByRole("button", { name: /remove key/i }));
  await user.click(screen.getByRole("button", { name: /save changes/i }));
  await waitFor(() => expect(api.saveAISettings).toHaveBeenCalledWith({ gemini_api_key: "" }));
});

it("reorders the fallback chain", async () => {
  const user = userEvent.setup();
  renderWithProviders(<SettingsPage />, { route: "/settings", path: "/settings" });
  await user.click(await screen.findByRole("button", { name: /move google gemini up/i }));
  await user.click(screen.getByRole("button", { name: /save changes/i }));
  await waitFor(() => expect(api.saveAISettings).toHaveBeenCalledWith({ provider_order: ["gemini", "anthropic", "openai", "ollama"] }));
});

it("tests a saved provider and shows the result", async () => {
  const user = userEvent.setup();
  renderWithProviders(<SettingsPage />, { route: "/settings", path: "/settings" });
  const gemini = await card(/google gemini/i);
  await user.click(within(gemini).getByRole("button", { name: /test connection/i }));
  expect(await within(gemini).findByText(/connected to gemini-2.5-flash/i)).toBeInTheDocument();
  expect(api.testProvider).toHaveBeenCalledWith("gemini");
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/features/settings src/lib/api.test.ts`
Expected: FAIL — cannot resolve `./SettingsPage`; `api.saveAISettings` is not a function.

- [ ] **Step 3: Types and API client**

Append to `frontend/src/lib/types.ts`:
```ts
export interface ProjectOptions {
  clip_count: number;
  min_duration_s: number;
  max_duration_s: number;
}

export type HookType = "question" | "bold_claim" | "number" | "conflict" | "story" | "contrarian" | "reveal" | "humor";

export interface SubScores {
  hook: number;
  emotion: number;
  novelty: number;
  value: number;
  shareability: number;
  loop: number;
}

export interface Clip {
  id: string;
  project_id: string;
  rank: number;
  start_s: number;
  end_s: number;
  title: string;
  hook_text: string;
  hook_type: HookType;
  why_viral: string;
  payoff_summary: string;
  score: number;
  sub_scores: SubScores;
  keywords: string[];
  emoji: string[];
  speakers: string[];
}

export type ProviderName = "anthropic" | "gemini" | "openai" | "ollama";

export interface AISettings {
  provider_order: ProviderName[];
  anthropic_api_key: string | null;
  anthropic_model: string;
  gemini_api_key: string | null;
  gemini_model: string;
  openai_api_key: string | null;
  openai_model: string;
  ollama_enabled: boolean;
  ollama_base_url: string;
  ollama_model: string;
  hf_token: string | null;
  configured_providers: ProviderName[];
}

/** Secrets: omit to keep the saved value, "" to remove it. */
export type AISettingsUpdate = Partial<{
  provider_order: ProviderName[];
  anthropic_api_key: string;
  anthropic_model: string;
  gemini_api_key: string;
  gemini_model: string;
  openai_api_key: string;
  openai_model: string;
  ollama_enabled: boolean;
  ollama_base_url: string;
  ollama_model: string;
  hf_token: string;
}>;

export interface ProviderTestResult {
  ok: boolean;
  message: string;
  latency_ms: number;
}
```
and add to `Project`: `options: ProjectOptions;` and `preview_playable: boolean;`.

In `frontend/src/lib/api.ts`: import the new types; change `upload` to accept `options?: ProjectOptions` and append them to the form (`form.append("clip_count", String(options.clip_count))` etc. when provided); change/add in `api`:
```ts
  createFromUrl: (url: string, options?: ProjectOptions) =>
    request<Project>("/projects", { method: "POST", body: JSON.stringify({ url, options }) }),
  clips: (projectId: string) => request<Clip[]>(`/projects/${projectId}/clips`),
  reanalyze: (projectId: string, options: ProjectOptions) =>
    request<Project>(`/projects/${projectId}/reanalyze`, { method: "POST", body: JSON.stringify(options) }),
  getAISettings: () => request<AISettings>("/settings/ai"),
  saveAISettings: (update: AISettingsUpdate) =>
    request<AISettings>("/settings/ai", { method: "PUT", body: JSON.stringify(update) }),
  testProvider: (provider: ProviderName) =>
    request<ProviderTestResult>("/settings/ai/test", { method: "POST", body: JSON.stringify({ provider }) }),
```
and export:
```ts
export const clipThumbnailUrl = (clipId: string) => `${BASE}/clips/${clipId}/thumbnail`;
export const projectSourceUrl = (projectId: string) => `${BASE}/projects/${projectId}/source`;
```
The existing `api.upload(file, onProgress)` signature stays valid (options optional).

- [ ] **Step 4: Settings components**

`frontend/src/features/settings/ProviderCard.tsx`:
```tsx
import clsx from "clsx";
import { Check, ExternalLink, LoaderCircle, X } from "lucide-react";
import { useMutation } from "@tanstack/react-query";
import { useId } from "react";
import { api } from "../../lib/api";
import type { AISettings, AISettingsUpdate, ProviderName } from "../../lib/types";

export interface ProviderMeta {
  name: ProviderName;
  label: string;
  help: string;
  link: string;
  linkLabel: string;
  keyField?: "anthropic_api_key" | "gemini_api_key" | "openai_api_key";
  modelField: "anthropic_model" | "gemini_model" | "openai_model" | "ollama_model";
}

export const PROVIDERS: ProviderMeta[] = [
  { name: "anthropic", label: "Claude (Anthropic)", help: "The sharpest judge of what will go viral.", link: "https://console.anthropic.com/settings/keys", linkLabel: "Get a Claude key", keyField: "anthropic_api_key", modelField: "anthropic_model" },
  { name: "gemini", label: "Google Gemini", help: "Fast, with a generous free tier.", link: "https://aistudio.google.com/apikey", linkLabel: "Get a free Gemini key", keyField: "gemini_api_key", modelField: "gemini_model" },
  { name: "openai", label: "OpenAI", help: "GPT models via your OpenAI account.", link: "https://platform.openai.com/api-keys", linkLabel: "Get an OpenAI key", keyField: "openai_api_key", modelField: "openai_model" },
  { name: "ollama", label: "Ollama (on this PC)", help: "Free and private. Small local models pick weaker moments.", link: "https://ollama.com/download", linkLabel: "Install Ollama", modelField: "ollama_model" },
];

const inputClass = "w-full rounded-xl border border-border bg-bg/60 px-3 py-2.5 text-sm outline-none transition placeholder:text-muted focus:border-violet-brand/70 focus:ring-2 focus:ring-violet-brand/20";

export function SecretField({ label, saved, value, onChange }: {
  label: string; saved: string | null; value: string | undefined; onChange: (next: string | undefined) => void;
}) {
  const id = useId();
  const removing = value === "" && saved !== null;
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-xs font-medium text-muted">{label}</label>
      <div className="flex gap-2">
        <input
          id={id} type="password" autoComplete="off" spellCheck={false} className={inputClass}
          value={removing ? "" : value ?? ""} disabled={removing}
          placeholder={saved ? `Saved (${saved}) · type to replace` : "Paste your key"}
          onChange={(e) => onChange(e.target.value === "" ? undefined : e.target.value)}
        />
        {saved !== null && (
          <button type="button" onClick={() => onChange(removing ? undefined : "")}
            className="shrink-0 rounded-xl border border-border px-3 text-xs text-muted transition hover:bg-surface-2 hover:text-fg">
            {removing ? "Undo" : "Remove key"}
          </button>
        )}
      </div>
      {removing && <p className="mt-1 text-xs text-red-400">This key will be removed when you save.</p>}
    </div>
  );
}

export function ProviderCard({ meta, settings, draft, onChange }: {
  meta: ProviderMeta; settings: AISettings; draft: AISettingsUpdate; onChange: (patch: AISettingsUpdate) => void;
}) {
  const modelId = useId();
  const configured = settings.configured_providers.includes(meta.name);
  const touched = Object.keys(draft).some((k) => k.startsWith(meta.name));
  const test = useMutation({ mutationFn: () => api.testProvider(meta.name) });
  const model = (draft[meta.modelField] as string | undefined) ?? settings[meta.modelField];

  return (
    <article className="rounded-2xl border border-border bg-surface p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-display text-lg font-semibold">{meta.label}</h3>
          <p className="mt-1 text-sm text-muted">{meta.help}</p>
        </div>
        <span className={clsx("rounded-full px-2.5 py-1 text-xs font-medium",
          configured ? "bg-emerald-500/15 text-emerald-400" : "bg-surface-2 text-muted")}>
          {configured ? "Configured" : "Not set up"}
        </span>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {meta.keyField ? (
          <SecretField label="API key" saved={settings[meta.keyField]} value={draft[meta.keyField] as string | undefined}
            onChange={(next) => onChange({ [meta.keyField!]: next })} />
        ) : (
          <label className="flex items-center gap-3 self-end rounded-xl border border-border px-3 py-2.5 text-sm">
            <input type="checkbox" className="size-4 accent-violet-500"
              checked={draft.ollama_enabled ?? settings.ollama_enabled}
              onChange={(e) => onChange({ ollama_enabled: e.target.checked })} />
            Use Ollama
          </label>
        )}
        <div>
          <label htmlFor={modelId} className="mb-1.5 block text-xs font-medium text-muted">Model</label>
          <input id={modelId} className={inputClass} value={model} spellCheck={false}
            onChange={(e) => onChange({ [meta.modelField]: e.target.value })} />
        </div>
        {meta.name === "ollama" && (
          <div className="sm:col-span-2">
            <label className="mb-1.5 block text-xs font-medium text-muted" htmlFor={`${modelId}-url`}>Server URL</label>
            <input id={`${modelId}-url`} className={inputClass} value={draft.ollama_base_url ?? settings.ollama_base_url}
              onChange={(e) => onChange({ ollama_base_url: e.target.value })} />
          </div>
        )}
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <a href={meta.link} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 text-xs text-violet-400 hover:underline">
          {meta.linkLabel} <ExternalLink className="size-3" aria-hidden="true" />
        </a>
        <div className="flex items-center gap-3">
          {test.data && (
            <span className={clsx("inline-flex items-center gap-1 text-xs", test.data.ok ? "text-emerald-400" : "text-red-400")}>
              {test.data.ok ? <Check className="size-3.5" /> : <X className="size-3.5" />}
              {test.data.message}{test.data.ok && ` · ${test.data.latency_ms} ms`}
            </span>
          )}
          <button type="button" disabled={!configured || touched || test.isPending} onClick={() => test.mutate()}
            title={touched ? "Save your changes first" : undefined}
            className="inline-flex items-center gap-2 rounded-xl border border-border px-3 py-2 text-xs font-medium transition hover:bg-surface-2 disabled:opacity-50">
            {test.isPending && <LoaderCircle className="size-3.5 animate-spin" />}
            Test connection
          </button>
        </div>
      </div>
    </article>
  );
}
```

`frontend/src/features/settings/ProviderOrder.tsx`:
```tsx
import clsx from "clsx";
import { ArrowDown, ArrowUp } from "lucide-react";
import { motion } from "motion/react";
import type { ProviderName } from "../../lib/types";
import { PROVIDERS } from "./ProviderCard";

const labelOf = (name: ProviderName) => PROVIDERS.find((p) => p.name === name)!.label;

export function ProviderOrder({ order, configured, onChange }: {
  order: ProviderName[]; configured: ProviderName[]; onChange: (next: ProviderName[]) => void;
}) {
  const move = (index: number, delta: number) => {
    const next = [...order];
    [next[index], next[index + delta]] = [next[index + delta], next[index]];
    onChange(next);
  };
  return (
    <ol className="space-y-2">
      {order.map((name, i) => (
        <motion.li layout key={name}
          className="flex items-center gap-3 rounded-xl border border-border bg-surface px-4 py-3">
          <span className="grid size-7 place-items-center rounded-full bg-surface-2 font-mono text-xs">{i + 1}</span>
          <span className="flex-1 text-sm font-medium">{labelOf(name)}</span>
          <span className={clsx("size-2 rounded-full", configured.includes(name) ? "bg-emerald-400" : "bg-border")}
            title={configured.includes(name) ? "Configured" : "Not set up"} />
          <button type="button" aria-label={`Move ${labelOf(name)} up`} disabled={i === 0} onClick={() => move(i, -1)}
            className="grid size-8 place-items-center rounded-lg text-muted transition hover:bg-surface-2 hover:text-fg disabled:opacity-30">
            <ArrowUp className="size-4" />
          </button>
          <button type="button" aria-label={`Move ${labelOf(name)} down`} disabled={i === order.length - 1} onClick={() => move(i, 1)}
            className="grid size-8 place-items-center rounded-lg text-muted transition hover:bg-surface-2 hover:text-fg disabled:opacity-30">
            <ArrowDown className="size-4" />
          </button>
        </motion.li>
      ))}
    </ol>
  );
}
```

`frontend/src/features/settings/SettingsPage.tsx`:
```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, LoaderCircle } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { PageTransition } from "../../components/PageTransition";
import { Skeleton } from "../../components/Skeleton";
import { api } from "../../lib/api";
import type { AISettingsUpdate } from "../../lib/types";
import { PROVIDERS, ProviderCard, SecretField } from "./ProviderCard";
import { ProviderOrder } from "./ProviderOrder";

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["ai-settings"], queryFn: api.getAISettings });
  const [draft, setDraft] = useState<AISettingsUpdate>({});
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const save = useMutation({
    mutationFn: (update: AISettingsUpdate) => api.saveAISettings(update),
    onSuccess: (data) => {
      queryClient.setQueryData(["ai-settings"], data);
      setDraft({});
      setSavedAt(Date.now());
    },
  });
  const change = (patch: AISettingsUpdate) => {
    setSavedAt(null);
    setDraft((current) => {
      const next = { ...current, ...patch };
      for (const [key, value] of Object.entries(patch)) if (value === undefined) delete next[key as keyof AISettingsUpdate];
      return next;
    });
  };
  const dirty = Object.keys(draft).length > 0;

  return (
    <PageTransition>
      <div className="mx-auto max-w-3xl px-4 pb-32 pt-10 sm:px-6 sm:pt-14">
        <p className="text-xs uppercase tracking-[0.2em] text-muted">Settings</p>
        <h1 className="mt-2 font-display text-3xl font-semibold tracking-tight sm:text-4xl">Your AI, your keys</h1>
        <p className="mt-3 max-w-xl text-muted">
          ClipForge uses an AI model to find and score the moments worth clipping. Keys stay on this computer and are only sent to the provider you choose.
        </p>

        {!query.data ? (
          <div className="mt-10 space-y-4">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-40 rounded-2xl" />)}</div>
        ) : (
          <>
            <section className="mt-10" aria-labelledby="providers-heading">
              <h2 id="providers-heading" className="mb-4 font-display text-xl font-semibold">AI providers</h2>
              <div className="grid gap-4">
                {PROVIDERS.map((meta) => (
                  <ProviderCard key={meta.name} meta={meta} settings={query.data} draft={draft} onChange={change} />
                ))}
              </div>
            </section>

            <section className="mt-10" aria-labelledby="order-heading">
              <h2 id="order-heading" className="font-display text-xl font-semibold">Fallback order</h2>
              <p className="mb-4 mt-1 text-sm text-muted">ClipForge tries these from top to bottom and moves on if one fails.</p>
              <ProviderOrder order={draft.provider_order ?? query.data.provider_order}
                configured={query.data.configured_providers} onChange={(provider_order) => change({ provider_order })} />
            </section>

            <section className="mt-10 rounded-2xl border border-border bg-surface p-5" aria-labelledby="speakers-heading">
              <h2 id="speakers-heading" className="font-display text-xl font-semibold">Speaker detection</h2>
              <p className="mb-4 mt-1 text-sm text-muted">
                Optional. A free Hugging Face token lets ClipForge tell podcast speakers apart.
              </p>
              <SecretField label="Hugging Face token" saved={query.data.hf_token} value={draft.hf_token}
                onChange={(hf_token) => change({ hf_token })} />
              <a href="https://huggingface.co/pyannote/speaker-diarization-community-1" target="_blank" rel="noreferrer"
                className="mt-3 inline-flex items-center gap-1.5 text-xs text-violet-400 hover:underline">
                Accept the model terms first <ExternalLink className="size-3" aria-hidden="true" />
              </a>
            </section>
          </>
        )}
      </div>

      <AnimatePresence>
        {(dirty || savedAt || save.isError) && (
          <motion.div initial={{ y: 80, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: 80, opacity: 0 }}
            className="fixed inset-x-0 bottom-4 z-40 mx-auto flex w-[calc(100%-2rem)] max-w-3xl items-center justify-between gap-3 rounded-2xl border border-border bg-bg/90 px-4 py-3 shadow-2xl backdrop-blur-xl">
            <span role="status" className="text-sm text-muted">
              {save.isError ? <span className="text-red-400">{save.error.message}</span> : dirty ? "You have unsaved changes" : "Saved"}
            </span>
            {dirty && (
              <div className="flex gap-2">
                <button type="button" onClick={() => setDraft({})} className="rounded-xl px-3 py-2 text-sm text-muted hover:bg-surface-2">Discard</button>
                <button type="button" onClick={() => save.mutate(draft)} disabled={save.isPending}
                  className="inline-flex items-center gap-2 rounded-xl bg-fg px-4 py-2 text-sm font-semibold text-bg disabled:opacity-60">
                  {save.isPending && <LoaderCircle className="size-4 animate-spin" />}Save changes
                </button>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </PageTransition>
  );
}
```

- [ ] **Step 5: Route and nav**

`frontend/src/App.tsx`: `import SettingsPage from "./features/settings/SettingsPage";` and `<Route path="/settings" element={<SettingsPage />} />` before the `*` route.

`frontend/src/components/AppShell.tsx`: import `Settings` from `lucide-react`; between the "New project" link and the theme button add:
```tsx
            <Link to="/settings" aria-label="Settings"
              className="inline-flex items-center gap-2 rounded-full px-3 py-2 text-sm text-muted transition hover:bg-surface-2 hover:text-fg">
              <Settings className="size-4" aria-hidden="true" />
              <span className="hidden sm:inline">Settings</span>
            </Link>
```

- [ ] **Step 6: Run tests and build**

Run: `npx vitest run` → all pass, clean output. Run: `npm run build` → no type errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): add Settings screen for AI providers, fallback order and speaker detection"
```

---

### Task 11: Frontend — clip options on the Home screen

**Files:**
- Create: `frontend/src/features/home/ClipOptions.tsx`, `frontend/src/features/home/ClipOptions.test.tsx`
- Modify: `frontend/src/features/home/HomePage.tsx`, `frontend/src/features/home/DropZone.tsx`, `frontend/src/features/home/HomePage.test.tsx`

**Interfaces:**
- Consumes: Task 10 `ProjectOptions`, `api.createFromUrl(url, options)`, `api.upload(file, onProgress, options)`.
- Produces: `DEFAULT_OPTIONS`, `LENGTH_PRESETS` (`[{id:"short",15,30},{id:"medium",30,60},{id:"long",60,90}]`), `loadOptions()` / `saveOptions(options)` (localStorage key `clipforge-options`, try/catch, falls back to defaults on invalid data), `ClipOptions({value, onChange})` — a collapsible panel with a clip-count slider (3–30) and a length radio group. `DropZone` gains an `options` prop.

- [ ] **Step 1: Write the failing tests**

`frontend/src/features/home/ClipOptions.test.tsx`:
```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { ClipOptions, DEFAULT_OPTIONS, loadOptions, saveOptions } from "./ClipOptions";

beforeEach(() => localStorage.clear());

it("summarises and edits the options", async () => {
  const onChange = vi.fn();
  render(<ClipOptions value={DEFAULT_OPTIONS} onChange={onChange} />);
  const toggle = screen.getByRole("button", { name: /10 clips · 30–60 s/i });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  await userEvent.click(toggle);
  fireEvent.change(screen.getByLabelText(/number of clips/i), { target: { value: "15" } });
  expect(onChange).toHaveBeenLastCalledWith({ ...DEFAULT_OPTIONS, clip_count: 15 });
  await userEvent.click(screen.getByRole("radio", { name: /60–90 s/i }));
  expect(onChange).toHaveBeenLastCalledWith({ ...DEFAULT_OPTIONS, min_duration_s: 60, max_duration_s: 90 });
});

it("persists options and survives bad stored data", () => {
  expect(loadOptions()).toEqual(DEFAULT_OPTIONS);
  saveOptions({ clip_count: 5, min_duration_s: 15, max_duration_s: 30 });
  expect(loadOptions()).toEqual({ clip_count: 5, min_duration_s: 15, max_duration_s: 30 });
  localStorage.setItem("clipforge-options", "{nonsense");
  expect(loadOptions()).toEqual(DEFAULT_OPTIONS);
  localStorage.setItem("clipforge-options", JSON.stringify({ clip_count: 999, min_duration_s: 1, max_duration_s: 2 }));
  expect(loadOptions()).toEqual(DEFAULT_OPTIONS);
});
```

In `frontend/src/features/home/HomePage.test.tsx`: add `localStorage.clear();` to `beforeEach`; import `DEFAULT_OPTIONS` from `./ClipOptions`; change the create assertion to `toHaveBeenCalledWith("https://youtube.com/watch?v=abc", DEFAULT_OPTIONS)`; in the upload test assert `expect(api.upload).toHaveBeenCalledWith(expect.any(File), expect.any(Function), DEFAULT_OPTIONS)`; and add:
```tsx
it("sends the chosen clip options", async () => {
  vi.mocked(api.createFromUrl).mockResolvedValue(makeProject({ id: "p9" }));
  renderWithProviders(<HomePage />);
  await userEvent.click(screen.getByRole("button", { name: /10 clips/i }));
  await userEvent.click(screen.getByRole("radio", { name: /15–30 s/i }));
  await userEvent.type(screen.getByLabelText(/video link/i), "https://youtu.be/x");
  await userEvent.click(screen.getByRole("button", { name: /forge clips/i }));
  await waitFor(() => expect(api.createFromUrl).toHaveBeenCalledWith("https://youtu.be/x",
    { clip_count: 10, min_duration_s: 15, max_duration_s: 30 }));
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/features/home`
Expected: FAIL — cannot resolve `./ClipOptions`.

- [ ] **Step 3: Implement**

`frontend/src/features/home/ClipOptions.tsx`:
```tsx
import clsx from "clsx";
import { ChevronDown, SlidersHorizontal } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useId, useState } from "react";
import type { ProjectOptions } from "../../lib/types";

export const DEFAULT_OPTIONS: ProjectOptions = { clip_count: 10, min_duration_s: 30, max_duration_s: 60 };
export const LENGTH_PRESETS = [
  { id: "short", label: "15–30 s", hint: "Snappy", min: 15, max: 30 },
  { id: "medium", label: "30–60 s", hint: "Best for Shorts", min: 30, max: 60 },
  { id: "long", label: "60–90 s", hint: "Story-driven", min: 60, max: 90 },
] as const;
const KEY = "clipforge-options";

function valid(o: unknown): o is ProjectOptions {
  const v = o as ProjectOptions;
  return !!v && Number.isInteger(v.clip_count) && v.clip_count >= 3 && v.clip_count <= 30
    && v.min_duration_s >= 15 && v.max_duration_s <= 90 && v.max_duration_s >= v.min_duration_s + 5;
}

export function loadOptions(): ProjectOptions {
  try {
    const parsed = JSON.parse(localStorage.getItem(KEY) ?? "null");
    return valid(parsed) ? parsed : DEFAULT_OPTIONS;
  } catch {
    return DEFAULT_OPTIONS;
  }
}

export function saveOptions(options: ProjectOptions): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(options));
  } catch {
    /* storage unavailable — options still apply to this visit */
  }
}

export function ClipOptions({ value, onChange, className }: {
  value: ProjectOptions; onChange: (next: ProjectOptions) => void; className?: string;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <div className={clsx("w-full max-w-2xl", className)}>
      <button type="button" aria-expanded={open} aria-controls={`${id}-panel`} onClick={() => setOpen((o) => !o)}
        className="mx-auto flex items-center gap-2 rounded-full border border-border bg-surface px-4 py-1.5 text-xs text-muted backdrop-blur transition hover:text-fg">
        <SlidersHorizontal className="size-3.5" aria-hidden="true" />
        {value.clip_count} clips · {value.min_duration_s}–{value.max_duration_s} s
        <ChevronDown className={clsx("size-3.5 transition", open && "rotate-180")} aria-hidden="true" />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div id={`${id}-panel`} initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
            <div className="mt-3 grid gap-5 rounded-2xl border border-border bg-surface p-5 text-left backdrop-blur sm:grid-cols-2">
              <div>
                <div className="flex items-baseline justify-between">
                  <label htmlFor={`${id}-count`} className="text-sm font-medium">Number of clips</label>
                  <span className="font-mono text-sm text-violet-400">{value.clip_count}</span>
                </div>
                <input id={`${id}-count`} type="range" min={3} max={30} value={value.clip_count}
                  onChange={(e) => onChange({ ...value, clip_count: Number(e.target.value) })}
                  className="mt-3 w-full accent-violet-500" />
              </div>
              <div>
                <span id={`${id}-len`} className="text-sm font-medium">Clip length</span>
                <div role="radiogroup" aria-labelledby={`${id}-len`} className="mt-2 grid grid-cols-3 gap-2">
                  {LENGTH_PRESETS.map((p) => {
                    const active = value.min_duration_s === p.min && value.max_duration_s === p.max;
                    return (
                      <button key={p.id} type="button" role="radio" aria-checked={active} aria-label={p.label}
                        onClick={() => onChange({ ...value, min_duration_s: p.min, max_duration_s: p.max })}
                        className={clsx("rounded-xl border px-2 py-2 text-center transition",
                          active ? "border-violet-brand bg-violet-brand/15 text-fg" : "border-border text-muted hover:bg-surface-2")}>
                        <span className="block text-sm font-medium">{p.label}</span>
                        <span className="block text-[11px] text-muted">{p.hint}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
```

`HomePage.tsx`: `const [options, setOptions] = useState(loadOptions);` with `const updateOptions = (next) => { setOptions(next); saveOptions(next); };`; the mutation becomes `mutationFn: (url: string) => api.createFromUrl(url, options)`; render `<ClipOptions className="mt-4" value={options} onChange={updateOptions} />` directly under `<HeroInput …/>`; pass `options={options}` to `<DropZone …/>`.

`DropZone.tsx`: add prop `options?: ProjectOptions` and call `api.upload(file, setProgress, options)`.

- [ ] **Step 4: Run tests and build**

Run: `npx vitest run` → all pass, clean output. Run: `npm run build` → passes.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/home
git commit -m "feat(frontend): add clip count and length options to the home screen"
```

---

### Task 12: Frontend — live clip gallery on the project page

**Files:**
- Create: `frontend/src/features/clips/hookTypes.ts`, `frontend/src/features/clips/ScoreRing.tsx`, `frontend/src/features/clips/ClipCard.tsx`, `frontend/src/features/clips/ClipModal.tsx`, `frontend/src/features/clips/ClipGallery.tsx`, `frontend/src/features/clips/ClipGallery.test.tsx`
- Modify: `frontend/src/features/processing/jobEvents.ts`, `frontend/src/features/processing/jobEvents.test.ts`, `frontend/src/features/processing/PipelineConstellation.tsx`, `frontend/src/features/processing/ErrorPanel.tsx`, `frontend/src/features/processing/ProcessingPage.tsx`, `frontend/src/features/processing/ProcessingPage.test.tsx`

**Interfaces:**
- Consumes: Task 10 types/api (`Clip`, `api.clips`, `api.reanalyze`, `clipThumbnailUrl`, `projectSourceUrl`); Task 11 `ClipOptions`; Phase 1 processing page, reducer, `formatDuration`, `formatTimestamp`.
- Produces:
  - Reducer: `JobViewState` gains `clips: Clip[]` (partial `kind:"clip"`, deduped by id) and `profile: {content_type, speakers, topics} | null` (partial `kind:"profile"`).
  - `HOOK_LABELS: Record<HookType, string>`; `ScoreRing({score, size?})` (`role="img"`, `aria-label="Virality score N"`); `ClipCard`; `ClipModal` (`role="dialog"`, Esc closes, segment-limited player); `ClipGallery({clips, projectId, previewPlayable, segments, onReanalyze?, reanalyzing?})` with sort (Score / Timeline / Length), hook-type filter chips and an empty state.
  - Stage icons: classify `Brain`, diarize `Users`, analyze `Flame`. `ErrorPanel` shows an "Open Settings" link when the hint mentions Settings.

- [ ] **Step 1: Write the failing tests**

`frontend/src/features/clips/ClipGallery.test.tsx`:
```tsx
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { makeClip } from "../../test/fixtures";
import { ClipGallery } from "./ClipGallery";

const clips = [
  makeClip({ id: "a", rank: 1, score: 91, start_s: 300, end_s: 330, title: "Alpha", hook_type: "bold_claim" }),
  makeClip({ id: "b", rank: 2, score: 77, start_s: 10, end_s: 70, title: "Bravo", hook_type: "question" }),
  makeClip({ id: "c", rank: 3, score: 64, start_s: 120, end_s: 140, title: "Charlie", hook_type: "question" }),
];
const segments = [{ id: 0, start: 299, end: 331, text: "The monkey takes the wheel." }];
const titles = () => screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);

it("shows clips ranked by score with score rings", () => {
  render(<ClipGallery clips={clips} projectId="p1" previewPlayable={false} segments={segments} />);
  expect(titles()).toEqual(["Alpha", "Bravo", "Charlie"]);
  expect(screen.getByRole("img", { name: "Virality score 91" })).toBeInTheDocument();
  expect(screen.getByText("3 clips")).toBeInTheDocument();
});

it("sorts by timeline and length", async () => {
  render(<ClipGallery clips={clips} projectId="p1" previewPlayable={false} segments={segments} />);
  await userEvent.click(screen.getByRole("radio", { name: "Timeline" }));
  expect(titles()).toEqual(["Bravo", "Charlie", "Alpha"]);
  await userEvent.click(screen.getByRole("radio", { name: "Length" }));
  expect(titles()).toEqual(["Bravo", "Alpha", "Charlie"]);
});

it("filters by hook type", async () => {
  render(<ClipGallery clips={clips} projectId="p1" previewPlayable={false} segments={segments} />);
  await userEvent.click(screen.getByRole("button", { name: /question \(2\)/i }));
  expect(titles()).toEqual(["Bravo", "Charlie"]);
  await userEvent.click(screen.getByRole("button", { name: /all \(3\)/i }));
  expect(titles()).toHaveLength(3);
});

it("opens details with scores and excerpt, closes on Escape", async () => {
  render(<ClipGallery clips={clips} projectId="p1" previewPlayable={false} segments={segments} />);
  await userEvent.click(screen.getByRole("button", { name: /open clip alpha/i }));
  const dialog = screen.getByRole("dialog", { name: "Alpha" });
  expect(within(dialog).getByText("Relatable confession with a twist.")).toBeInTheDocument();
  expect(within(dialog).getByText("The monkey takes the wheel.")).toBeInTheDocument();
  expect(within(dialog).getByText("Hook")).toBeInTheDocument();
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("shows an empty state with a re-run action", async () => {
  const onReanalyze = vi.fn();
  render(<ClipGallery clips={[]} projectId="p1" previewPlayable={false} segments={[]} onReanalyze={onReanalyze} />);
  expect(screen.getByText(/no strong moments/i)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /try different options/i }));
  expect(screen.getByRole("button", { name: /re-run analysis/i })).toBeInTheDocument();
});
```

Append to `frontend/src/features/processing/jobEvents.test.ts` (inside the `describe`):
```ts
  it("collects live clips without duplicates and the content profile", () => {
    const clip = { id: "c1", title: "A" };
    const s = reduce(
      ev({ type: "partial", stage: "classify", data: { kind: "profile", content_type: "podcast", speakers: 2, topics: ["habits"] } }),
      ev({ type: "partial", stage: "analyze", data: { kind: "clip", clip } }),
      ev({ type: "partial", stage: "analyze", data: { kind: "clip", clip } }),
    );
    expect(s.clips.map((c) => c.id)).toEqual(["c1"]);
    expect(s.profile).toEqual({ content_type: "podcast", speakers: 2, topics: ["habits"] });
  });
```

Append to `frontend/src/features/processing/ProcessingPage.test.tsx` (extend the `vi.mock` api object with `clips: vi.fn()` and `reanalyze: vi.fn()`):
```tsx
it("shows the clip gallery when the job is done", async () => {
  vi.mocked(api.getProject).mockResolvedValue(makeProject({ title: "My Talk", latest_job: makeJob({ status: "succeeded" }) }));
  vi.mocked(api.transcript).mockResolvedValue({ language: "en", duration_s: 400, segments: [] });
  vi.mocked(api.clips).mockResolvedValue([makeClip({ title: "Best moment" })]);
  vi.mocked(useJobEvents).mockReturnValue({ ...initialJobViewState, jobStatus: "succeeded" });
  renderWithProviders(<ProcessingPage />, route);
  expect(await screen.findByRole("heading", { name: "Best moment" })).toBeInTheDocument();
});

it("links to Settings when the AI is not configured", async () => {
  vi.mocked(api.getProject).mockResolvedValue(makeProject({ latest_job: makeJob({ status: "failed" }) }));
  vi.mocked(useJobEvents).mockReturnValue({
    ...initialJobViewState, jobStatus: "failed", error: "No AI provider is set up.",
    hint: "Open Settings and add an API key (Gemini has a free tier), or enable Ollama for fully local AI.",
  });
  renderWithProviders(<ProcessingPage />, route);
  expect(await screen.findByRole("link", { name: /open settings/i })).toHaveAttribute("href", "/settings");
});
```
(import `makeClip` from the fixtures.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/features/clips src/features/processing`
Expected: FAIL — cannot resolve `./ClipGallery`; reducer has no `clips`.

- [ ] **Step 3: Reducer, icons, ErrorPanel**

`jobEvents.ts`: import `Clip`; add to `JobViewState`:
```ts
  clips: Clip[];
  profile: { content_type: string; speakers: number; topics: string[] } | null;
```
add `clips: [], profile: null` to `initialJobViewState`; in the `partial` case add:
```ts
      if (data.kind === "clip") {
        const clip = data.clip as Clip;
        return state.clips.some((c) => c.id === clip.id) ? state : { ...state, clips: [...state.clips, clip] };
      }
      if (data.kind === "profile") {
        return { ...state, profile: { content_type: String(data.content_type), speakers: Number(data.speakers),
          topics: (data.topics as string[]) ?? [] } };
      }
```

`PipelineConstellation.tsx`: import `Brain, Flame, Users` and extend `ICONS` with `classify: Brain, diarize: Users, analyze: Flame`.

`ErrorPanel.tsx`: import `Link` from `react-router` and `Settings` from `lucide-react`; under the hint render:
```tsx
          {hint?.includes("Settings") && (
            <Link to="/settings" className="mt-3 inline-flex items-center gap-1.5 text-sm font-medium text-violet-400 hover:underline">
              <Settings className="size-4" aria-hidden="true" /> Open Settings
            </Link>
          )}
```

- [ ] **Step 4: Gallery components**

`frontend/src/features/clips/hookTypes.ts`:
```ts
import type { HookType } from "../../lib/types";

export const HOOK_LABELS: Record<HookType, string> = {
  question: "Question", bold_claim: "Bold claim", number: "Surprising number", conflict: "Conflict",
  story: "Story", contrarian: "Contrarian", reveal: "Reveal", humor: "Humor",
};

export const SUB_SCORE_LABELS: [keyof import("../../lib/types").SubScores, string][] = [
  ["hook", "Hook"], ["emotion", "Emotion"], ["novelty", "Novelty"], ["value", "Value"],
  ["shareability", "Shareability"], ["loop", "Loop"],
];
```

`frontend/src/features/clips/ScoreRing.tsx`:
```tsx
import { motion } from "motion/react";
import { useId } from "react";

export function ScoreRing({ score, size = 56 }: { score: number; size?: number }) {
  const id = useId();
  const r = size / 2 - 4;
  const circumference = 2 * Math.PI * r;
  const [from, to] = score >= 85 ? ["#f97316", "#facc15"] : score >= 70 ? ["#8b5cf6", "#22d3ee"] : ["#64748b", "#94a3b8"];
  return (
    <div role="img" aria-label={`Virality score ${score}`} className="relative grid shrink-0 place-items-center"
      style={{ width: size, height: size }}>
      <svg viewBox={`0 0 ${size} ${size}`} className="absolute inset-0 -rotate-90" aria-hidden="true">
        <defs>
          <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor={from} />
            <stop offset="1" stopColor={to} />
          </linearGradient>
        </defs>
        <circle cx={size / 2} cy={size / 2} r={r} fill="rgb(7 6 13 / 0.75)" stroke="rgb(255 255 255 / 0.15)" strokeWidth="4" />
        <motion.circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={`url(#${id})`} strokeWidth="4" strokeLinecap="round"
          strokeDasharray={circumference} initial={{ strokeDashoffset: circumference }}
          animate={{ strokeDashoffset: circumference * (1 - score / 100) }} transition={{ duration: 1.1, ease: [0.22, 1, 0.36, 1] }} />
      </svg>
      <span className="relative font-display text-sm font-semibold text-white tabular-nums">{score}</span>
    </div>
  );
}
```

`frontend/src/features/clips/ClipCard.tsx`:
```tsx
import { Clock } from "lucide-react";
import { motion } from "motion/react";
import { useRef, useState } from "react";
import { formatDuration, formatTimestamp } from "../../lib/format";
import type { Clip } from "../../lib/types";
import { HOOK_LABELS } from "./hookTypes";
import { ScoreRing } from "./ScoreRing";

export function ClipCard({ clip, thumbnail, previewSrc, onOpen }: {
  clip: Clip; thumbnail: string; previewSrc: string | null; onOpen: () => void;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const [hovering, setHovering] = useState(false);
  const [thumbOk, setThumbOk] = useState(true);
  const start = () => {
    setHovering(true);
    const v = video.current;
    if (!v) return;
    v.currentTime = clip.start_s;
    void v.play().catch(() => undefined);
  };
  const stop = () => {
    setHovering(false);
    video.current?.pause();
  };
  return (
    <motion.article layout variants={{ hidden: { opacity: 0, y: 18 }, show: { opacity: 1, y: 0 } }}
      className="group overflow-hidden rounded-2xl border border-border bg-surface transition hover:-translate-y-0.5 hover:border-violet-brand/50">
      <button type="button" onClick={onOpen} onMouseEnter={start} onMouseLeave={stop} onFocus={start} onBlur={stop}
        aria-label={`Open clip ${clip.title}`} className="block w-full text-left">
        <div className="relative aspect-video overflow-hidden bg-surface-2">
          {thumbOk && (
            <img src={thumbnail} alt="" loading="lazy" onError={() => setThumbOk(false)}
              className="size-full object-cover transition duration-500 group-hover:scale-[1.03]" />
          )}
          {previewSrc && (
            <video ref={video} src={`${previewSrc}#t=${clip.start_s}`} muted playsInline preload="none"
              onTimeUpdate={(e) => { if (e.currentTarget.currentTime >= clip.end_s) e.currentTarget.currentTime = clip.start_s; }}
              className={`absolute inset-0 size-full object-cover transition-opacity duration-300 ${hovering ? "opacity-100" : "opacity-0"}`} />
          )}
          <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-transparent to-transparent" />
          <span className="absolute left-3 top-3 rounded-full bg-black/60 px-2.5 py-1 font-mono text-xs text-white backdrop-blur">#{clip.rank}</span>
          <div className="absolute right-3 top-3"><ScoreRing score={clip.score} size={52} /></div>
          <span className="absolute bottom-3 left-3 inline-flex items-center gap-1 rounded-full bg-black/60 px-2.5 py-1 text-xs text-white backdrop-blur">
            <Clock className="size-3" aria-hidden="true" />{formatDuration(clip.end_s - clip.start_s)} · {formatTimestamp(clip.start_s)}
          </span>
        </div>
        <div className="p-4">
          <span className="text-[11px] font-medium uppercase tracking-wider text-violet-400">{HOOK_LABELS[clip.hook_type] ?? clip.hook_type}</span>
          <h3 className="mt-1 line-clamp-2 font-medium leading-snug">{clip.title}</h3>
          <p className="mt-2 line-clamp-2 text-sm text-muted">“{clip.hook_text}” {clip.emoji.join(" ")}</p>
        </div>
      </button>
    </motion.article>
  );
}
```

`frontend/src/features/clips/ClipModal.tsx`:
```tsx
import { X } from "lucide-react";
import { motion } from "motion/react";
import { useEffect, useId, useRef } from "react";
import { formatDuration, formatTimestamp } from "../../lib/format";
import type { Clip } from "../../lib/types";
import { HOOK_LABELS, SUB_SCORE_LABELS } from "./hookTypes";
import { ScoreRing } from "./ScoreRing";

export function ClipModal({ clip, thumbnail, previewSrc, excerpt, onClose }: {
  clip: Clip; thumbnail: string; previewSrc: string | null; excerpt: string; onClose: () => void;
}) {
  const titleId = useId();
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <motion.div className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-4 backdrop-blur-sm"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose}>
      <motion.div role="dialog" aria-modal="true" aria-labelledby={titleId} onClick={(e) => e.stopPropagation()}
        initial={{ y: 24, scale: 0.97 }} animate={{ y: 0, scale: 1 }} exit={{ y: 24, scale: 0.97 }}
        className="max-h-[90dvh] w-full max-w-3xl overflow-y-auto rounded-3xl border border-border bg-bg shadow-2xl" data-lenis-prevent>
        <div className="relative aspect-video bg-black">
          {previewSrc ? (
            <video src={`${previewSrc}#t=${clip.start_s},${clip.end_s}`} controls autoPlay playsInline className="size-full"
              onTimeUpdate={(e) => { if (e.currentTarget.currentTime >= clip.end_s) { e.currentTarget.pause(); e.currentTarget.currentTime = clip.start_s; } }} />
          ) : (
            <img src={thumbnail} alt="" className="size-full object-cover" />
          )}
          <button ref={closeRef} type="button" onClick={onClose} aria-label="Close"
            className="absolute right-3 top-3 grid size-9 place-items-center rounded-full bg-black/60 text-white backdrop-blur hover:bg-black/80">
            <X className="size-4" />
          </button>
        </div>
        <div className="grid gap-6 p-6 sm:grid-cols-[1fr_auto]">
          <div className="min-w-0">
            <span className="text-xs font-medium uppercase tracking-wider text-violet-400">{HOOK_LABELS[clip.hook_type] ?? clip.hook_type}</span>
            <h2 id={titleId} className="mt-1 font-display text-2xl font-semibold tracking-tight">{clip.title}</h2>
            <p className="mt-2 text-sm text-muted">
              {formatTimestamp(clip.start_s)}–{formatTimestamp(clip.end_s)} · {formatDuration(clip.end_s - clip.start_s)}
              {clip.speakers.length > 0 && ` · ${clip.speakers.length} speaker${clip.speakers.length > 1 ? "s" : ""}`}
            </p>
            <p className="mt-4 rounded-xl bg-surface-2 px-4 py-3 font-display text-lg">“{clip.hook_text}” {clip.emoji.join(" ")}</p>
            <h3 className="mt-5 text-sm font-semibold">Why it can go viral</h3>
            <p className="mt-1 text-sm text-muted">{clip.why_viral}</p>
            {clip.payoff_summary && (<><h3 className="mt-4 text-sm font-semibold">Payoff</h3><p className="mt-1 text-sm text-muted">{clip.payoff_summary}</p></>)}
            {clip.keywords.length > 0 && (
              <div className="mt-4 flex flex-wrap gap-2">
                {clip.keywords.map((k) => <span key={k} className="rounded-full bg-gold/15 px-2.5 py-1 text-xs text-gold">{k}</span>)}
              </div>
            )}
            {excerpt && (<><h3 className="mt-5 text-sm font-semibold">Transcript</h3><p className="mt-1 text-sm leading-relaxed text-muted">{excerpt}</p></>)}
          </div>
          <div className="flex flex-col items-center gap-4 sm:w-48">
            <ScoreRing score={clip.score} size={96} />
            <ul className="w-full space-y-2">
              {SUB_SCORE_LABELS.map(([key, label]) => (
                <li key={key}>
                  <div className="flex justify-between text-xs"><span>{label}</span><span className="tabular-nums text-muted">{clip.sub_scores[key]}/10</span></div>
                  <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-2">
                    <motion.div className="h-full rounded-full bg-gradient-to-r from-violet-brand to-cyan-brand"
                      initial={{ width: 0 }} animate={{ width: `${clip.sub_scores[key] * 10}%` }} />
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </motion.div>
    </motion.div>
  );
}
```

`frontend/src/features/clips/ClipGallery.tsx`:
```tsx
import clsx from "clsx";
import { LoaderCircle, RotateCcw, Sparkles } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useMemo, useState } from "react";
import { clipThumbnailUrl, projectSourceUrl } from "../../lib/api";
import type { Clip, HookType, ProjectOptions, TranscriptLine } from "../../lib/types";
import { ClipOptions, DEFAULT_OPTIONS } from "../home/ClipOptions";
import { ClipCard } from "./ClipCard";
import { ClipModal } from "./ClipModal";
import { HOOK_LABELS } from "./hookTypes";

type SortKey = "score" | "timeline" | "length";
const SORTS: { key: SortKey; label: string }[] = [
  { key: "score", label: "Score" }, { key: "timeline", label: "Timeline" }, { key: "length", label: "Length" },
];
const sorters: Record<SortKey, (a: Clip, b: Clip) => number> = {
  score: (a, b) => b.score - a.score || a.rank - b.rank,
  timeline: (a, b) => a.start_s - b.start_s,
  length: (a, b) => (b.end_s - b.start_s) - (a.end_s - a.start_s),
};

export function ClipGallery({ clips, projectId, previewPlayable, segments, options, onReanalyze, reanalyzing }: {
  clips: Clip[]; projectId: string; previewPlayable: boolean; segments: TranscriptLine[];
  options?: ProjectOptions; onReanalyze?: (options: ProjectOptions) => void; reanalyzing?: boolean;
}) {
  const [sort, setSort] = useState<SortKey>("score");
  const [hook, setHook] = useState<HookType | "all">("all");
  const [openId, setOpenId] = useState<string | null>(null);
  const [rerun, setRerun] = useState(false);
  const [draft, setDraft] = useState<ProjectOptions>(options ?? DEFAULT_OPTIONS);
  const previewSrc = previewPlayable ? projectSourceUrl(projectId) : null;

  const counts = useMemo(() => clips.reduce<Record<string, number>>((acc, c) => ({ ...acc, [c.hook_type]: (acc[c.hook_type] ?? 0) + 1 }), {}), [clips]);
  const visible = useMemo(() => clips.filter((c) => hook === "all" || c.hook_type === hook).sort(sorters[sort]), [clips, hook, sort]);
  const open = clips.find((c) => c.id === openId) ?? null;
  const excerpt = open ? segments.filter((s) => s.end > open.start_s && s.start < open.end_s).map((s) => s.text).join(" ") : "";

  const rerunPanel = onReanalyze && rerun && (
    <div className="mb-6 flex flex-col items-center gap-3 rounded-2xl border border-border bg-surface p-4">
      <ClipOptions value={draft} onChange={setDraft} />
      <button type="button" disabled={reanalyzing} onClick={() => onReanalyze(draft)}
        className="inline-flex items-center gap-2 rounded-xl bg-fg px-4 py-2 text-sm font-semibold text-bg disabled:opacity-60">
        {reanalyzing ? <LoaderCircle className="size-4 animate-spin" /> : <RotateCcw className="size-4" />} Re-run analysis
      </button>
    </div>
  );

  return (
    <section className="mt-10" aria-labelledby="clips-heading">
      <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 id="clips-heading" className="font-display text-2xl font-semibold tracking-tight">Clips</h2>
          <p className="text-sm text-muted">{clips.length} clips</p>
        </div>
        {clips.length > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            <div role="radiogroup" aria-label="Sort clips" className="flex rounded-full border border-border bg-surface p-1">
              {SORTS.map((s) => (
                <button key={s.key} type="button" role="radio" aria-checked={sort === s.key} onClick={() => setSort(s.key)}
                  className={clsx("rounded-full px-3 py-1 text-xs transition", sort === s.key ? "bg-fg text-bg" : "text-muted hover:text-fg")}>
                  {s.label}
                </button>
              ))}
            </div>
            {onReanalyze && (
              <button type="button" onClick={() => setRerun((r) => !r)}
                className="rounded-full border border-border px-3 py-1.5 text-xs text-muted transition hover:bg-surface-2 hover:text-fg">
                Change options
              </button>
            )}
          </div>
        )}
      </div>

      {clips.length > 0 && (
        <div className="mb-6 flex flex-wrap gap-2">
          {(["all", ...Object.keys(counts)] as (HookType | "all")[]).map((key) => (
            <button key={key} type="button" aria-pressed={hook === key} onClick={() => setHook(key)}
              className={clsx("rounded-full border px-3 py-1 text-xs transition",
                hook === key ? "border-violet-brand bg-violet-brand/15 text-fg" : "border-border text-muted hover:text-fg")}>
              {key === "all" ? `All (${clips.length})` : `${HOOK_LABELS[key]} (${counts[key]})`}
            </button>
          ))}
        </div>
      )}

      {rerunPanel}

      {clips.length === 0 ? (
        <div className="flex flex-col items-center rounded-3xl border border-dashed border-border px-6 py-14 text-center">
          <span className="grid size-12 place-items-center rounded-2xl bg-surface-2"><Sparkles className="size-5 text-violet-400" /></span>
          <p className="mt-4 font-medium">No strong moments found</p>
          <p className="mt-1 max-w-sm text-sm text-muted">Try a different clip length — or a video with more talking.</p>
          {onReanalyze && !rerun && (
            <button type="button" onClick={() => setRerun(true)}
              className="mt-5 rounded-xl border border-border px-4 py-2 text-sm hover:bg-surface-2">Try different options</button>
          )}
        </div>
      ) : (
        <motion.div initial="hidden" animate="show" variants={{ show: { transition: { staggerChildren: 0.06 } } }}
          className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {visible.map((clip) => (
            <ClipCard key={clip.id} clip={clip} thumbnail={clipThumbnailUrl(clip.id)} previewSrc={previewSrc}
              onOpen={() => setOpenId(clip.id)} />
          ))}
        </motion.div>
      )}

      <AnimatePresence>
        {open && (
          <ClipModal clip={open} thumbnail={clipThumbnailUrl(open.id)} previewSrc={previewSrc} excerpt={excerpt}
            onClose={() => setOpenId(null)} />
        )}
      </AnimatePresence>
    </section>
  );
}
```
> In the empty-state test, `rerun` toggles on and the Re-run button renders from `rerunPanel`. `Object.keys(counts)` preserves first-seen order, so chips follow the ranking.

- [ ] **Step 5: Wire into the project page**

In `ProcessingPage.tsx`:
```tsx
const clipsQuery = useQuery({ queryKey: ["clips", projectId], queryFn: () => api.clips(projectId), enabled: status === "succeeded" });
const reanalyze = useMutation({
  mutationFn: (options: ProjectOptions) => api.reanalyze(projectId, options),
  onSuccess: (project) => {
    queryClient.setQueryData(["project", projectId], project);
    void queryClient.invalidateQueries({ queryKey: ["clips", projectId] });
  },
});
const clips = clipsQuery.data ?? view.clips;
const showGallery = status === "succeeded" || view.clips.length > 0;
```
Render, right before `<TranscriptStream …/>`:
```tsx
{showGallery && (
  <ClipGallery clips={clips} projectId={projectId} previewPlayable={project.preview_playable}
    segments={lines} options={project.options} onReanalyze={(o) => reanalyze.mutate(o)} reanalyzing={reanalyze.isPending} />
)}
```
and under the title in the header, when `view.profile` is set:
```tsx
{view.profile && (
  <p className="mt-2 text-sm text-muted">
    {view.profile.content_type.replace("_", " ")} · {view.profile.speakers} speaker{view.profile.speakers > 1 ? "s" : ""}
    {view.profile.topics.length > 0 && ` · ${view.profile.topics.slice(0, 3).join(", ")}`}
  </p>
)}
```
Also invalidate `["clips", projectId]` in the existing effect that reacts to a terminal `view.jobStatus`.

- [ ] **Step 6: Run tests and build**

Run: `npx vitest run` → all pass, clean output. Run: `npm run build` → passes.

- [ ] **Step 7: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): add live clip gallery with score rings, sorting, filters and clip details"
```

---

### Task 13: End-to-end verification with a real AI provider

**Files:**
- Modify: `README.md` (roadmap: mark Phase 2A; add "AI keys" note to Quick start), `.env.example` (add the four `CLIPFORGE_*` key lines, commented)

**Interfaces:**
- Consumes: everything above.
- Produces: verified behaviour on the real machine.

- [ ] **Step 1: Automated suites**

Run, and paste outputs into the report:
1. `cd backend; uv run pytest -q` → all pass, zero warnings.
2. `cd backend; uv run pytest -m gpu -q` → Whisper GPU test passes (and pyannote if `CLIPFORGE_HF_TOKEN` is set).
3. `cd frontend; npx vitest run; npm run build` → pass.

- [ ] **Step 2: Real provider**

Use whichever is available, in this order: a key the user placed in `.env` / Settings; otherwise local Ollama — `ollama list`; if `qwen3:4b` is missing run `ollama pull qwen3:4b`, then in Settings enable Ollama. Verify with Settings → "Test connection" (✓).

- [ ] **Step 3: Real run (API + UI running, headless Chrome via Playwright as in Phase 1's verification)**

1. Settings page renders, saving a key masks it, "Test connection" succeeds.
2. Home: open the clip options, pick 5 clips · 30–60 s, paste `https://www.youtube.com/watch?v=arj7oStGLkU` (cached from Phase 1 — ingest/transcribe show "Reused from cache").
3. Stages "Understanding content", "Identifying speakers" (skipped notice without HF token), "Finding viral moments" progress with chunk messages; clip cards fade in; 5 clips with scores, titles, hook texts in English; hover preview plays the right segment; modal shows sub-scores and the matching transcript excerpt.
4. "Change options" → 3 clips · 15–30 s → re-run; only `analyze` runs (others cached) and 3 shorter clips appear.
5. Remove all keys/disable Ollama, run a new project → job fails with "No AI provider is set up" and an "Open Settings" link.
6. Phone width (375 px): gallery cards stack, no horizontal scroll; light theme readable.
Screenshot each step; confirm no console errors.

- [ ] **Step 4: Docs and commit**

README: tick `Phase 2A — Moment engine` (add the line under the roadmap if needed) and add to Quick start: "Open **Settings** and add a Claude, Gemini or OpenAI key — or enable Ollama for fully local AI. Add a Hugging Face token to tell podcast speakers apart."

```bash
git add README.md .env.example
git commit -m "docs: document AI provider setup; complete Phase 2A moment engine"
```

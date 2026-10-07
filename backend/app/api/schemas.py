from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import Engine

from app import repo
from app.models import Clip, JobStatus, Project, SourceType


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


class SeoPack(BaseModel):
    youtube_caption: str = ""
    tiktok_caption: str = ""
    reels_caption: str = ""
    hashtags: list[str] = []
    cta: str = ""


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
    video_file: str | None
    seo: SeoPack | None = None
    created_at: datetime
    updated_at: datetime

    utc_dates = field_validator("created_at", "updated_at")(_as_utc)


def clip_out(clip: Clip, seo_data: dict[str, Any] | None = None) -> ClipOut:
    out = ClipOut.model_validate(clip)
    if seo_data:
        out.seo = SeoPack(**{k: seo_data.get(k, v) for k, v in SeoPack().model_dump().items()})
    return out


def project_out(engine: Engine, project: Project) -> ProjectOut:
    job = repo.latest_job(engine, project.id)
    out = ProjectOut.model_validate(project)
    out.latest_job = JobOut.model_validate(job) if job else None
    return out

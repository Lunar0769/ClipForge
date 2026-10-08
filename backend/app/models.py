from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Column
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
    options: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON, nullable=True))


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
    # output video and thumbnail files (relative to workspace/videos/{video_id}/), set after rendering
    video_file: str | None = None
    thumbnail_file: str | None = None
    subtitle_style: str | None = Field(default="hormozi", nullable=True)
    auto_zoom: bool | None = Field(default=True, nullable=True)
    music_mood: str | None = Field(default=None, nullable=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

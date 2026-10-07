"""All database access. Every function opens its own short session so callers
(worker threads, the event loop, request handlers) never share a Session."""

from collections.abc import Sequence

from sqlalchemy import Engine
from sqlmodel import Session, col, delete, select

from app.models import Clip, Job, JobStatus, Project, Setting, SourceType, utcnow


def _session(engine: Engine) -> Session:
    return Session(engine, expire_on_commit=False)


def create_project(
    engine: Engine,
    *,
    source_type: SourceType,
    source_url: str | None = None,
    original_filename: str | None = None,
    title: str | None = None,
    options: dict | None = None,
) -> Project:
    project = Project(
        source_type=source_type,
        source_url=source_url,
        original_filename=original_filename,
        title=title,
        options=options,
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
        s.exec(delete(Clip).where(col(Clip.project_id) == project_id))
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


def update_clip(engine: Engine, clip_id: str, **fields) -> Clip:
    with _session(engine) as s:
        clip = s.get(Clip, clip_id)
        if clip is None:
            raise KeyError(clip_id)
        for key, value in fields.items():
            setattr(clip, key, value)
        clip.updated_at = utcnow()
        s.add(clip)
        s.commit()
        return clip


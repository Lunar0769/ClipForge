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

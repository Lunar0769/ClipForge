import asyncio
import json
import os
import re
import shutil
import zipfile
from pathlib import Path
from typing import BinaryIO

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse

from app import repo
from app.api.deps import Services, get_services
from app.api.schemas import CreateFromUrl, ExportRequest, ProjectOut, project_out
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


@router.api_route("/projects/{project_id}/export", methods=["GET", "POST"])
def export_project_zip(
    project_id: str,
    body: ExportRequest | None = None,
    svc: Services = Depends(get_services),
) -> FileResponse:
    """Exports rendered Shorts with videos, thumbnails, captions, and SEO packs as a ZIP."""
    project = _get_project_or_404(svc, project_id)
    all_clips = repo.list_clips(svc.engine, project_id)
    selected_ids = set(body.clip_ids) if (body and body.clip_ids) else None

    clips_to_export = [
        c for c in all_clips
        if (selected_ids is None or c.id in selected_ids) and c.video_file
    ]
    if not clips_to_export:
        raise HTTPException(400, "No rendered clips available for export.")

    clips_dir = svc.workspace.project_dir(project_id) / "clips"
    export_dir = svc.workspace.project_dir(project_id) / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    zip_path = export_dir / f"{project.id}_shorts.zip"

    safe_p_title = re.sub(r"[^a-zA-Z0-9_\- ]+", "", project.title or "project").strip() or "clipforge"
    archive_filename = f"{safe_p_title[:30]}_shorts.zip"

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for clip in clips_to_export:
            safe_clip_title = re.sub(r"[^a-zA-Z0-9_\- ]+", "", clip.title).strip() or f"clip_{clip.rank + 1}"
            folder = f"clip_{clip.rank + 1}_{safe_clip_title[:25]}"

            # 1. MP4 Video
            vid_file = clips_dir / f"{clip.id}.mp4"
            if vid_file.exists():
                zf.write(vid_file, arcname=f"{folder}/{safe_clip_title[:40]}.mp4")

            # 2. Thumbnail
            thumb_file = clips_dir / f"{clip.id}.jpg"
            if thumb_file.exists():
                zf.write(thumb_file, arcname=f"{folder}/thumbnail.jpg")

            # 3. Subtitles
            ass_file = clips_dir / f"{clip.id}.ass"
            if ass_file.exists():
                zf.write(ass_file, arcname=f"{folder}/captions.ass")

            # 4. SEO pack
            seo_data = None
            if project.video_id:
                seo_file = svc.workspace.video(project.video_id).dir / f"seo_{clip.id}.json"
                if seo_file.exists():
                    zf.write(seo_file, arcname=f"{folder}/seo.json")
                    try:
                        seo_data = json.loads(seo_file.read_text(encoding="utf-8"))
                    except Exception:
                        pass

            # 5. Formatted ready-to-copy seo.txt
            if seo_data:
                seo_txt = (
                    f"TITLE (YouTube):\n{seo_data.get('youtube_title', clip.title)}\n\n"
                    f"DESCRIPTION (YouTube):\n{seo_data.get('youtube_description', '')}\n\n"
                    f"TIKTOK CAPTION:\n{seo_data.get('tiktok_caption', '')}\n\n"
                    f"INSTAGRAM REELS CAPTION:\n{seo_data.get('reels_caption', '')}\n\n"
                    f"HASHTAGS:\n{' '.join(seo_data.get('hashtags', []))}\n\n"
                    f"CALL TO ACTION:\n{seo_data.get('cta', '')}\n"
                )
                zf.writestr(f"{folder}/seo.txt", seo_txt)

    return FileResponse(
        path=zip_path,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{archive_filename}"'},
    )

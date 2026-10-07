"""Clips API — Phase 2 & Phase 3."""
import json
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app import repo
from app.api.deps import Services, get_services
from app.api.schemas import ClipOut, clip_out

router = APIRouter(tags=["clips"])


def _seo_data(svc: Services, clip_id: str, project_id: str) -> dict | None:
    """Load the SEO pack sidecar for a clip, return None if missing."""
    project = repo.get_project(svc.engine, project_id)
    if project is None or project.video_id is None:
        return None
    seo_path = svc.workspace.video(project.video_id).dir / f"seo_{clip_id}.json"
    if not seo_path.exists():
        return None
    try:
        return json.loads(seo_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _clip_paths(svc: Services, project_id: str, clip_id: str) -> tuple[Path, Path]:
    clips_dir = svc.workspace.project_dir(project_id) / "clips"
    return clips_dir / f"{clip_id}.mp4", clips_dir / f"{clip_id}.jpg"


@router.get("/projects/{project_id}/clips", response_model=list[ClipOut])
def list_clips(project_id: str, svc: Services = Depends(get_services)) -> list[ClipOut]:
    project = repo.get_project(svc.engine, project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    clips = repo.list_clips(svc.engine, project_id)
    return [clip_out(c, _seo_data(svc, c.id, project_id)) for c in clips]


@router.get("/clips/{clip_id}", response_model=ClipOut)
def get_clip(clip_id: str, svc: Services = Depends(get_services)) -> ClipOut:
    clip = repo.get_clip(svc.engine, clip_id)
    if clip is None:
        raise HTTPException(404, "Clip not found")
    return clip_out(clip, _seo_data(svc, clip.id, clip.project_id))


@router.get("/clips/{clip_id}/video")
def stream_clip_video(clip_id: str, svc: Services = Depends(get_services)) -> FileResponse:
    clip = repo.get_clip(svc.engine, clip_id)
    if clip is None:
        raise HTTPException(404, "Clip not found")
    video_path, _ = _clip_paths(svc, clip.project_id, clip.id)
    if not video_path.exists():
        raise HTTPException(404, "Clip video is still rendering or not available")
    return FileResponse(
        path=video_path,
        media_type="video/mp4",
        filename=f"{clip_id}.mp4",
    )


@router.get("/clips/{clip_id}/thumbnail")
def stream_clip_thumbnail(clip_id: str, svc: Services = Depends(get_services)) -> FileResponse:
    clip = repo.get_clip(svc.engine, clip_id)
    if clip is None:
        raise HTTPException(404, "Clip not found")
    _, thumb_path = _clip_paths(svc, clip.project_id, clip.id)
    if not thumb_path.exists():
        raise HTTPException(404, "Clip thumbnail not found")
    return FileResponse(
        path=thumb_path,
        media_type="image/jpeg",
        filename=f"{clip_id}.jpg",
    )


@router.get("/clips/{clip_id}/download")
def download_clip_video(clip_id: str, svc: Services = Depends(get_services)) -> FileResponse:
    clip = repo.get_clip(svc.engine, clip_id)
    if clip is None:
        raise HTTPException(404, "Clip not found")
    video_path, _ = _clip_paths(svc, clip.project_id, clip.id)
    if not video_path.exists():
        raise HTTPException(404, "Clip video is not available for download")

    safe_title = re.sub(r'[^a-zA-Z0-9_\- ]+', '', clip.title).strip() or f"clip_{clip.rank + 1}"
    safe_filename = f"{safe_title[:40]}.mp4"

    return FileResponse(
        path=video_path,
        media_type="video/mp4",
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )

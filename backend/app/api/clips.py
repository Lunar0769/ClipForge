"""Clips API — Phase 2."""
import json

from fastapi import APIRouter, Depends, HTTPException

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

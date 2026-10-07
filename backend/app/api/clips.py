"""Clips API — Phase 2 & Phase 3."""
import json
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app import repo
from app.api.deps import Services, get_services
from app.api.schemas import ClipOut, ClipRenderRequest, clip_out
from app.pipeline.captions import write_clip_ass_file
from app.pipeline.render import render_clip_video
from app.pipeline.transcript import Transcript

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


@router.post("/clips/{clip_id}/render", response_model=ClipOut)
def rerender_clip(
    clip_id: str,
    req: ClipRenderRequest = ClipRenderRequest(),
    svc: Services = Depends(get_services),
) -> ClipOut:
    """Re-renders a clip with a selected kinetic subtitle style."""
    clip = repo.get_clip(svc.engine, clip_id)
    if clip is None:
        raise HTTPException(404, "Clip not found")
    project = repo.get_project(svc.engine, clip.project_id)
    if project is None or project.video_id is None:
        raise HTTPException(404, "Project source media not found")

    vp = svc.workspace.video(project.video_id)
    src = vp.find_source()
    if src is None or not src.exists():
        raise HTTPException(404, "Source video file not found")

    clips_dir = svc.workspace.project_dir(clip.project_id) / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    video_dst = clips_dir / f"{clip.id}.mp4"
    ass_dst = clips_dir / f"{clip.id}.ass"

    # Load words if transcript exists
    words = []
    if vp.transcript.exists():
        try:
            data = json.loads(vp.transcript.read_text(encoding="utf-8"))
            transcript = Transcript.model_validate(data)
            words = transcript.words
        except Exception:
            pass

    if words:
        write_clip_ass_file(
            words=words,
            clip_start_s=clip.start_s,
            clip_end_s=clip.end_s,
            dst_path=ass_dst,
            style_name=req.subtitle_style,
            hook_text=clip.hook_text or clip.title,
        )

    # Re-render video
    video_dst.unlink(missing_ok=True)
    render_clip_video(
        src=src,
        dst=video_dst,
        start_s=clip.start_s,
        end_s=clip.end_s,
        ass_file=ass_dst if ass_dst.exists() else None,
    )

    updated = repo.update_clip(
        svc.engine,
        clip.id,
        video_file=f"clips/{clip.id}.mp4",
        subtitle_style=req.subtitle_style,
    )
    return clip_out(updated, _seo_data(svc, updated.id, updated.project_id))

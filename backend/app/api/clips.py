"""Clips API — Phase 2 & Phase 3."""
import json
import logging
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse

from app import repo
from app.api.deps import Services, get_services
from app.api.schemas import ClipOut, ClipRenderRequest, ClipUpdateRequest, clip_out
from app.pipeline.captions import write_clip_ass_file
from app.pipeline.render import DEFAULT_LAYOUT, extract_clip_thumbnail, plan_layout, render_clip_video
from app.pipeline.transcript import Transcript

logger = logging.getLogger(__name__)
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


@router.patch("/clips/{clip_id}", response_model=ClipOut)
def update_clip(
    clip_id: str,
    req: ClipUpdateRequest,
    svc: Services = Depends(get_services),
) -> ClipOut:
    """Updates clip metadata or trim bounds."""
    clip = repo.get_clip(svc.engine, clip_id)
    if clip is None:
        raise HTTPException(404, "Clip not found")

    updates = {}
    if req.title is not None:
        updates["title"] = req.title.strip()
    if req.hook_text is not None:
        updates["hook_text"] = req.hook_text.strip()
    if req.start_s is not None:
        updates["start_s"] = max(0.0, req.start_s)
    if req.end_s is not None:
        updates["end_s"] = req.end_s
    if "start_s" in updates or "end_s" in updates:
        s = updates.get("start_s", clip.start_s)
        e = updates.get("end_s", clip.end_s)
        if e <= s:
            raise HTTPException(422, "end_s must be greater than start_s")
    if req.subtitle_style is not None:
        updates["subtitle_style"] = req.subtitle_style
    if req.auto_zoom is not None:
        updates["auto_zoom"] = req.auto_zoom
    if req.music_mood is not None:
        updates["music_mood"] = req.music_mood
    if req.broll_enabled is not None:
        updates["broll_enabled"] = req.broll_enabled
    if req.target_language is not None:
        updates["target_language"] = req.target_language
    if req.layout_mode is not None:
        updates["layout_mode"] = req.layout_mode
    if req.filler_trim is not None:
        updates["filler_trim"] = req.filler_trim

    if updates:
        clip = repo.update_clip(svc.engine, clip.id, **updates)
    return clip_out(clip, _seo_data(svc, clip.id, clip.project_id))


@router.post("/clips/{clip_id}/render", response_model=ClipOut)
def rerender_clip(
    clip_id: str,
    req: ClipRenderRequest = ClipRenderRequest(),
    svc: Services = Depends(get_services),
) -> ClipOut:
    """Re-renders a clip with a selected kinetic subtitle style, optional trim, and polish settings."""
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

    # Options the request leaves out keep the clip's current settings (e.g. changing only the caption
    # style must not silently drop dubbing, B-roll, filler trimming or the chosen layout).
    sent = req.model_fields_set

    def keep(name: str, current):
        return getattr(req, name) if name in sent else current

    subtitle_style = keep("subtitle_style", None) or clip.subtitle_style or "hormozi"
    auto_zoom = bool(keep("auto_zoom", clip.auto_zoom if clip.auto_zoom is not None else True))
    music_mood = keep("music_mood", clip.music_mood)
    broll_enabled = bool(keep("broll_enabled", clip.broll_enabled))
    target_language = keep("target_language", clip.target_language)
    requested_layout = keep("layout_mode", None) or clip.layout_mode or DEFAULT_LAYOUT
    filler_trim = bool(keep("filler_trim", clip.filler_trim))

    # Determine trim boundaries and titles
    start_s = req.start_s if req.start_s is not None else clip.start_s
    end_s = req.end_s if req.end_s is not None else clip.end_s
    if end_s <= start_s or start_s < 0:
        raise HTTPException(422, "Invalid trim boundaries: end_s must be greater than start_s and start_s >= 0")

    title = req.title.strip() if req.title is not None else clip.title
    hook_text = req.hook_text.strip() if req.hook_text is not None else (clip.hook_text or clip.title)

    clips_dir = svc.workspace.project_dir(clip.project_id) / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    video_dst = clips_dir / f"{clip.id}.mp4"
    thumb_dst = clips_dir / f"{clip.id}.jpg"
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

    # Neural Dubbing & Translation if requested
    dubbed_audio_path = None
    target_words = words
    if target_language:
        from app.pipeline.dubbing import DubbingError, generate_dubbed_clip_audio
        dub_file = clips_dir / f"{clip.id}_dub_{target_language}.mp3"
        try:
            dubbed_audio_path, target_words = generate_dubbed_clip_audio(
                words=words,
                clip_start_s=start_s,
                clip_end_s=end_s,
                target_lang=target_language,
                dst_path=dub_file,
                engine=svc.engine,
            )
        except DubbingError as dub_exc:
            # Tell the user instead of silently rendering the original language.
            raise HTTPException(422, str(dub_exc)) from dub_exc

    # Silence & Filler jump-cut trimmer if enabled
    keep_intervals = None
    if filler_trim and target_words:
        try:
            from app.pipeline.fillers import detect_silence_and_fillers
            keep_intervals, target_words, time_saved = detect_silence_and_fillers(
                words=target_words,
                clip_start_s=start_s,
                clip_end_s=end_s,
            )
            logger.info("Jump-cut trimmer: trimmed %.2fs for clip %s", time_saved, clip.id)
        except Exception as filler_exc:
            logger.warning("Jump-cut trimmer failed for clip %s: %s", clip.id, filler_exc)

    if target_words:
        write_clip_ass_file(
            words=target_words,
            clip_start_s=start_s,
            clip_end_s=end_s,
            dst_path=ass_dst,
            style_name=subtitle_style,
            hook_text=hook_text,
        )

    # Prepare B-roll cues if broll_enabled
    active_broll_cues = []
    if broll_enabled:
        try:
            from app.pipeline.broll import ensure_broll_media, extract_broll_cues
            cues = extract_broll_cues(start_s, end_s, words=words, keywords=clip.keywords)
            broll_cache = svc.workspace.project_dir(clip.project_id) / "broll"
            for cue in cues:
                try:
                    ensure_broll_media(cue, broll_cache)
                    active_broll_cues.append(cue)
                except Exception:
                    pass
        except Exception:
            pass

    # Re-render video
    layout_mode, track, layout_note = plan_layout(
        src, start_s, end_s, requested_layout, models_dir=svc.settings.models_dir,
        cache_file=clips_dir / f"{clip.id}.track.json",
    )
    if layout_note:
        logger.info("Clip %s: %s", clip.id, layout_note)
    video_dst.unlink(missing_ok=True)
    render_clip_video(
        src=src,
        dst=video_dst,
        start_s=start_s,
        end_s=end_s,
        ass_file=ass_dst if ass_dst.exists() else None,
        auto_zoom=auto_zoom,
        music_mood=music_mood,
        broll_cues=active_broll_cues,
        dubbed_audio=dubbed_audio_path,
        layout_mode=layout_mode,
        keep_intervals=keep_intervals,
        track=track,
    )

    # Refresh thumbnail
    mid = start_s + min(1.5, (end_s - start_s) / 2)
    try:
        extract_clip_thumbnail(src=src, dst=thumb_dst, time_s=mid)
    except Exception:
        pass

    updated = repo.update_clip(
        svc.engine,
        clip.id,
        video_file=f"clips/{clip.id}.mp4",
        thumbnail_file=f"clips/{clip.id}.jpg" if thumb_dst.exists() else None,
        subtitle_style=subtitle_style,
        auto_zoom=auto_zoom,
        music_mood=music_mood,
        broll_enabled=broll_enabled,
        broll_cues=[c.model_dump() for c in active_broll_cues] if active_broll_cues else clip.broll_cues,
        target_language=target_language,
        # Turning dubbing off must also forget the old dub, or the UI keeps offering the wrong language.
        dubbed_audio_file=f"clips/{dubbed_audio_path.name}" if dubbed_audio_path and dubbed_audio_path.exists() else None,
        layout_mode=layout_mode,
        filler_trim=filler_trim,
        start_s=start_s,
        end_s=end_s,
        title=title,
        hook_text=hook_text,
    )
    return clip_out(updated, _seo_data(svc, updated.id, updated.project_id))


@router.delete("/clips/{clip_id}", status_code=204)
def delete_clip(clip_id: str, svc: Services = Depends(get_services)) -> Response:
    """Delete one clip and every file rendered for it (video, thumbnail, captions, dub, tracking, SEO)."""
    clip = repo.get_clip(svc.engine, clip_id)
    if clip is None:
        raise HTTPException(404, "Clip not found")
    clips_dir = svc.workspace.projects_dir / clip.project_id / "clips"
    if clips_dir.exists():
        for path in clips_dir.glob(f"{clip.id}*"):  # {id}.mp4/.jpg/.ass/.track.json, {id}_dub_xx.mp3
            if path.is_file():
                path.unlink(missing_ok=True)
    project = repo.get_project(svc.engine, clip.project_id)
    if project is not None and project.video_id:
        (svc.workspace.videos_dir / project.video_id / f"seo_{clip.id}.json").unlink(missing_ok=True)
    repo.delete_clip(svc.engine, clip_id)
    return Response(status_code=204)

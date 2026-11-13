"""Clips API — Phase 2 & Phase 3."""
import json
import logging
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse

from app import repo
from app.api.deps import Services, get_services
from app.api.schemas import (
    ChatEditRequest,
    ChatEditResponse,
    ClipOut,
    ClipRenderRequest,
    ClipUpdateRequest,
    SuperCutRequest,
    clip_out,
)
from app.pipeline.captions import write_clip_ass_file
from app.pipeline.render import DEFAULT_LAYOUT, extract_clip_thumbnail, plan_layout, render_clip_video
from app.pipeline.supercut import build_master_supercut
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


def _trigger_rerender(clip_id: str, svc: Services) -> None:
    """Fire off a background re-render for a clip after chat edit changes."""
    import threading
    from app.pipeline.render import extract_clip_thumbnail, render_clip_video
    from app.pipeline.captions import write_clip_ass_file

    clip = repo.get_clip(svc.engine, clip_id)
    if clip is None:
        return

    project = repo.get_project(svc.engine, clip.project_id)
    if project is None or project.video_id is None:
        return

    video_dir = svc.workspace.video(project.video_id).dir
    src = next(
        (p for ext in (".mp4", ".mkv", ".webm", ".mov") if (p := video_dir / f"source{ext}").exists()),
        None,
    )
    if src is None:
        return

    clips_dir = svc.workspace.project_dir(clip.project_id) / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    video_dst = clips_dir / f"{clip.id}.mp4"
    ass_dst = clips_dir / f"{clip.id}.ass"
    thumb_dst = clips_dir / f"{clip.id}.jpg"

    def _run():
        try:
            # Delete old render so it regenerates
            video_dst.unlink(missing_ok=True)
            ass_dst.unlink(missing_ok=True)
            thumb_dst.unlink(missing_ok=True)

            # Load transcript words for subtitle sync
            import json as _json
            words_path = video_dir / "transcript_words.json"
            words = []
            if words_path.exists():
                from app.pipeline.transcript import Word
                raw_words = _json.loads(words_path.read_text())
                words = [Word(**w) for w in raw_words]

            # Keep intervals if filler_trim
            keep_intervals = None
            render_words = words
            if clip.filler_trim and words:
                from app.pipeline.fillers import detect_silence_and_fillers
                keep_intervals, render_words, _ = detect_silence_and_fillers(
                    words=words, clip_start_s=clip.start_s, clip_end_s=clip.end_s
                )

            # Write ASS subtitles
            if render_words:
                try:
                    write_clip_ass_file(
                        words=render_words,
                        clip_start_s=clip.start_s,
                        clip_end_s=clip.end_s,
                        dst_path=ass_dst,
                        style_name=clip.subtitle_style or "hormozi",
                        hook_text=clip.hook_text or clip.title,
                    )
                except Exception:
                    pass

            render_clip_video(
                src=src,
                dst=video_dst,
                start_s=clip.start_s,
                end_s=clip.end_s,
                ass_file=ass_dst if ass_dst.exists() else None,
                auto_zoom=clip.auto_zoom if clip.auto_zoom is not None else True,
                music_mood=clip.music_mood,
                broll_cues=clip.broll_cues,
                layout_mode=clip.layout_mode or "track",
                keep_intervals=keep_intervals,
                color_grade=clip.color_grade,
            )

            extract_clip_thumbnail(src=video_dst, dst=thumb_dst, time_s=1.0)

            # Update DB with new file paths
            from sqlmodel import Session
            from app.models import utcnow
            with Session(svc.engine) as session:
                db_clip = session.get(type(clip), clip.id)
                if db_clip:
                    db_clip.video_file = str(video_dst)
                    db_clip.thumbnail_file = str(thumb_dst)
                    db_clip.updated_at = utcnow()
                    session.add(db_clip)
                    session.commit()
        except Exception as exc:
            logger.error("Background re-render after chat edit failed: %s", exc)

    threading.Thread(target=_run, daemon=True).start()


@router.get("/projects/{project_id}/clips", response_model=list[ClipOut])
def list_clips(project_id: str, svc: Services = Depends(get_services)) -> list[ClipOut]:
    project = repo.get_project(svc.engine, project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    clips = repo.list_clips(svc.engine, project_id)
    return [clip_out(c, _seo_data(svc, c.id, project_id)) for c in clips]


@router.post("/projects/{project_id}/supercut", response_model=ClipOut)
def create_supercut(
    project_id: str,
    req: SuperCutRequest = SuperCutRequest(),
    svc: Services = Depends(get_services),
) -> ClipOut:
    """Generate a master highlight supercut video combining top candidate moments with cinematic grading."""
    project = repo.get_project(svc.engine, project_id)
    if project is None:
        raise HTTPException(404, "Project not found")

    try:
        clip = build_master_supercut(
            engine=svc.engine,
            project_id=project_id,
            workspace=svc.workspace,
            settings=svc.settings,
            max_duration_s=req.max_duration_s,
            color_grade=req.color_grade,
            music_mood=req.music_mood,
            selected_clip_ids=req.clip_ids if req.clip_ids else None,
        )
        return clip_out(clip, _seo_data(svc, clip.id, project_id))
    except ValueError as val_err:
        raise HTTPException(400, str(val_err))
    except Exception as exc:
        logger.error("Supercut generation failed: %s", exc, exc_info=True)
        raise HTTPException(500, f"Supercut generation failed: {exc}")


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
    if req.color_grade is not None:
        updates["color_grade"] = req.color_grade

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
    color_grade = keep("color_grade", clip.color_grade)

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
        color_grade=color_grade,
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
        color_grade=color_grade,
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


@router.post("/clips/{clip_id}/chat-edit")
def chat_edit_clip(
    clip_id: str,
    body: ChatEditRequest,
    svc: Services = Depends(get_services),
) -> ChatEditResponse:
    """AI natural-language clip editor. Parses instruction, applies edits, triggers re-render."""
    from app.pipeline.chat_editor import apply_edit_command, parse_edit_instruction

    clip = repo.get_clip(svc.engine, clip_id)
    if clip is None:
        raise HTTPException(404, "Clip not found")

    cmd = parse_edit_instruction(
        instruction=body.instruction,
        clip_start_s=clip.start_s,
        clip_end_s=clip.end_s,
        clip_title=clip.title,
        clip_hook=clip.hook_text,
        engine=svc.engine,
    )

    changes = apply_edit_command(cmd, clip)
    rerender = bool(changes)

    if changes:
        from sqlmodel import Session
        with Session(svc.engine) as session:
            db_clip = session.get(type(clip), clip_id)
            if db_clip:
                for k, v in changes.items():
                    setattr(db_clip, k, v)
                db_clip.updated_at = __import__("app.models", fromlist=["utcnow"]).utcnow()
                session.add(db_clip)
                session.commit()

        # Trigger async re-render via existing rerender_clip logic
        if rerender:
            try:
                _trigger_rerender(clip_id, svc)
            except Exception as exc:
                logger.warning("Re-render trigger failed after chat edit: %s", exc)
                rerender = False

    summary = cmd.summary
    if not summary and changes:
        summary = "Applied: " + ", ".join(f"{k}={v}" for k, v in changes.items())

    return ChatEditResponse(
        understood=cmd.understood,
        intent=cmd.intent,
        summary=summary,
        changes=changes,
        rerender_triggered=rerender,
    )

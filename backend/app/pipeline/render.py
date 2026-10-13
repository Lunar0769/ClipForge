"""Phase 3 — 9:16 Vertical Video Renderer.

Cuts candidate moments from the source video and renders them into
high-quality vertical 1080x1920 Short-form videos (YouTube Shorts, TikTok,
Instagram Reels) with blurred background fill framing, H.264 video,
AAC audio, and faststart headers for instant browser playback.
Also generates a thumbnail snapshot for each clip.
"""

import json
import logging
import os
import shutil
import threading
from pathlib import Path
from typing import Any

from app import media, repo
from app.media import _run_cancellable, _tool
from app.models import Clip
from app.pipeline.captions import write_clip_ass_file
from app.pipeline.context import PipelineContext
from app.pipeline.errors import StageCancelled, StageError
from app.pipeline.transcript import Transcript

logger = logging.getLogger(__name__)

# Filter complex for professional 9:16 vertical composition:
# Splits video into 2 streams:
# - Stream 1 (bg): scaled to fill 1080x1920, cropped, and blurred (boxblur)
# - Stream 2 (fg): scaled to fit 1080 width with original aspect ratio preserved
# - Overlay: centers foreground on top of the blurred background
VERTICAL_BLUR_FILTER = (
    "[0:v]split=2[bg_in][fg_in];"
    "[bg_in]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:2[bg];"
    "[fg_in]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
    "[bg][fg]overlay=(W-w)/2:(H-h)/2[v]"
)


MOOD_PRESETS: dict[str, str] = {
    "chill": "0.03*sin(2*PI*110*t) + 0.02*sin(2*PI*165*t) + 0.015*sin(2*PI*220*t)",
    "energetic": "0.03*sin(2*PI*130*t)*(0.6+0.4*sin(2*PI*2*t)) + 0.02*sin(2*PI*260*t)",
    "suspense": "0.04*sin(2*PI*55*t) + 0.03*sin(2*PI*58.2*t) + 0.02*sin(2*PI*116*t)",
}


def render_clip_video(
    src: Path,
    dst: Path,
    start_s: float,
    end_s: float,
    *,
    ass_file: Path | None = None,
    auto_zoom: bool = True,
    music_mood: str | None = None,
    broll_cues: list[Any] | None = None,
    cancel: threading.Event | None = None,
) -> None:
    """Renders a single 9:16 vertical video slice from src to dst with optional ASS subtitles, dynamic punch-in zoom, mood audio bed, and B-roll cutaways."""
    tmp = dst.with_name(f"{dst.stem}.tmp{dst.suffix}")
    ffmpeg = _tool("ffmpeg")
    duration = max(1.0, end_s - start_s)

    # 1. Foreground stream framing: dynamic punch-in zoom or standard fit
    if auto_zoom:
        fg_filter = "crop=w='if(between(mod(t,12),4,8), in_w*0.92, in_w)':h='if(between(mod(t,12),4,8), in_h*0.92, in_h)':x='(in_w-out_w)/2':y='(in_h-out_h)/2',scale=1080:1920:force_original_aspect_ratio=decrease"
    else:
        fg_filter = "scale=1080:1920:force_original_aspect_ratio=decrease"

    filter_chains = [
        "[0:v]split=2[bg_in][fg_in]",
        "[bg_in]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:2[bg]",
        f"[fg_in]{fg_filter}[fg]",
        "[bg][fg]overlay=(W-w)/2:(H-h)/2[base_comp_0]",
    ]

    extra_inputs: list[str] = []
    input_count = 1

    # Audio & Mood Bed
    music_input_idx = None
    if music_mood and music_mood in MOOD_PRESETS:
        extra_inputs.extend([
            "-f", "lavfi",
            "-i", f"aevalsrc=exprs='{MOOD_PRESETS[music_mood]}':s=44100:d={duration:.3f}",
        ])
        music_input_idx = input_count
        input_count += 1

    # B-roll Video Inputs
    valid_brolls: list[tuple[int, float, float]] = []
    if broll_cues:
        for cue in broll_cues:
            cue_path = getattr(cue, "video_path", None) or (cue.get("video_path") if isinstance(cue, dict) else None)
            cue_start = getattr(cue, "start_s", 0.0) if not isinstance(cue, dict) else cue.get("start_s", 0.0)
            cue_end = getattr(cue, "end_s", 0.0) if not isinstance(cue, dict) else cue.get("end_s", 0.0)
            if cue_path and Path(cue_path).exists():
                extra_inputs.extend(["-stream_loop", "-1", "-i", str(Path(cue_path).resolve())])
                valid_brolls.append((input_count, float(cue_start), float(cue_end)))
                input_count += 1

    # Composite B-roll overlays
    curr_comp = "base_comp_0"
    for i, (b_idx, c_start, c_end) in enumerate(valid_brolls):
        filter_chains.append(f"[{b_idx}:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920[broll_{i}]")
        next_comp = f"base_comp_{i+1}"
        filter_chains.append(f"[{curr_comp}][broll_{i}]overlay=x=0:y=0:enable='between(t,{c_start:.2f},{c_end:.2f})'[{next_comp}]")
        curr_comp = next_comp

    # Subtitles on top of all visual layers
    if ass_file and ass_file.exists():
        filter_chains.append(f"[{curr_comp}]ass={ass_file.name}[v]")
    else:
        filter_chains.append(f"[{curr_comp}]null[v]")

    # Audio & Mood Bed mapping
    audio_maps: list[str] = []
    if music_input_idx is not None:
        has_audio = True
        try:
            info = media.probe(src)
            has_audio = info.has_audio
        except Exception:
            pass

        if has_audio:
            filter_chains.append(f"[0:a]volume=1.0[a0];[{music_input_idx}:a]volume=0.20[a1];[a0][a1]amix=inputs=2:duration=first[a]")
        else:
            filter_chains.append(f"[{music_input_idx}:a]volume=0.25[a]")
        audio_maps = ["-map", "[a]"]
    else:
        audio_maps = ["-map", "0:a?"]

    filter_complex = ";".join(filter_chains)

    # Note: placing -ss before -i provides fast seek, -t provides duration
    cmd = [
        ffmpeg,
        "-y",
        "-v", "error",
        "-ss", f"{start_s:.3f}",
        "-t", f"{duration:.3f}",
        "-i", str(src),
        *extra_inputs,
        "-filter_complex", filter_complex,
        "-map", "[v]",
        *audio_maps,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar", "44100",
        "-movflags", "+faststart",
        "-f", "mp4",
        str(tmp),
    ]

    try:
        # Run inside dst.parent directory so relative ASS filename resolves without path escaping issues
        _run_cancellable(cmd, cancel, cwd=dst.parent)
        os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)


def extract_clip_thumbnail(
    src: Path,
    dst: Path,
    time_s: float,
    *,
    cancel: threading.Event | None = None,
) -> None:
    """Extracts a single high-quality frame snapshot."""
    tmp = dst.with_name(f"{dst.stem}.tmp{dst.suffix}")
    ffmpeg = _tool("ffmpeg")

    cmd = [
        ffmpeg,
        "-y",
        "-v", "error",
        "-ss", f"{time_s:.3f}",
        "-i", str(src),
        "-vframes", "1",
        "-q:v", "2",
        "-f", "image2",
        str(tmp),
    ]

    try:
        _run_cancellable(cmd, cancel)
        os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)


class RenderStage:
    name = "render"
    label = "Rendering 9:16 vertical shorts"
    weight = 3.0
    uses_gpu = False

    def is_done(self, ctx: PipelineContext) -> bool:
        clips = repo.list_clips(ctx.engine, ctx.project_id)
        if not clips:
            return False
        clips_dir = ctx.workspace.project_dir(ctx.project_id) / "clips"
        return all(
            c.video_file and (clips_dir / Path(c.video_file).name).exists()
            for c in clips
        )

    def run(self, ctx: PipelineContext) -> None:
        clips = repo.list_clips(ctx.engine, ctx.project_id)
        if not clips:
            ctx.emit("log", stage=self.name, message="No clips found to render.")
            return

        vp = ctx.video()
        src = vp.find_source()
        if src is None or not src.exists():
            raise StageError(
                "Source media missing for rendering.",
                "The source video could not be found in the workspace cache.",
            )

        clips_dir = ctx.workspace.project_dir(ctx.project_id) / "clips"
        clips_dir.mkdir(parents=True, exist_ok=True)

        total = len(clips)
        ctx.emit("log", stage=self.name, message=f"Starting 9:16 vertical render with dynamic captions for {total} clips...")

        # Load transcript words if available for kinetic caption burning
        words = []
        try:
            if vp.transcript.exists():
                data = json.loads(vp.transcript.read_text(encoding="utf-8"))
                transcript = Transcript.model_validate(data)
                words = transcript.words
        except Exception as exc:
            logger.warning("Could not load transcript words for subtitles: %s", exc)

        for idx, clip in enumerate(clips):
            ctx.check_cancelled()

            video_dst = clips_dir / f"{clip.id}.mp4"
            thumb_dst = clips_dir / f"{clip.id}.jpg"
            ass_dst = clips_dir / f"{clip.id}.ass"

            # 1. Generate ASS subtitles if words exist
            if words and not ass_dst.exists():
                try:
                    style_name = clip.subtitle_style or "hormozi"
                    hook = clip.hook_text or clip.title
                    write_clip_ass_file(
                        words=words,
                        clip_start_s=clip.start_s,
                        clip_end_s=clip.end_s,
                        dst_path=ass_dst,
                        style_name=style_name,
                        hook_text=hook,
                    )
                except Exception as exc:
                    logger.warning("Failed to generate ASS subtitles for clip %s: %s", clip.id, exc)

            # 2. B-roll cutaway preparation if enabled
            active_broll_cues = []
            if clip.broll_enabled:
                try:
                    from app.pipeline.broll import ensure_broll_media, extract_broll_cues
                    cues = extract_broll_cues(clip.start_s, clip.end_s, words=words, keywords=clip.keywords)
                    cache_dir = ctx.workspace.project_dir(ctx.project_id) / "broll"
                    for cue in cues:
                        try:
                            ensure_broll_media(cue, cache_dir, cancel=ctx.cancel_event)
                            active_broll_cues.append(cue)
                        except Exception as cue_err:
                            logger.warning("B-roll generation failed for %s: %s", cue.keyword, cue_err)
                except Exception as broll_err:
                    logger.warning("Failed to prepare B-roll cues for clip %s: %s", clip.id, broll_err)

            # 3. Video render
            if not video_dst.exists():
                ctx.emit(
                    "log",
                    stage=self.name,
                    message=f"Rendering clip #{clip.rank + 1} ({int(round(clip.end_s - clip.start_s))}s) with {clip.subtitle_style or 'hormozi'} subtitles: {clip.title}",
                )
                render_clip_video(
                    src=src,
                    dst=video_dst,
                    start_s=clip.start_s,
                    end_s=clip.end_s,
                    ass_file=ass_dst if ass_dst.exists() else None,
                    auto_zoom=clip.auto_zoom if clip.auto_zoom is not None else True,
                    music_mood=clip.music_mood,
                    broll_cues=active_broll_cues,
                    cancel=ctx.cancel_event,
                )

            # 4. Thumbnail extraction (pick a frame 1.5s in or at midpoint)
            if not thumb_dst.exists():
                mid = clip.start_s + min(1.5, (clip.end_s - clip.start_s) / 2)
                try:
                    extract_clip_thumbnail(
                        src=src,
                        dst=thumb_dst,
                        time_s=mid,
                        cancel=ctx.cancel_event,
                    )
                except Exception as exc:
                    logger.warning("Thumbnail extraction failed for clip %s: %s", clip.id, exc)

            # 5. Update database record
            repo.update_clip(
                ctx.engine,
                clip.id,
                video_file=f"clips/{clip.id}.mp4",
                thumbnail_file=f"clips/{clip.id}.jpg" if thumb_dst.exists() else None,
                subtitle_style=clip.subtitle_style or "hormozi",
                auto_zoom=clip.auto_zoom if clip.auto_zoom is not None else True,
                music_mood=clip.music_mood,
                broll_enabled=clip.broll_enabled,
                broll_cues=[c.model_dump() for c in active_broll_cues] if active_broll_cues else clip.broll_cues,
            )

            progress = (idx + 1) / total
            ctx.emit("progress", stage=self.name, progress=progress)

        ctx.emit("log", stage=self.name, message=f"✅ Finished rendering all {total} clips in 9:16 vertical format.")

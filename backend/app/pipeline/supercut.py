"""Phase 9 — Cinematic Master Super-Cut & Highlight Reel Generator.

Compiles the highest-retention viral moments from a project into a cohesive,
fast-paced 9:16 short with cinematic color grading (teal/orange contrast curves,
subtle vignette, film saturation), dynamic background soundtrack, and kinetic styling.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any, Sequence
from uuid import uuid4

from app import media, repo
from app.gpu import ffmpeg_has_nvenc
from app.media import _run_cancellable, _tool
from app.models import Clip, Project
from app.pipeline.render import (
    COLOR_GRADES,
    CPU_ARGS,
    MOOD_PRESETS,
    NVENC_ARGS,
    VIDEO_ENCODER_PLACEHOLDER_TOKEN,
    extract_clip_thumbnail,
    render_clip_video,
)

logger = logging.getLogger(__name__)


def build_master_supercut(
    engine: Any,
    project_id: str,
    workspace: Any,
    settings: Any,
    *,
    max_duration_s: float = 60.0,
    color_grade: str = "cinematic",
    music_mood: str = "suspense",
    selected_clip_ids: Sequence[str] | None = None,
) -> Clip:
    """Combines top candidate clips into a single cinematic master highlight reel."""
    all_clips = repo.list_clips(engine, project_id)
    # Exclude existing supercuts
    candidate_clips = [c for c in all_clips if not c.is_supercut]

    if selected_clip_ids:
        chosen = [c for c in candidate_clips if c.id in selected_clip_ids]
    else:
        # Pick top clips sorted by score descending, up to 4 clips
        chosen = sorted(candidate_clips, key=lambda c: (c.score or 0), reverse=True)[:4]

    if not chosen:
        raise ValueError("No candidate clips found in project to compile super-cut.")

    proj_dir = workspace.project_dir(project_id)
    clips_dir = proj_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    # Ensure source video is discoverable if rendering is needed
    project = repo.get_project(engine, project_id)
    source_video = None
    if project and project.video_id:
        v_dir = workspace.videos_dir / project.video_id
        for ext in (".mp4", ".mov", ".mkv", ".webm", ".avi"):
            cand = v_dir / f"source{ext}"
            if cand.exists():
                source_video = cand
                break

    # Verify each chosen clip has a rendered video on disk; if not, render it now
    rendered_clip_paths: list[tuple[Clip, Path, float]] = []
    n_clips = len(chosen)
    target_per_clip = max(8.0, min(max_duration_s / n_clips, 18.0))

    for clip in chosen:
        clip_vid = clips_dir / f"{clip.id}.mp4"
        if not clip_vid.exists() and source_video and source_video.exists():
            ass_dst = clips_dir / f"{clip.id}.ass"
            try:
                render_clip_video(
                    src=source_video,
                    dst=clip_vid,
                    start_s=clip.start_s,
                    end_s=clip.end_s,
                    ass_file=ass_dst if ass_dst.exists() else None,
                    auto_zoom=clip.auto_zoom if clip.auto_zoom is not None else True,
                    music_mood=None,  # Leave dry so supercut mixes global soundtrack
                    layout_mode=clip.layout_mode or "fit_blur",
                    color_grade=None,  # Supercut applies unified grade
                )
            except Exception as exc:
                logger.warning("Failed to render clip %s for supercut: %s", clip.id, exc)

        if clip_vid.exists():
            clip_dur = max(1.0, clip.end_s - clip.start_s)
            slice_dur = min(clip_dur, target_per_clip)
            rendered_clip_paths.append((clip, clip_vid, slice_dur))

    if not rendered_clip_paths:
        raise RuntimeError("No rendered video files available to compile super-cut.")

    supercut_id = f"supercut_{uuid4().hex[:10]}"
    dst_video = clips_dir / f"{supercut_id}.mp4"
    dst_thumb = clips_dir / f"{supercut_id}.jpg"
    tmp_video = dst_video.with_name(f"{dst_video.stem}.tmp{dst_video.suffix}")

    ffmpeg = _tool("ffmpeg")
    total_duration = sum(slice_s for _, _, slice_s in rendered_clip_paths)

    # Build FFmpeg command inputs
    inputs: list[str] = []
    for _, path, slice_s in rendered_clip_paths:
        inputs.extend(["-ss", "0.0", "-t", f"{slice_s:.3f}", "-i", str(path.resolve())])

    num_inputs = len(rendered_clip_paths)
    extra_inputs: list[str] = []

    # Music audio bed
    music_idx = None
    if music_mood and music_mood in MOOD_PRESETS:
        extra_inputs.extend([
            "-f", "lavfi",
            "-i", f"aevalsrc=exprs='{MOOD_PRESETS[music_mood]}':s=44100:d={total_duration:.3f}",
        ])
        music_idx = num_inputs

    # Build filtergraph
    # 1. Concat all clip slices
    concat_inputs = "".join(f"[{i}:v][{i}:a]" for i in range(num_inputs))
    filter_chains = [
        f"{concat_inputs}concat=n={num_inputs}:v=1:a=1[v_concat][a_concat]"
    ]

    # 2. Cinematic lighting & color grading
    grade_preset = COLOR_GRADES.get(color_grade, COLOR_GRADES["cinematic"])
    filter_chains.append(f"[v_concat]{grade_preset}[v_graded]")

    # 3. Audio mixing with dramatic soundtrack
    audio_maps: list[str] = []
    if music_idx is not None:
        filter_chains.append(
            f"[a_concat]volume=1.0[voice];[{music_idx}:a]volume=0.22[bg_music];[voice][bg_music]amix=inputs=2:duration=first[a_mixed]"
        )
        audio_maps = ["-map", "[a_mixed]"]
    else:
        audio_maps = ["-map", "[a_concat]"]

    filter_complex = ";".join(filter_chains)

    cmd = [
        ffmpeg,
        "-y",
        "-v", "error",
        *inputs,
        *extra_inputs,
        "-filter_complex", filter_complex,
        "-map", "[v_graded]",
        *audio_maps,
        VIDEO_ENCODER_PLACEHOLDER_TOKEN,
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar", "44100",
        "-t", f"{total_duration:.3f}",
        "-movflags", "+faststart",
        "-f", "mp4",
        str(tmp_video),
    ]

    encoders = [NVENC_ARGS, CPU_ARGS] if ffmpeg_has_nvenc() else [CPU_ARGS]
    success = False
    for attempt, encoder in enumerate(encoders, start=1):
        idx = cmd.index(VIDEO_ENCODER_PLACEHOLDER_TOKEN)
        run_cmd = cmd[:idx] + encoder + cmd[idx + 1:]
        try:
            _run_cancellable(run_cmd, None, cwd=clips_dir)
            if tmp_video.exists() and tmp_video.stat().st_size > 0:
                os.replace(tmp_video, dst_video)
                success = True
                break
        except Exception as exc:
            logger.warning("Supercut encoder attempt %d failed: %s", attempt, exc)
            tmp_video.unlink(missing_ok=True)

    if not success or not dst_video.exists():
        raise RuntimeError(f"Failed to generate super-cut video at {dst_video}")

    # Extract thumbnail at 1.5s
    try:
        extract_clip_thumbnail(dst_video, dst_thumb, time_s=min(1.5, total_duration / 2))
    except Exception as exc:
        logger.warning("Failed to extract supercut thumbnail: %s", exc)

    # Shift ranks of existing clips by +1 so supercut is rank 0 (top of gallery)
    for c in all_clips:
        repo.update_clip(engine, c.id, rank=c.rank + 1)

    # Create new supercut Clip
    supercut_clip = Clip(
        id=supercut_id,
        project_id=project_id,
        rank=0,
        start_s=0.0,
        end_s=round(total_duration, 2),
        title="🎬 AI Master Super-Cut (Cinematic Edit)",
        hook_text="The Ultimate Highlights",
        hook_type="statement",
        why_viral="AI-edited compilation combining the highest-retention moments with cinematic lighting, film curve color grading, and dramatic score.",
        payoff_summary=f"Seamlessly stitched the top {len(rendered_clip_paths)} clips into a cohesive high-retention reel.",
        score=99,
        sub_scores={"hook": 99, "flow": 98, "payoff": 99, "trend": 98},
        keywords=["supercut", "highlights", "cinematic", "viral", "movie edit"],
        emoji=["🎬", "🔥", "✨"],
        speakers=["Compilation"],
        video_file=f"clips/{supercut_id}.mp4",
        thumbnail_file=f"clips/{supercut_id}.jpg" if dst_thumb.exists() else None,
        subtitle_style="clean",
        auto_zoom=True,
        music_mood=music_mood,
        color_grade=color_grade,
        is_supercut=True,
    )

    created_clip = repo.add_clip(engine, supercut_clip)
    logger.info("Successfully created master supercut clip: %s", supercut_id)
    return created_clip

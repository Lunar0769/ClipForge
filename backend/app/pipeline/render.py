"""Phase 3 — 9:16 Vertical Video Renderer.

Cuts candidate moments from the source video and renders them into
high-quality vertical 1080x1920 Short-form videos (YouTube Shorts, TikTok,
Instagram Reels) with blurred background fill framing, H.264 video,
AAC audio, and faststart headers for instant browser playback.
Also generates a thumbnail snapshot for each clip.
"""

import logging
import os
import shutil
import threading
from pathlib import Path

from app import media, repo
from app.media import _run_cancellable, _tool
from app.models import Clip
from app.pipeline.context import PipelineContext
from app.pipeline.errors import StageCancelled, StageError

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


def render_clip_video(
    src: Path,
    dst: Path,
    start_s: float,
    end_s: float,
    *,
    cancel: threading.Event | None = None,
) -> None:
    """Renders a single 9:16 vertical video slice from src to dst."""
    tmp = dst.with_name(f"{dst.stem}.tmp{dst.suffix}")
    ffmpeg = _tool("ffmpeg")
    duration = max(1.0, end_s - start_s)

    # Note: placing -ss before -i provides fast seek, -t provides duration
    cmd = [
        ffmpeg,
        "-y",
        "-v", "error",
        "-ss", f"{start_s:.3f}",
        "-t", f"{duration:.3f}",
        "-i", str(src),
        "-filter_complex", VERTICAL_BLUR_FILTER,
        "-map", "[v]",
        "-map", "0:a?",
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
        _run_cancellable(cmd, cancel)
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
        ctx.emit("log", stage=self.name, message=f"Starting 9:16 vertical render for {total} clips...")

        for idx, clip in enumerate(clips):
            ctx.check_cancelled()

            video_dst = clips_dir / f"{clip.id}.mp4"
            thumb_dst = clips_dir / f"{clip.id}.jpg"

            # 1. Video render
            if not video_dst.exists():
                ctx.emit(
                    "log",
                    stage=self.name,
                    message=f"Rendering clip #{clip.rank + 1} ({int(round(clip.end_s - clip.start_s))}s): {clip.title}",
                )
                render_clip_video(
                    src=src,
                    dst=video_dst,
                    start_s=clip.start_s,
                    end_s=clip.end_s,
                    cancel=ctx.cancel_event,
                )

            # 2. Thumbnail extraction (pick a frame 1.5s in or at midpoint)
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

            # 3. Update database record
            repo.update_clip(
                ctx.engine,
                clip.id,
                video_file=f"clips/{clip.id}.mp4",
                thumbnail_file=f"clips/{clip.id}.jpg" if thumb_dst.exists() else None,
            )

            progress = (idx + 1) / total
            ctx.emit("progress", stage=self.name, progress=progress)

        ctx.emit("log", stage=self.name, message=f"✅ Finished rendering all {total} clips in 9:16 vertical format.")

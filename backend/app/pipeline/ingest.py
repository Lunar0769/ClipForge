import shutil
import threading
from pathlib import Path

from pydantic import BaseModel

from app import repo
from app.media import MediaError, compute_video_id, extract_audio, probe
from app.models import Project, SourceType
from app.pipeline.context import PipelineContext
from app.pipeline.download import Downloader, DownloadResult
from app.pipeline.errors import StageError
from app.workspace import atomic_write_json

UPLOAD_EXTENSIONS = frozenset({".mp4", ".mkv", ".mov", ".webm", ".m4v", ".avi"})


class VideoMeta(BaseModel):
    video_id: str
    source_file: str
    title: str | None = None
    channel: str | None = None
    description: str | None = None
    webpage_url: str | None = None
    duration_s: float
    width: int | None = None
    height: int | None = None
    fps: float | None = None


class IngestStage:
    name = "ingest"
    label = "Importing video"
    weight = 1.0
    uses_gpu = False

    def __init__(self, downloader: Downloader) -> None:
        self._downloader = downloader
        # Two jobs can import the same file at once (video_id is only known after hashing),
        # so placing the source and extracting audio is guarded per video_id.
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _video_lock(self, video_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(video_id, threading.Lock())

    def is_done(self, ctx: PipelineContext) -> bool:
        if ctx.video_id is None:
            return False
        vp = ctx.video()
        return vp.find_source() is not None and vp.audio.exists() and vp.meta.exists()

    def run(self, ctx: PipelineContext) -> None:
        project = repo.get_project(ctx.engine, ctx.project_id)
        if project is None:
            raise StageError("This project no longer exists.")
        already_imported = (
            ctx.video_id is not None
            and ctx.video().find_source() is not None
            and ctx.video().meta.exists()
        )
        if not already_imported:
            self._import_source(ctx, project)
        with self._video_lock(ctx.video_id):
            vp = ctx.video()
            if not vp.audio.exists():
                ctx.progress(self.name, 0.9, "Extracting audio…")
                try:
                    extract_audio(vp.find_source(), vp.audio, cancel=ctx.cancel_event)
                except MediaError as exc:
                    raise StageError("Couldn't extract the audio track.", "Try re-exporting the video as MP4.") from exc

    def _import_source(self, ctx: PipelineContext, project: Project) -> None:
        result = self._acquire(ctx, project)
        ctx.check_cancelled()
        ctx.progress(self.name, 0.8, "Inspecting video…")
        try:
            info = probe(result.path)
        except MediaError as exc:
            raise StageError(
                "This file couldn't be read as a video.",
                "Make sure it's a normal video file (MP4, MKV, MOV, WebM).",
            ) from exc
        if not info.has_video:
            raise StageError("This file has no video track.", "Upload a video file, not audio only.")
        if not info.has_audio:
            raise StageError(
                "This video has no audio track.",
                "ClipForge finds moments from speech, so the video needs sound.",
            )

        video_id = compute_video_id(result.path, info.duration_s)
        title = result.title or (Path(project.original_filename).stem if project.original_filename else None)
        with self._video_lock(video_id):
            vp = ctx.workspace.video(video_id)
            source = vp.find_source()
            if source is None:
                source = vp.dir / f"source{result.path.suffix.lower()}"
                shutil.move(result.path, source)
            else:
                result.path.unlink(missing_ok=True)
            if not vp.meta.exists():
                atomic_write_json(vp.meta, VideoMeta(
                    video_id=video_id, source_file=source.name, title=title,
                    channel=result.channel, description=result.description, webpage_url=result.webpage_url,
                    duration_s=info.duration_s, width=info.width, height=info.height, fps=info.fps,
                ))
        repo.update_project(ctx.engine, project.id, video_id=video_id, title=title, duration_s=info.duration_s)
        ctx.video_id = video_id

    def _acquire(self, ctx: PipelineContext, project: Project) -> DownloadResult:
        project_dir = ctx.workspace.project_dir(project.id)
        if project.source_type == SourceType.url:
            ctx.progress(self.name, 0.0, "Starting download…")
            return self._downloader(
                project.source_url,
                project_dir / "download",
                lambda fraction, message: ctx.progress(self.name, fraction * 0.8, message),
                ctx.cancel_event,
            )
        uploads = [p for p in project_dir.glob("upload.*") if p.suffix.lower() in UPLOAD_EXTENSIONS]
        if not uploads:
            raise StageError("The uploaded file is missing.", "Upload the video again.")
        return DownloadResult(path=uploads[0])

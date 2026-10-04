import hashlib
import json
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

from app.pipeline.errors import StageCancelled

HEAD_BYTES = 64 * 1024 * 1024
_POLL_S = 0.2


class MediaError(Exception):
    pass


@dataclass(frozen=True)
class MediaInfo:
    duration_s: float
    has_video: bool
    has_audio: bool
    width: int | None = None
    height: int | None = None
    fps: float | None = None


def _tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise MediaError(f"{name} was not found on PATH. Install FFmpeg 8 (full build) and restart.")
    return path


def _failure(args: list[str], stderr: str) -> MediaError:
    tail = "\n".join(stderr.strip().splitlines()[-5:])
    return MediaError(f"{Path(args[0]).stem} failed: {tail}")


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise _failure(args, proc.stderr)
    return proc


def _run_cancellable(args: list[str], cancel: threading.Event | None) -> None:
    """Run a tool, polling `cancel`; a cancelled run is terminated (then killed) and raises StageCancelled."""
    proc = subprocess.Popen(
        args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
    )
    while True:
        if cancel is not None and cancel.is_set():
            proc.terminate()
            try:
                proc.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
            raise StageCancelled()
        try:
            _, stderr = proc.communicate(timeout=_POLL_S)
            break
        except subprocess.TimeoutExpired:  # retrying communicate() loses no output
            continue
    if proc.returncode != 0:
        raise _failure(args, stderr or "")


def _parse_fps(rate: str | None) -> float | None:
    if not rate or "/" not in rate:
        return None
    num, den = rate.split("/", 1)
    try:
        n, d = float(num), float(den)
    except ValueError:
        return None
    return round(n / d, 3) if d else None


def probe(path: Path) -> MediaInfo:
    proc = _run([
        _tool("ffprobe"), "-v", "error", "-print_format", "json",
        "-show_streams", "-show_format", str(path),
    ])
    try:
        data = json.loads(proc.stdout or "{}")
        if not isinstance(data, dict):
            raise ValueError("ffprobe did not return a JSON object")
    except ValueError as exc:  # JSONDecodeError is a ValueError
        raise MediaError(f"ffprobe returned unreadable output: {exc}") from exc
    streams = data.get("streams", [])
    video = next(
        (s for s in streams
         if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")),
        None,
    )
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    raw_duration = data.get("format", {}).get("duration") or (video or {}).get("duration") or 0.0
    try:
        duration = float(raw_duration)
    except (TypeError, ValueError) as exc:
        raise MediaError(f"ffprobe reported an invalid duration: {raw_duration!r}") from exc
    if video is None and audio is None:
        raise MediaError("No audio or video streams found")
    return MediaInfo(
        duration_s=duration,
        has_video=video is not None,
        has_audio=audio is not None,
        width=video.get("width") if video else None,
        height=video.get("height") if video else None,
        fps=_parse_fps(video.get("avg_frame_rate")) if video else None,
    )


def _audio_command(src: Path, tmp: Path, sample_rate: int) -> list[str]:
    return [
        _tool("ffmpeg"), "-y", "-v", "error", "-i", str(src),
        "-vn", "-ac", "1", "-ar", str(sample_rate), "-c:a", "pcm_s16le", "-f", "wav", str(tmp),
    ]


def extract_audio(
    src: Path, dst: Path, sample_rate: int = 16000, *, cancel: threading.Event | None = None
) -> None:
    tmp = dst.with_name(dst.name + ".tmp")
    try:
        _run_cancellable(_audio_command(src, tmp, sample_rate), cancel)
        os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)  # no-op after a successful replace


def compute_video_id(path: Path, duration_s: float) -> str:
    digest = hashlib.sha256()
    remaining = HEAD_BYTES
    with path.open("rb") as f:
        while remaining > 0 and (chunk := f.read(min(1024 * 1024, remaining))):
            digest.update(chunk)
            remaining -= len(chunk)
    digest.update(str(path.stat().st_size).encode())
    digest.update(f"{duration_s:.3f}".encode())
    return digest.hexdigest()[:20]

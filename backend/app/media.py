import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

HEAD_BYTES = 64 * 1024 * 1024


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


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-5:])
        raise MediaError(f"{Path(args[0]).stem} failed: {tail}")
    return proc


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
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams", [])
    video = next(
        (s for s in streams
         if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")),
        None,
    )
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = float(data.get("format", {}).get("duration") or (video or {}).get("duration") or 0.0)
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


def extract_audio(src: Path, dst: Path, sample_rate: int = 16000) -> None:
    tmp = dst.with_name(dst.name + ".tmp")
    _run([
        _tool("ffmpeg"), "-y", "-v", "error", "-i", str(src),
        "-vn", "-ac", "1", "-ar", str(sample_rate), "-c:a", "pcm_s16le", "-f", "wav", str(tmp),
    ])
    os.replace(tmp, dst)


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

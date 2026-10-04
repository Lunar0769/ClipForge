import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from app.pipeline.errors import StageCancelled, StageError

ProgressFn = Callable[[float, str | None], None]

_URL_HELP = "Enter a full http(s) link to a video, e.g. https://www.youtube.com/watch?v=…"


def validate_source_url(url: str) -> str:
    candidate = url.strip()
    parsed = urlparse(candidate)
    host = parsed.hostname or ""
    if parsed.scheme.lower() not in {"http", "https"} or "." not in host:
        raise ValueError(_URL_HELP)
    return candidate


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    title: str | None = None
    channel: str | None = None
    description: str | None = None
    webpage_url: str | None = None


class Downloader(Protocol):
    def __call__(
        self, url: str, dest_dir: Path, on_progress: ProgressFn, cancel: threading.Event
    ) -> DownloadResult: ...


def build_ytdlp_options(
    dest_dir: Path, *, max_height: int, cookies_file: Path | None, js_runtime: str | None
) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "format": f"bv*[height<={max_height}]+ba/b[height<={max_height}]/bv*+ba/b",
        "merge_output_format": "mp4",
        "outtmpl": str(dest_dir / "download.%(ext)s"),
        "noplaylist": True,
        "playlist_items": "1",  # guard: never fetch more than one entry, even if a list slips through
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "retries": 3,
        "fragment_retries": 3,
        "overwrites": True,
    }
    if cookies_file:
        opts["cookiefile"] = str(cookies_file)
    if js_runtime:
        # YouTube extraction needs a JS runtime; we use the Node that ships with the frontend toolchain.
        opts["js_runtimes"] = {js_runtime: {}}
    return opts


_UPDATE_HINT = "Update yt-dlp: in backend/ run `uv lock --upgrade-package yt-dlp` then `uv sync`, and press Retry."

_ERROR_RULES: list[tuple[tuple[str, ...], str, str]] = [
    # Before the "is not available" rule: this one means YouTube withheld the streams, not that the video is gone.
    (("requested format is not available",),
     "YouTube blocked the download.",
     _UPDATE_HINT),
    (("sign in to confirm", "confirm your age", "age-restricted", "members-only", "join this channel"),
     "This video needs a signed-in YouTube session.",
     "Export your browser's YouTube cookies to a cookies.txt file and set CLIPFORGE_YTDLP_COOKIES_FILE in .env."),
    (("private video",),
     "This video is private.",
     "Use a public or unlisted video, or upload the file directly."),
    (("video unavailable", "is not available", "has been removed", "account associated with this video has been terminated"),
     "This video is unavailable.",
     "Check the link in your browser, or upload the file directly."),
    (("unsupported url",),
     "This site or link isn't supported.",
     "Paste a link to a video page (YouTube, Vimeo, X, …) or upload the file directly."),
    (("http error 403", "forbidden", "nsig", "signature", "po token", "js runtime", "javascript runtime"),
     "YouTube blocked the download.",
     _UPDATE_HINT),
]


def explain_download_error(raw: str) -> tuple[str, str]:
    low = raw.lower()
    for needles, message, hint in _ERROR_RULES:
        if any(n in low for n in needles):
            return message, hint
    return "The download failed.", f"Check your internet connection and the link. {_UPDATE_HINT}"


class ProgressThrottle:
    """Forwards download progress at most every 1% or 250 ms (yt-dlp calls its hook on every block)."""

    def __init__(self, on_progress: ProgressFn, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._on_progress = on_progress
        self._clock = clock
        self._last_fraction: float | None = None
        self._last_time = 0.0

    def __call__(self, fraction: float, message: str | None) -> None:
        now = self._clock()
        if (
            self._last_fraction is None
            or fraction >= 1.0
            or abs(fraction - self._last_fraction) >= 0.01
            or now - self._last_time >= 0.25
        ):
            self._last_fraction, self._last_time = fraction, now
            self._on_progress(fraction, message)


def _is_playlist(info: dict[str, Any]) -> bool:
    return info.get("_type") == "playlist" or "entries" in info


class YtDlpDownloader:
    def __init__(self, *, max_height: int, cookies_file: Path | None, js_runtime: str | None) -> None:
        self._max_height = max_height
        self._cookies_file = cookies_file
        self._js_runtime = js_runtime

    def __call__(
        self, url: str, dest_dir: Path, on_progress: ProgressFn, cancel: threading.Event
    ) -> DownloadResult:
        import yt_dlp

        dest_dir.mkdir(parents=True, exist_ok=True)
        report = ProgressThrottle(on_progress)

        def hook(d: dict[str, Any]) -> None:
            if cancel.is_set():
                raise yt_dlp.utils.DownloadCancelled("Cancelled by user")
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                if total:
                    pct = (d.get("_percent_str") or "").strip()
                    report(min(d.get("downloaded_bytes", 0) / total, 1.0), f"Downloading… {pct}".strip())

        opts = build_ytdlp_options(
            dest_dir, max_height=self._max_height,
            cookies_file=self._cookies_file, js_runtime=self._js_runtime,
        )
        opts["progress_hooks"] = [hook]
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                # Resolve the link first: noplaylist only covers video+list URLs, so a playlist or
                # channel link would otherwise download every entry.
                info = ydl.extract_info(url, download=False, process=False)
                if _is_playlist(info):
                    raise StageError("This link is a playlist or channel.", "Paste a link to a single video.")
                info = ydl.process_ie_result(info, download=True)
        except yt_dlp.utils.DownloadCancelled as exc:
            raise StageCancelled() from exc
        except yt_dlp.utils.DownloadError as exc:
            if cancel.is_set():
                raise StageCancelled() from exc
            message, hint = explain_download_error(str(exc))
            raise StageError(message, hint) from exc

        return DownloadResult(
            path=_downloaded_path(info, dest_dir),
            title=info.get("title"),
            channel=info.get("channel") or info.get("uploader"),
            description=info.get("description"),
            webpage_url=info.get("webpage_url"),
        )


def _downloaded_path(info: dict[str, Any], dest_dir: Path) -> Path:
    for item in info.get("requested_downloads") or []:
        filepath = item.get("filepath")
        if filepath and Path(filepath).exists():
            return Path(filepath)
    candidates = [
        p for p in dest_dir.glob("download.*") if p.suffix.lower() not in {".part", ".ytdl", ".tmp"}
    ]
    if not candidates:
        raise StageError("The download finished but no video file was found.", "Retry, or upload the file directly.")
    return max(candidates, key=lambda p: p.stat().st_size)

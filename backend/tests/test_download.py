import threading
from pathlib import Path

import pytest
import yt_dlp

from app.pipeline.download import (
    ProgressThrottle,
    YtDlpDownloader,
    build_ytdlp_options,
    explain_download_error,
    validate_source_url,
)
from app.pipeline.errors import StageError


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ?t=30",
    "https://www.youtube.com/shorts/abc123",
    "https://www.youtube.com/watch?v=abc&list=PL123&index=2",
    "http://vimeo.com/12345",
    "  https://youtu.be/x  ",
])
def test_validate_accepts_http_video_links(url):
    assert validate_source_url(url) == url.strip()


@pytest.mark.parametrize("url", ["javascript:alert(1)", "ftp://example.com/a.mp4", "notaurl", "https://", ""])
def test_validate_rejects_non_http_links(url):
    with pytest.raises(ValueError, match="http"):
        validate_source_url(url)


def test_options_never_download_playlists_and_cap_resolution(tmp_path):
    opts = build_ytdlp_options(tmp_path, max_height=1080, cookies_file=None, js_runtime="node")
    assert opts["noplaylist"] is True
    assert opts["playlist_items"] == "1"
    assert "height<=1080" in opts["format"]
    assert opts["merge_output_format"] == "mp4"
    assert opts["outtmpl"] == str(tmp_path / "download.%(ext)s")
    assert opts["js_runtimes"] == {"node": {}}
    assert "cookiefile" not in opts


def test_options_include_cookies_when_configured(tmp_path):
    cookies = tmp_path / "cookies.txt"
    opts = build_ytdlp_options(tmp_path, max_height=720, cookies_file=cookies, js_runtime=None)
    assert opts["cookiefile"] == str(cookies)
    assert "js_runtimes" not in opts


@pytest.mark.parametrize(("raw", "expected_hint_word"), [
    ("ERROR: [youtube] x: Sign in to confirm your age", "cookies"),
    ("ERROR: [youtube] x: Private video. Sign in if you've been granted access", "upload"),
    ("ERROR: [youtube] x: Video unavailable", "upload"),
    ("ERROR: Unsupported URL: https://example.com", "upload"),
    ("ERROR: unable to download video data: HTTP Error 403: Forbidden", "yt-dlp"),
    ("ERROR: something new and weird", "yt-dlp"),
])
def test_explain_download_error(raw, expected_hint_word):
    message, hint = explain_download_error(raw)
    assert message
    assert expected_hint_word in hint.lower()


def test_requested_format_not_available_is_a_block_not_unavailable():
    message, hint = explain_download_error(
        "ERROR: [youtube] abc: Requested format is not available. Use --list-formats for a list of available formats"
    )
    assert message == "YouTube blocked the download."
    assert "yt-dlp" in hint


class FakeYoutubeDL:
    """Stands in for yt_dlp.YoutubeDL: no network, records what was asked."""

    probe_result: dict = {}
    instances: list["FakeYoutubeDL"] = []

    def __init__(self, opts):
        self.opts = opts
        self.calls: list[tuple] = []
        FakeYoutubeDL.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=True, process=True, **kwargs):
        self.calls.append(("extract_info", url, download, process))
        return dict(self.probe_result)

    def process_ie_result(self, ie_result, download=True, extra_info=None):
        self.calls.append(("process_ie_result", ie_result.get("id"), download))
        dest = self.opts["outtmpl"].replace("%(ext)s", "mp4")
        with open(dest, "wb") as f:
            f.write(b"video")
        return {**ie_result, "requested_downloads": [{"filepath": dest}]}


@pytest.fixture
def fake_ytdl(monkeypatch):
    FakeYoutubeDL.instances = []
    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)
    return FakeYoutubeDL


@pytest.mark.parametrize("probe", [
    {"_type": "playlist", "id": "PL1", "title": "My list"},
    {"id": "UC1", "title": "Some channel", "entries": iter([])},
])
def test_playlist_or_channel_links_are_rejected_before_downloading(tmp_path, fake_ytdl, probe):
    fake_ytdl.probe_result = probe
    downloader = YtDlpDownloader(max_height=720, cookies_file=None, js_runtime=None)
    with pytest.raises(StageError) as err:
        downloader("https://www.youtube.com/playlist?list=PL1", tmp_path, lambda f, m: None, threading.Event())
    assert err.value.message == "This link is a playlist or channel."
    assert err.value.hint == "Paste a link to a single video."
    (ydl,) = fake_ytdl.instances
    assert ydl.calls == [("extract_info", "https://www.youtube.com/playlist?list=PL1", False, False)]
    assert not list(tmp_path.iterdir())


def test_single_video_is_probed_then_downloaded(tmp_path, fake_ytdl):
    fake_ytdl.probe_result = {"id": "abc", "title": "A talk", "channel": "Someone", "webpage_url": "https://x/abc"}
    downloader = YtDlpDownloader(max_height=720, cookies_file=None, js_runtime=None)
    result = downloader("https://youtu.be/abc", tmp_path, lambda f, m: None, threading.Event())
    (ydl,) = fake_ytdl.instances
    assert ydl.calls == [("extract_info", "https://youtu.be/abc", False, False), ("process_ie_result", "abc", True)]
    assert ydl.opts["playlist_items"] == "1"
    assert result.path == tmp_path / "download.mp4" and result.path.exists()
    assert (result.title, result.channel) == ("A talk", "Someone")


def test_progress_throttle_publishes_on_1pct_or_250ms_and_always_at_100pct():
    clock = [0.0]
    published = []
    throttle = ProgressThrottle(lambda f, m: published.append(round(f, 4)), clock=lambda: clock[0])
    for i in range(1, 1001):  # 0.1% steps, 1 ms apart
        clock[0] += 0.001
        throttle(i / 1000, None)
    assert 90 <= len(published) <= 110
    assert published[0] == 0.001 and published[-1] == 1.0
    # Tiny moves are still published after 250 ms of silence.
    throttle2_out = []
    clock[0] = 0.0
    t2 = ProgressThrottle(lambda f, m: throttle2_out.append(f), clock=lambda: clock[0])
    t2(0.5, None)
    clock[0] += 0.1
    t2(0.501, None)
    clock[0] += 0.3
    t2(0.502, None)
    assert throttle2_out == [0.5, 0.502]


@pytest.mark.network
def test_real_youtube_download(tmp_path):
    downloader = YtDlpDownloader(max_height=360, cookies_file=None, js_runtime="node")
    result = downloader(
        "https://www.youtube.com/watch?v=jNQXAC9IVRw", tmp_path, lambda f, m: None, threading.Event()
    )
    assert result.path.exists() and result.path.stat().st_size > 0
    assert result.title

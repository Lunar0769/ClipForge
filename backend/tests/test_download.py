import threading
from pathlib import Path

import pytest

from app.pipeline.download import (
    YtDlpDownloader,
    build_ytdlp_options,
    explain_download_error,
    validate_source_url,
)


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


@pytest.mark.network
def test_real_youtube_download(tmp_path):
    downloader = YtDlpDownloader(max_height=360, cookies_file=None, js_runtime="node")
    result = downloader(
        "https://www.youtube.com/watch?v=jNQXAC9IVRw", tmp_path, lambda f, m: None, threading.Event()
    )
    assert result.path.exists() and result.path.stat().st_size > 0
    assert result.title

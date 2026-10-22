import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.pipeline.broll import BRollCue, ensure_broll_media, extract_broll_cues
from app.pipeline.transcript import Word


def test_extract_broll_cues_short_clip():
    cues = extract_broll_cues(0.0, 4.5)
    assert cues == []


def test_extract_broll_cues_finds_contextual_keywords():
    words = [
        Word(text="welcome", start=1.0, end=1.5),
        Word(text="to", start=1.5, end=1.7),
        Word(text="the", start=1.7, end=1.9),
        Word(text="future", start=2.0, end=2.8),
        Word(text="of", start=2.8, end=3.0),
        Word(text="cryptocurrency", start=3.1, end=3.9),
        Word(text="and", start=4.0, end=4.2),
        Word(text="modern", start=10.0, end=10.5),
        Word(text="technology", start=10.6, end=11.5),
    ]

    cues = extract_broll_cues(0.0, 18.0, words=words, keywords=["crypto", "tech"])
    assert len(cues) == 2
    assert cues[0].start_s >= 2.0
    assert cues[0].end_s > cues[0].start_s
    assert cues[0].keyword in ["future", "cryptocurrency", "crypto"]
    assert cues[1].start_s > cues[0].end_s
    assert cues[1].keyword in ["modern", "technology", "tech"]


def test_ensure_broll_media_procedural_fallback(tmp_path):
    cue = BRollCue(start_s=2.0, end_s=4.0, keyword="technology")
    out_file = ensure_broll_media(cue, tmp_path)
    assert out_file.exists()
    assert out_file.stat().st_size > 500
    assert cue.source == "procedural"
    assert cue.video_path == str(out_file)

    # Calling again uses the cached file
    cached_file = ensure_broll_media(cue, tmp_path)
    assert cached_file == out_file


def test_ensure_broll_media_pexels_mock(tmp_path, monkeypatch):
    monkeypatch.setenv("PEXELS_API_KEY", "fake_pexels_key")

    fake_pexels_resp = MagicMock()
    fake_pexels_resp.status_code = 200
    fake_pexels_resp.json.return_value = {
        "videos": [
            {
                "video_files": [
                    {
                        "width": 1080,
                        "height": 1920,
                        "link": "https://fake.pexels.com/download/test.mp4",
                    }
                ]
            }
        ]
    }

    fake_download_resp = MagicMock()
    fake_download_resp.status_code = 200
    fake_download_resp.content = b"fake video bytes for pexels stock cutaway"

    def mock_get(url, **kwargs):
        if "pexels.com/videos/search" in url:
            return fake_pexels_resp
        return fake_download_resp

    monkeypatch.setattr("httpx.get", mock_get)

    cue = BRollCue(start_s=1.0, end_s=3.5, keyword="bitcoin")
    out_file = ensure_broll_media(cue, tmp_path)
    assert out_file.exists()
    assert out_file.read_bytes() == b"fake video bytes for pexels stock cutaway"
    assert cue.source == "pexels"


def _resp(status=200, json=None, content=b""):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json or {}
    r.content = content
    return r


PIXABAY_HITS = {"hits": [
    {"videos": {"medium": {"url": "https://cdn.pixabay.com/wide.mp4", "width": 1920, "height": 1080}}},
    {"videos": {"medium": {"url": "https://cdn.pixabay.com/tall.mp4", "width": 720, "height": 1280}}},
    {"videos": {"medium": {"url": "", "width": 0, "height": 0}}},
]}


def test_pixabay_used_when_it_is_the_only_key_and_picks_tallest(tmp_path, monkeypatch):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    monkeypatch.setenv("PIXABAY_API_KEY", "pix_key")
    fetched = []

    def mock_get(url, **kwargs):
        fetched.append(url)
        if "pixabay.com/api/videos" in url:
            assert kwargs["params"]["key"] == "pix_key"
            return _resp(json=PIXABAY_HITS)
        return _resp(content=b"tall clip bytes")

    monkeypatch.setattr("httpx.get", mock_get)
    cue = BRollCue(start_s=1.0, end_s=3.5, keyword="ocean")
    out = ensure_broll_media(cue, tmp_path)
    assert out.read_bytes() == b"tall clip bytes"
    assert cue.source == "pixabay"
    assert fetched[-1] == "https://cdn.pixabay.com/tall.mp4"


def test_falls_back_to_pixabay_when_pexels_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("PEXELS_API_KEY", "dead_key")
    monkeypatch.setenv("PIXABAY_API_KEY", "pix_key")

    def mock_get(url, **kwargs):
        if "pexels.com" in url:
            return _resp(status=401)
        if "pixabay.com/api/videos" in url:
            return _resp(json=PIXABAY_HITS)
        return _resp(content=b"pixabay bytes")

    monkeypatch.setattr("httpx.get", mock_get)
    cue = BRollCue(start_s=1.0, end_s=3.5, keyword="money")
    ensure_broll_media(cue, tmp_path)
    assert cue.source == "pixabay"


def test_pixabay_errors_never_log_the_key(tmp_path, monkeypatch, caplog):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    monkeypatch.setenv("PIXABAY_API_KEY", "SECRET_PIX_KEY")
    monkeypatch.setattr("httpx.get", lambda url, **kw: _resp(status=400))
    ran = []
    monkeypatch.setattr("app.pipeline.broll._run_cancellable", lambda cmd, cancel, cwd: ran.append(cmd))
    monkeypatch.setattr("app.pipeline.broll._tool", lambda name: name)

    cue = BRollCue(start_s=1.0, end_s=3.5, keyword="rocket")
    ensure_broll_media(cue, tmp_path)
    assert cue.source == "procedural" and ran
    assert "Pixabay returned HTTP 400" in caplog.text
    assert "SECRET_PIX_KEY" not in caplog.text

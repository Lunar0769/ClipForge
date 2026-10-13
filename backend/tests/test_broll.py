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

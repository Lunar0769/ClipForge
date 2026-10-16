from pathlib import Path
from unittest.mock import patch

import pytest

from app.pipeline.fillers import (
    FILLER_WORDS,
    _clean_token,
    build_jumpcut_select_filter,
    detect_silence_and_fillers,
)
from app.pipeline.render import render_clip_video
from app.pipeline.transcript import Word


def test_filler_words_set():
    assert "um" in FILLER_WORDS
    assert "uh" in FILLER_WORDS
    assert "ah" in FILLER_WORDS
    assert "hmm" in FILLER_WORDS
    assert "er" in FILLER_WORDS


def test_clean_token():
    assert _clean_token(" Um... ") == "um"
    assert _clean_token("Uh?!") == "uh"
    assert _clean_token("Awesome") == "awesome"


def test_detect_silence_and_fillers_empty():
    intervals, realigned, saved = detect_silence_and_fillers(
        [],
        clip_start_s=10.0,
        clip_end_s=25.0,
    )
    assert intervals == [(10.0, 25.0)]
    assert realigned == []
    assert saved == 0.0


def test_detect_silence_and_fillers_only_fillers():
    words = [
        Word(text="um", start=10.5, end=11.0),
        Word(text="uh", start=12.0, end=12.5),
    ]
    intervals, realigned, saved = detect_silence_and_fillers(
        words,
        clip_start_s=10.0,
        clip_end_s=15.0,
    )
    # When all words in clip are fillers, fallback to full interval
    assert intervals == [(10.0, 15.0)]
    assert len(realigned) == 2
    assert saved == 0.0


def test_detect_silence_and_fillers_strips_vocal_fillers():
    words = [
        Word(text="So", start=10.2, end=10.6),
        Word(text="um", start=10.8, end=11.2),  # filler
        Word(text="this", start=11.4, end=11.8),
        Word(text="is", start=11.9, end=12.1),
        Word(text="great", start=12.2, end=12.6),
    ]
    intervals, realigned, saved = detect_silence_and_fillers(
        words,
        clip_start_s=10.0,
        clip_end_s=13.0,
    )
    texts = [w.text for w in realigned]
    assert "um" not in texts
    assert "So" in texts
    assert "this" in texts
    assert len(intervals) >= 1


def test_detect_silence_and_fillers_condenses_dead_air():
    # Long 2.5s gap between "hello" and "world"
    words = [
        Word(text="hello", start=1.0, end=1.5),
        # 2.5s pause here
        Word(text="world", start=4.0, end=4.5),
    ]
    intervals, realigned, saved = detect_silence_and_fillers(
        words,
        clip_start_s=0.0,
        clip_end_s=5.0,
        max_pause_s=0.75,
        target_pause_s=0.15,
    )
    # Must have split into two segments
    assert len(intervals) == 2
    assert saved > 1.5  # trimmed substantial dead air
    # "world" timestamp must be compressed
    assert realigned[1].start < 4.0
    assert realigned[0].text == "hello"
    assert realigned[1].text == "world"


def test_build_jumpcut_select_filter_empty():
    v, a = build_jumpcut_select_filter([], clip_start_s=0.0)
    assert v == "null"
    assert a == "anull"


def test_build_jumpcut_select_filter_intervals():
    intervals = [(10.0, 12.0), (14.0, 16.0)]
    v_filter, a_filter = build_jumpcut_select_filter(intervals, clip_start_s=10.0)
    assert "select='between(t,0.000,2.000)+between(t,4.000,6.000)'" in v_filter
    assert "setpts=N/FRAME_RATE/TB" in v_filter
    assert "aselect='between(t,0.000,2.000)+between(t,4.000,6.000)'" in a_filter
    assert "asetpts=N/SR/TB" in a_filter


def test_render_clip_video_with_keep_intervals(tmp_path, monkeypatch):
    source = tmp_path / "src.mp4"
    source.write_bytes(b"dummy")
    out = tmp_path / "out.mp4"

    seen_cmds = []

    def mock_run(cmd, cancel=None, cwd=None):
        seen_cmds.append(cmd)
        for arg in cmd:
            if str(arg).endswith(".mp4"):
                Path(arg).write_bytes(b"rendered")

    monkeypatch.setattr("app.pipeline.render._run_cancellable", mock_run)

    render_clip_video(
        source,
        out,
        start_s=5.0,
        end_s=15.0,
        keep_intervals=[(5.0, 8.0), (10.0, 15.0)],
    )

    assert len(seen_cmds) == 1
    cmd_str = " ".join(seen_cmds[0])
    assert "select='between(t," in cmd_str
    assert "aselect='between(t," in cmd_str

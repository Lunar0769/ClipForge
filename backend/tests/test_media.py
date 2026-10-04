import shutil

import pytest

from app.media import MediaError, compute_video_id, extract_audio, probe


def test_probe_video_with_audio(sample_video):
    info = probe(sample_video)
    assert info.has_video and info.has_audio
    assert (info.width, info.height) == (640, 360)
    assert info.fps == pytest.approx(30, abs=0.1)
    assert info.duration_s == pytest.approx(3, abs=0.2)


def test_probe_video_without_audio(no_audio_video):
    info = probe(no_audio_video)
    assert info.has_video and not info.has_audio


def test_probe_rejects_non_media(tmp_path):
    bogus = tmp_path / "notes.mp4"
    bogus.write_text("definitely not a video")
    with pytest.raises(MediaError):
        probe(bogus)


def test_extract_audio_writes_mono_wav_atomically(sample_video, tmp_path):
    dst = tmp_path / "out dir ü" / "audio.wav"
    dst.parent.mkdir()
    extract_audio(sample_video, dst)
    info = probe(dst)
    assert info.has_audio and not info.has_video
    assert info.duration_s == pytest.approx(3, abs=0.2)
    assert not list(dst.parent.glob("*.tmp"))


def test_video_id_is_content_based(sample_video, silent_video, tmp_path):
    duration = probe(sample_video).duration_s
    copy = tmp_path / "copy.mp4"
    shutil.copy(sample_video, copy)
    vid = compute_video_id(sample_video, duration)
    assert len(vid) == 20
    assert compute_video_id(copy, duration) == vid
    assert compute_video_id(silent_video, probe(silent_video).duration_s) != vid

"""Renders through the real ffmpeg binary (the other render tests mock it, which hid broken commands)."""

import pytest

from app.media import probe
from app.pipeline.captions import write_clip_ass_file
from app.pipeline.render import render_clip_video
from app.pipeline.transcript import Word

WORDS = [Word(text=f" word{i}", start=0.2 + i * 0.4, end=0.5 + i * 0.4) for i in range(6)]


def assert_vertical(path, *, min_s: float, max_s: float, audio: bool = True):
    info = probe(path)
    assert (info.width, info.height) == (1080, 1920)
    assert min_s <= info.duration_s <= max_s
    assert info.has_audio is audio


@pytest.mark.parametrize("layout", ["fit_blur", "track", "split", "gaming"])
@pytest.mark.parametrize("auto_zoom", [True, False])
def test_every_layout_renders(sample_video, tmp_path, layout, auto_zoom):
    dst = tmp_path / "out dir ü" / f"{layout}.mp4"
    dst.parent.mkdir()
    render_clip_video(sample_video, dst, 0.5, 2.5, layout_mode=layout, auto_zoom=auto_zoom)
    assert_vertical(dst, min_s=1.8, max_s=2.3)


def test_captions_music_and_jumpcuts_render(sample_video, tmp_path):
    ass = tmp_path / "c.ass"
    write_clip_ass_file(words=WORDS, clip_start_s=0.0, clip_end_s=3.0, dst_path=ass,
                        style_name="hormozi", hook_text="Watch this")
    dst = tmp_path / "full.mp4"
    render_clip_video(sample_video, dst, 0.0, 3.0, ass_file=ass, music_mood="chill",
                      keep_intervals=[(0.0, 1.0), (1.8, 3.0)])
    assert_vertical(dst, min_s=1.9, max_s=2.5)


def test_source_without_audio_renders_silently(no_audio_video, tmp_path):
    dst = tmp_path / "silent.mp4"
    render_clip_video(no_audio_video, dst, 0.0, 1.5)
    assert_vertical(dst, min_s=1.3, max_s=1.8, audio=False)


def test_zoom_keeps_25fps_sources_in_sync(tmp_path):
    import subprocess
    src = tmp_path / "pal.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=6",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=6", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(src)], check=True)
    dst = tmp_path / "zoomed.mp4"
    render_clip_video(src, dst, 0.0, 6.0, layout_mode="fit_blur", auto_zoom=True)
    assert_vertical(dst, min_s=5.8, max_s=6.2)
    v = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=duration",
                        "-of", "csv=p=0", str(dst)], capture_output=True, text=True).stdout
    assert abs(float(v) - 6.0) < 0.2

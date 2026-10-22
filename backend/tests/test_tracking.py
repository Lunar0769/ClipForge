import json
import subprocess

import numpy as np
import pytest

from app.media import probe
from app.pipeline import render
from app.pipeline.reframe.tracking import (
    Face, Sample, TrackPlan, choose_targets, crop_keyframes, plan_track, smooth_path,
)
from app.pipeline.render import plan_layout, render_clip_video


def face(cx, w=0.15, score=0.9):
    return Face(cx=cx, cy=0.4, w=w, score=score)


def samples(*face_lists, step=0.2):
    return [Sample(t=i * step, faces=list(fs)) for i, fs in enumerate(face_lists)]


def test_follows_main_speaker_and_ignores_small_background_faces():
    s = samples([face(0.3), face(0.8, w=0.03)], [face(0.32), face(0.81, w=0.03)], [face(0.31)])
    assert choose_targets(s, [0]) == [0.3, 0.32, 0.31]


def test_sticks_with_current_speaker_when_two_people_are_visible():
    s = samples([face(0.3, w=0.16)], [face(0.31, w=0.15), face(0.7, w=0.16)])
    assert choose_targets(s, [0]) == [0.3, 0.31]


def test_switches_when_the_main_face_moves_far_away():
    s = samples([face(0.2)], [face(0.75)])
    assert choose_targets(s, [0]) == [0.2, 0.75]


def test_deadzone_ignores_jitter_and_easing_follows_real_moves():
    jitter = smooth_path([0.50, 0.52, 0.49, 0.53, 0.51], [0])
    assert max(jitter) - min(jitter) < 1e-9
    moving = smooth_path([0.3, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6], [0])
    assert moving[0] == 0.3 and moving[1] < 0.45  # eases, doesn't jump
    assert all(a <= b + 1e-9 for a, b in zip(moving, moving[1:]))
    assert 0.6 - moving[-1] <= 0.02  # re-centres on the speaker


def test_cuts_snap_and_shots_without_faces_stay_centred():
    path = smooth_path([0.2, 0.2, 0.8, 0.8, None, None], [0, 2, 4])
    assert path[:4] == [0.2, 0.2, 0.8, 0.8]  # second shot starts on its speaker, no slide
    assert path[4:] == [0.5, 0.5]


def test_missing_detections_hold_the_last_position():
    assert smooth_path([0.3, None, None, 0.31], [0]) == [0.3, 0.3, 0.3, 0.3]


def test_keyframes_stay_inside_the_frame_and_are_even():
    frames = crop_keyframes([0.0, 1.0], [0.0, 1.0], [0], src_w=1920, crop_w=606, duration_s=1.0)
    xs = [x for _, x in frames]
    assert xs[0] == 0 and xs[-1] == 1920 - 606
    assert all(x % 2 == 0 and 0 <= x <= 1920 - 606 for x in xs)
    assert all(a < b for a, b in zip(xs, xs[1:]))  # interpolated per frame, only changes recorded


def test_keyframes_step_at_cuts_instead_of_sliding():
    frames = crop_keyframes([0.0, 0.5, 1.0], [0.2, 0.2, 0.8], [0, 2], src_w=1920, crop_w=606, duration_s=1.0)
    xs = dict(frames)
    assert len(set(xs.values())) == 2  # one jump, no in-between positions


def test_plan_coverage_and_usability():
    good = plan_track(samples(*[[face(0.4)]] * 10), 1920, 1080, 2.0)
    assert good.usable and good.face_coverage == 1.0 and (good.crop_w, good.crop_h) == (606, 1080)
    empty = plan_track(samples(*[[]] * 10), 1920, 1080, 2.0)
    assert not empty.usable


@pytest.fixture
def fake_plan():
    return TrackPlan(src_w=640, src_h=360, crop_w=202, crop_h=360, y=0,
                     keyframes=[(0.0, 0), (1.0, 200), (2.0, 438)], face_coverage=0.9)


def test_plan_layout_passes_through_other_layouts(tmp_path):
    assert plan_layout(tmp_path / "x.mp4", 0, 5, "split", models_dir=tmp_path, cache_file=tmp_path / "c.json") == ("split", None, None)


def test_plan_layout_falls_back_when_no_faces_or_tracking_fails(tmp_path, monkeypatch, fake_plan):
    monkeypatch.setattr(render, "compute_track", lambda *a, **k: fake_plan.model_copy(update={"face_coverage": 0.05}))
    layout, plan, note = plan_layout(tmp_path / "x.mp4", 0, 5, "track", models_dir=tmp_path, cache_file=tmp_path / "a.json")
    assert (layout, plan) == ("fit_blur", None) and "No clear face" in note

    def boom(*a, **k):
        raise RuntimeError("model download failed")
    monkeypatch.setattr(render, "compute_track", boom)
    layout, plan, note = plan_layout(tmp_path / "x.mp4", 0, 5, "track", models_dir=tmp_path, cache_file=tmp_path / "b.json")
    assert layout == "fit_blur" and "wasn't available" in note


def test_plan_layout_caches_per_trim(tmp_path, monkeypatch, fake_plan):
    calls = []
    monkeypatch.setattr(render, "compute_track", lambda *a, **k: calls.append(a) or fake_plan)
    cache = tmp_path / "clip.track.json"
    for _ in range(2):
        assert plan_layout(tmp_path / "x.mp4", 0, 5, "track", models_dir=tmp_path, cache_file=cache)[0] == "track"
    assert len(calls) == 1
    plan_layout(tmp_path / "x.mp4", 1, 5, "track", models_dir=tmp_path, cache_file=cache)  # trimmed: recompute
    assert len(calls) == 2 and json.loads(cache.read_text())["start_s"] == 1


def test_tracked_crop_really_moves(sample_video, tmp_path, fake_plan):
    dst = tmp_path / "out dir ü" / "tracked.mp4"
    dst.parent.mkdir()
    render_clip_video(sample_video, dst, 0.0, 2.5, layout_mode="track", auto_zoom=False, track=fake_plan)
    info = probe(dst)
    assert (info.width, info.height) == (1080, 1920)
    assert not list(dst.parent.glob("*.track.cmd"))  # temp command file cleaned up

    def frame(t):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(dst), "-frames:v", "1",
                              "-vf", "scale=54:96", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                             capture_output=True, check=True).stdout
        return np.frombuffer(raw, dtype=np.uint8).astype(int)

    assert np.abs(frame(0.1) - frame(2.2)).mean() > 10  # a different part of the frame is shown

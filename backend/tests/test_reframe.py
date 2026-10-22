from pathlib import Path

import pytest

from app.pipeline.reframe.layouts import SUPPORTED_LAYOUTS, build_layout_filtergraph
from app.pipeline.render import render_clip_video


def test_supported_layouts_definitions():
    assert "fit_blur" in SUPPORTED_LAYOUTS
    assert "track" in SUPPORTED_LAYOUTS
    assert "split" in SUPPORTED_LAYOUTS
    assert "gaming" in SUPPORTED_LAYOUTS

    for mode, meta in SUPPORTED_LAYOUTS.items():
        assert "name" in meta
        assert "description" in meta
        assert "badge" in meta


def test_build_layout_filtergraph_fit_blur():
    chains = build_layout_filtergraph("fit_blur", auto_zoom=True)
    full = ";".join(chains)
    assert "[base_comp_0]" in full
    assert "boxblur" in full
    assert "zoompan" in full and "fps=30" in full

    chains_no_zoom = build_layout_filtergraph("fit_blur", auto_zoom=False)
    full_no_zoom = ";".join(chains_no_zoom)
    assert "[base_comp_0]" in full_no_zoom
    assert "boxblur" in full_no_zoom
    assert "zoompan" not in full_no_zoom


def test_build_layout_filtergraph_track():
    chains = build_layout_filtergraph("track", auto_zoom=True)
    full = ";".join(chains)
    assert "[base_comp_0]" in full
    assert "min(iw, ih*9/16)" in full
    assert "zoompan" in full

    chains_no_zoom = build_layout_filtergraph("track", auto_zoom=False)
    full_no_zoom = ";".join(chains_no_zoom)
    assert "[base_comp_0]" in full_no_zoom
    assert "zoompan" not in full_no_zoom


def test_build_layout_filtergraph_split():
    chains = build_layout_filtergraph("split", auto_zoom=False)
    full = ";".join(chains)
    assert "[base_comp_0]" in full
    assert "vstack=inputs=2" in full
    assert "crop" in full


def test_build_layout_filtergraph_gaming():
    chains = build_layout_filtergraph("gaming", auto_zoom=False)
    full = ";".join(chains)
    assert "[base_comp_0]" in full
    assert "vstack=inputs=2" in full
    assert "crop" in full


def test_build_layout_filtergraph_fallback():
    # Unknown layout falls back to fit_blur
    chains = build_layout_filtergraph("unknown_invalid_mode", auto_zoom=True)
    full = ";".join(chains)
    assert "[base_comp_0]" in full
    assert "boxblur" in full


def test_render_clip_video_passes_layout_mode(tmp_path, monkeypatch):
    src = tmp_path / "source.mp4"
    src.write_bytes(b"dummy")
    dst = tmp_path / "clip.mp4"

    seen_cmds = []

    def mock_run(cmd, cancel=None, cwd=None):
        seen_cmds.append(cmd)
        for arg in cmd:
            if str(arg).endswith(".mp4"):
                Path(arg).write_bytes(b"rendered")

    monkeypatch.setattr("app.pipeline.render._run_cancellable", mock_run)

    # Track layout
    render_clip_video(src, dst, 0.0, 10.0, layout_mode="track")
    assert any("min(iw, ih*9/16)" in arg for arg in seen_cmds[-1])

    # Split layout
    render_clip_video(src, dst, 0.0, 10.0, layout_mode="split")
    assert any("vstack=inputs=2" in arg for arg in seen_cmds[-1])

    # Gaming layout
    render_clip_video(src, dst, 0.0, 10.0, layout_mode="gaming")
    assert any("cam_box" in arg for arg in seen_cmds[-1])


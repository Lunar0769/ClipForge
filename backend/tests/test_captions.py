from pathlib import Path
from unittest.mock import MagicMock
from app.pipeline.transcript import Word
from app.pipeline.captions import (
    format_ass_time,
    generate_clip_ass,
    write_clip_ass_file,
    PRESETS,
)


def test_format_ass_time():
    assert format_ass_time(0.0) == "0:00:00.00"
    assert format_ass_time(1.5) == "0:00:01.50"
    assert format_ass_time(65.25) == "0:01:05.25"
    assert format_ass_time(3661.12) == "1:01:01.12"


def test_generate_clip_ass_presets():
    words = [
        Word(text="This", start=10.0, end=10.4),
        Word(text="is", start=10.5, end=10.7),
        Word(text="going", start=10.8, end=11.2),
        Word(text="viral", start=11.3, end=11.9),
    ]

    for style_name in ("hormozi", "mrbeast", "neon", "clean"):
        ass_text = generate_clip_ass(
            words=words,
            clip_start_s=10.0,
            clip_end_s=12.0,
            style_name=style_name,
            hook_text="Mind-Blowing Secret",
        )
        assert "[Script Info]" in ass_text
        assert "[V4+ Styles]" in ass_text
        assert "[Events]" in ass_text
        assert "PlayResX: 1080" in ass_text
        assert "PlayResY: 1920" in ass_text
        assert "Dialogue: 1," in ass_text  # Hook card
        assert "MIND-BLOWING SECRET" in ass_text.upper()
        assert "VIRAL" in ass_text.upper()


def test_write_clip_ass_file(tmp_path):
    words = [
        Word(text="Hello", start=0.0, end=0.5),
        Word(text="World", start=0.6, end=1.0),
    ]
    dst = tmp_path / "test.ass"
    res = write_clip_ass_file(words, 0.0, 1.0, dst, style_name="hormozi", hook_text="Intro")
    assert res.exists()
    assert "HELLO" in res.read_text(encoding="utf-8")


def test_rerender_clip_endpoint(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.config import Settings
    from app.workspace import Workspace
    from app.db import make_engine
    from app import repo
    from app.models import SourceType, Clip

    ws = Workspace(tmp_path / "ws")
    db_file = tmp_path / "db.sqlite"
    settings = Settings(data_dir=tmp_path / "data", workspace_dir=tmp_path / "ws", db_url=f"sqlite:///{db_file}")
    engine = make_engine(settings.db_url)

    p = repo.create_project(engine, source_type=SourceType.upload)
    repo.update_project(engine, p.id, video_id="vid123")
    vp = ws.video("vid123")
    vp.dir.mkdir(parents=True, exist_ok=True)
    (vp.dir / "source.mp4").write_bytes(b"dummy video")

    # Write transcript
    transcript_json = '{"language":"en","language_prob":1.0,"duration_s":10.0,"segments":[],"words":[{"text":"Hello","start":0.0,"end":1.0,"prob":1.0}],"sentences":[]}'
    vp.transcript.write_text(transcript_json, encoding="utf-8")

    clip = repo.replace_clips(engine, p.id, [
        Clip(
            project_id=p.id,
            rank=0,
            start_s=0.0,
            end_s=5.0,
            title="Awesome Clip",
            hook_text="Hook Title",
            hook_type="question",
            why_viral="Great",
            score=90,
            sub_scores={},
            keywords=[],
            emoji=[],
            speakers=[],
        )
    ])[0]

    def mock_run_cancellable(cmd, cancel=None, cwd=None):
        for arg in cmd:
            if str(arg).endswith(".mp4"):
                Path(arg).write_bytes(b"rendered")

    monkeypatch.setattr("app.pipeline.render._run_cancellable", mock_run_cancellable)

    app = create_app(settings=settings)
    client = TestClient(app)

    resp = client.post(f"/api/clips/{clip.id}/render", json={"subtitle_style": "mrbeast"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["subtitle_style"] == "mrbeast"
    assert data["video_file"] == f"clips/{clip.id}.mp4"

    # Verify .ass file created with mrbeast style
    ass_file = ws.project_dir(p.id) / "clips" / f"{clip.id}.ass"
    assert ass_file.exists()
    assert "MRBEAST BEAST" in ass_file.read_text(encoding="utf-8") or "Default,Arial Black,66" in ass_file.read_text(encoding="utf-8")

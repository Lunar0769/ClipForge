import sqlite3

import pytest
from pydantic import ValidationError

from app import repo
from app.db import make_engine
from app.models import Clip, SourceType
from app.options import ProjectOptions, project_options


def make_clip(project_id: str, rank: int, start: float) -> Clip:
    return Clip(
        project_id=project_id, rank=rank, start_s=start, end_s=start + 30, title=f"Clip {rank}",
        hook_text="Hook", hook_type="question", why_viral="Because", payoff_summary="Payoff",
        score=90 - rank, sub_scores={"hook": 8}, keywords=["k"], emoji=["🔥"], speakers=["SPEAKER_00"],
    )


def test_phase1_database_is_upgraded_in_place(tmp_path):
    db = tmp_path / "old db ü" / "clipforge.db"
    db.parent.mkdir()
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE project (id VARCHAR PRIMARY KEY, created_at DATETIME, source_type VARCHAR(6), "
        "source_url VARCHAR, original_filename VARCHAR, title VARCHAR, video_id VARCHAR, duration_s FLOAT)"
    )
    con.execute("INSERT INTO project (id, created_at, source_type, title) VALUES ('old1', '2026-10-01 10:00:00', 'url', 'Old')")
    con.commit()
    con.close()

    engine = make_engine(f"sqlite:///{db.as_posix()}")

    old = repo.get_project(engine, "old1")
    assert old.title == "Old" and old.options is None
    assert project_options(old) == ProjectOptions()
    updated = repo.update_project(engine, "old1", options={"clip_count": 5, "min_duration_s": 20, "max_duration_s": 40})
    assert updated.options["clip_count"] == 5
    assert repo.list_clips(engine, "old1") == []


def test_project_options_defaults_and_validation():
    opts = ProjectOptions()
    assert (opts.clip_count, opts.min_duration_s, opts.max_duration_s) == (10, 30, 60)
    assert ProjectOptions(clip_count=3, min_duration_s=15, max_duration_s=20).max_duration_s == 20
    with pytest.raises(ValidationError):
        ProjectOptions(clip_count=2)
    with pytest.raises(ValidationError):
        ProjectOptions(min_duration_s=40, max_duration_s=42)
    with pytest.raises(ValidationError):
        ProjectOptions(max_duration_s=91)
    assert ProjectOptions().fingerprint() == ProjectOptions().fingerprint()
    assert ProjectOptions().fingerprint() != ProjectOptions(clip_count=11).fingerprint()


def test_create_project_with_options(engine):
    p = repo.create_project(engine, source_type=SourceType.url, source_url="https://youtu.be/x", options={"clip_count": 12})
    assert project_options(repo.get_project(engine, p.id)).clip_count == 12


def test_settings_roundtrip_and_upsert(engine):
    assert repo.get_setting(engine, "ai") is None
    repo.put_setting(engine, "ai", {"a": 1})
    repo.put_setting(engine, "ai", {"a": 2, "b": "x"})
    assert repo.get_setting(engine, "ai") == {"a": 2, "b": "x"}


def test_replace_and_list_clips(engine):
    p = repo.create_project(engine, source_type=SourceType.upload)
    repo.replace_clips(engine, p.id, [make_clip(p.id, 2, 50.0), make_clip(p.id, 1, 10.0)])
    first = repo.list_clips(engine, p.id)
    assert [c.rank for c in first] == [1, 2]
    assert first[0].emoji == ["🔥"] and first[0].sub_scores == {"hook": 8}
    assert repo.get_clip(engine, first[0].id).title == "Clip 1"

    repo.replace_clips(engine, p.id, [make_clip(p.id, 1, 99.0)])
    again = repo.list_clips(engine, p.id)
    assert len(again) == 1 and again[0].start_s == 99.0
    assert repo.get_clip(engine, first[0].id) is None


def test_delete_project_deletes_clips(engine):
    p = repo.create_project(engine, source_type=SourceType.upload)
    [clip] = repo.replace_clips(engine, p.id, [make_clip(p.id, 1, 0.0)])
    repo.delete_project(engine, p.id)
    assert repo.get_clip(engine, clip.id) is None


def test_pick_scorer_prioritizes_gemini_when_set(monkeypatch):
    from app.pipeline.score import _pick_scorer, Candidate, _safe_score

    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    scorer, label = _pick_scorer()
    assert scorer is not None
    assert label == "gemini-3.5-flash-lite"

    # Verify fallback on failure
    bad_scorer = lambda txt: (_ for _ in ()).throw(RuntimeError("API error"))
    cand = Candidate(start=0.0, end=30.0, text="This is an exciting moment in the podcast.")
    res = _safe_score(bad_scorer, cand)
    assert res is not None
    assert "score" in res
    assert "title" in res


def test_update_clip_video_files(engine):
    p = repo.create_project(engine, source_type=SourceType.upload)
    [clip] = repo.replace_clips(engine, p.id, [make_clip(p.id, 1, 0.0)])
    assert clip.video_file is None
    assert clip.thumbnail_file is None

    updated = repo.update_clip(
        engine, clip.id, video_file=f"clips/{clip.id}.mp4", thumbnail_file=f"clips/{clip.id}.jpg"
    )
    assert updated.video_file == f"clips/{clip.id}.mp4"
    assert updated.thumbnail_file == f"clips/{clip.id}.jpg"
    refetched = repo.get_clip(engine, clip.id)
    assert refetched.video_file == f"clips/{clip.id}.mp4"


def test_render_stage_is_done_contract(engine, tmp_path):
    from unittest.mock import MagicMock
    from app.pipeline.render import RenderStage
    from app.workspace import Workspace

    stage = RenderStage()
    ws = Workspace(tmp_path / "ws")
    p = repo.create_project(engine, source_type=SourceType.upload)
    ctx = MagicMock()
    ctx.engine = engine
    ctx.project_id = p.id
    ctx.workspace = ws

    # No clips yet -> not done
    assert not stage.is_done(ctx)

    # Clips exist but not rendered -> not done
    [clip] = repo.replace_clips(engine, p.id, [make_clip(p.id, 1, 0.0)])
    assert not stage.is_done(ctx)

    # File created on disk and recorded in DB -> is_done returns True
    clips_dir = ws.project_dir(p.id) / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    video_file = clips_dir / f"{clip.id}.mp4"
    video_file.write_bytes(b"dummy mp4")

    repo.update_clip(engine, clip.id, video_file=f"clips/{clip.id}.mp4")
    assert stage.is_done(ctx)


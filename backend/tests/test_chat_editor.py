from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import Clip, SourceType
from app.pipeline.chat_editor import EditCommand, apply_edit_command, parse_edit_instruction


def test_apply_edit_command_trim():
    clip = Clip(
        id="c1",
        project_id="p1",
        rank=0,
        start_s=10.0,
        end_s=30.0,
        title="Test Clip",
        hook_text="Hook",
        hook_type="statement",
        why_viral="Viral",
        score=90,
    )
    cmd = EditCommand(intent="trim", start_s=12.0, end_s=28.0)
    changes = apply_edit_command(cmd, clip)

    assert changes == {"start_s": 12.0, "end_s": 28.0}
    assert clip.start_s == 12.0
    assert clip.end_s == 28.0


def test_apply_edit_command_style_and_pacing():
    clip = Clip(
        id="c2",
        project_id="p1",
        rank=1,
        start_s=0.0,
        end_s=20.0,
        title="Style Test",
        hook_text="Hook",
        hook_type="question",
        why_viral="Why",
        score=85,
        subtitle_style="hormozi",
        filler_trim=False,
    )
    cmd = EditCommand(intent="style", subtitle_style="neon", filler_trim=True)
    changes = apply_edit_command(cmd, clip)

    assert changes["subtitle_style"] == "neon"
    assert changes["filler_trim"] is True
    assert clip.subtitle_style == "neon"
    assert clip.filler_trim is True


def test_apply_edit_command_layout_and_mood():
    clip = Clip(
        id="c3",
        project_id="p1",
        rank=2,
        start_s=5.0,
        end_s=25.0,
        title="Layout Test",
        hook_text="Hook",
        hook_type="stat",
        why_viral="Why",
        score=88,
        layout_mode="fit_blur",
        music_mood=None,
    )
    cmd = EditCommand(intent="layout", layout_mode="gaming")
    changes = apply_edit_command(cmd, clip)
    assert changes == {"layout_mode": "gaming"}
    assert clip.layout_mode == "gaming"

    mood_cmd = EditCommand(intent="mood", music_mood="energetic")
    mood_changes = apply_edit_command(mood_cmd, clip)
    assert mood_changes == {"music_mood": "energetic"}
    assert clip.music_mood == "energetic"


def test_apply_edit_command_reset():
    clip = Clip(
        id="c4",
        project_id="p1",
        rank=3,
        start_s=0.0,
        end_s=30.0,
        title="Reset Test",
        hook_text="Hook",
        hook_type="story",
        why_viral="Why",
        score=80,
        subtitle_style="neon",
        filler_trim=True,
        music_mood="chill",
        broll_enabled=True,
        layout_mode="split",
    )
    cmd = EditCommand(intent="reset")
    changes = apply_edit_command(cmd, clip)

    assert clip.subtitle_style == "hormozi"
    assert clip.filler_trim is False
    assert clip.music_mood is None
    assert clip.broll_enabled is False
    assert clip.layout_mode == "track"
    assert changes["subtitle_style"] == "hormozi"


def test_parse_edit_instruction_mock_llm():
    mock_engine = MagicMock()
    with patch("app.pipeline.chat_editor.generate_json") as mock_gen:
        mock_gen.return_value = {
            "intent": "speed",
            "filler_trim": True,
            "summary": "Enabled fast pacing by cutting pauses and filler words",
            "understood": True,
        }
        cmd = parse_edit_instruction(
            instruction="make it faster cut out pauses",
            clip_start_s=0.0,
            clip_end_s=20.0,
            clip_title="Interview clip",
            clip_hook="Wait for it",
            engine=mock_engine,
        )

        assert cmd.intent == "speed"
        assert cmd.filler_trim is True
        assert cmd.understood is True
        assert "fast pacing" in cmd.summary


def test_parse_edit_instruction_handles_error():
    mock_engine = MagicMock()
    with patch("app.pipeline.chat_editor.generate_json", side_effect=Exception("API timeout")):
        cmd = parse_edit_instruction(
            instruction="something weird",
            clip_start_s=0.0,
            clip_end_s=20.0,
            clip_title="Test",
            clip_hook="Test",
            engine=mock_engine,
        )

        assert cmd.intent == "unknown"
        assert cmd.understood is False
        assert "couldn't understand" in cmd.summary


def test_chat_edit_endpoint_applies_and_persists(settings, monkeypatch):
    from app import repo

    app = create_app(settings)
    engine = app.state.services.engine

    project = repo.create_project(engine, source_type=SourceType.upload, title="Test Project")
    p_id = project.id

    repo.replace_clips(engine, p_id, [
        Clip(
            id="chat_clip_1",
            project_id=p_id,
            rank=0,
            start_s=5.0,
            end_s=25.0,
            title="Before Edit",
            hook_text="Old Hook",
            hook_type="statement",
            why_viral="Viral",
            score=90,
            subtitle_style="hormozi",
        )
    ])

    monkeypatch.setattr(
        "app.pipeline.chat_editor.generate_json",
        lambda **kwargs: {
            "intent": "style",
            "subtitle_style": "neon",
            "filler_trim": True,
            "summary": "Switched to neon captions and enabled fast jump-cuts",
            "understood": True,
        },
    )

    rerender_called = []
    monkeypatch.setattr(
        "app.api.clips._trigger_rerender",
        lambda clip_id, svc: rerender_called.append(clip_id),
    )

    with TestClient(app) as client:
        res = client.post(
            "/api/clips/chat_clip_1/chat-edit",
            json={"instruction": "give it neon captions and make it fast paced"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["understood"] is True
        assert data["intent"] == "style"
        assert data["changes"]["subtitle_style"] == "neon"
        assert data["changes"]["filler_trim"] is True
        assert data["rerender_triggered"] is True
        assert rerender_called == ["chat_clip_1"]

    # Verify clip was updated in DB
    refreshed = repo.get_clip(engine, "chat_clip_1")
    assert refreshed.subtitle_style == "neon"
    assert refreshed.filler_trim is True

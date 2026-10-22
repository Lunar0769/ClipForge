import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.llm import LLMError
from app.pipeline.dubbing import (
    SUPPORTED_LANGUAGES,
    DubbingError,
    generate_dubbed_clip_audio,
    synthesize_speech,
    translate_segments,
    translate_text,
)
from app.pipeline.transcript import Word


def test_supported_languages_schema():
    assert "es" in SUPPORTED_LANGUAGES
    assert "de" in SUPPORTED_LANGUAGES
    assert "fr" in SUPPORTED_LANGUAGES
    assert "hi" in SUPPORTED_LANGUAGES
    assert "ja" in SUPPORTED_LANGUAGES
    assert "pt" in SUPPORTED_LANGUAGES
    assert "it" in SUPPORTED_LANGUAGES

    for lang, info in SUPPORTED_LANGUAGES.items():
        assert "voice" in info
        assert "name" in info
        assert "label" in info


def _fake_translations(prefix="ES"):
    def fake(system, prompt, **kwargs):
        lines = json.loads(prompt)["lines"]
        return {"translations": [f"{prefix} {line}" for line in lines]}, "fake/model"
    return fake


async def _fake_tts(text, voice, out_path):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.6",
                    "-c:a", "libmp3lame", str(out_path)], check=True)
    return True


def test_translate_passthrough_cases():
    assert translate_text("", "es") == ""
    assert translate_text("hello world", "unsupported_lang") == "hello world"


def test_translate_without_ai_fails_clearly(monkeypatch):
    def no_ai(*args, **kwargs):
        raise LLMError("No AI provider is set up.", "Open Settings and add a key.")
    monkeypatch.setattr("app.pipeline.dubbing.generate_json", no_ai)
    with pytest.raises(DubbingError, match="Translation needs an AI provider"):
        translate_text("welcome to the future of technology", "es")


def test_translate_batches_all_lines_in_one_call(monkeypatch):
    calls = []
    def fake(system, prompt, **kwargs):
        calls.append(prompt)
        return {"translations": ["Hola.", "Adiós."]}, "fake/model"
    monkeypatch.setattr("app.pipeline.dubbing.generate_json", fake)
    assert translate_segments(["Hello.", "Goodbye."], "es") == ["Hola.", "Adiós."]
    assert len(calls) == 1 and "Spanish" not in calls[0]


def test_incomplete_translation_is_an_error(monkeypatch):
    monkeypatch.setattr("app.pipeline.dubbing.generate_json", lambda *a, **k: ({"translations": ["Hola."]}, "m"))
    with pytest.raises(DubbingError, match="incomplete"):
        translate_segments(["Hello.", "Goodbye."], "es")


def test_speech_failure_is_an_error_not_a_buzz(tmp_path, monkeypatch):
    async def offline(text, voice, out_path):
        raise OSError("network unreachable")
    monkeypatch.setattr("app.pipeline.dubbing._synthesize_edge_tts", offline)
    with pytest.raises(DubbingError, match="internet"):
        synthesize_speech("Hola mundo", "es", tmp_path / "dub.mp3", duration_s=1.5)


def test_generate_dubbed_clip_audio(tmp_path, monkeypatch):
    monkeypatch.setattr("app.pipeline.dubbing.generate_json", _fake_translations())
    monkeypatch.setattr("app.pipeline.dubbing._synthesize_edge_tts", _fake_tts)
    words = [
        Word(text="welcome", start=1.0, end=1.5),
        Word(text="to", start=1.5, end=1.7),
        Word(text="the", start=1.7, end=1.9),
        Word(text="future.", start=2.0, end=2.8),
        Word(text="Really", start=3.0, end=3.3),
    ]
    out_path, translated_words = generate_dubbed_clip_audio(
        words=words, clip_start_s=0.5, clip_end_s=3.5, target_lang="es", dst_path=tmp_path / "final dub.mp3",
    )
    assert out_path.exists() and out_path.stat().st_size > 100
    assert [w.text.strip() for w in translated_words][:2] == ["ES", "welcome"]
    for tw in translated_words:
        assert 0.5 <= tw.start <= tw.end <= 3.6


def test_clip_without_speech_cannot_be_dubbed(tmp_path):
    with pytest.raises(DubbingError, match="no speech"):
        generate_dubbed_clip_audio(words=[], clip_start_s=0, clip_end_s=3, target_lang="es", dst_path=tmp_path / "x.mp3")

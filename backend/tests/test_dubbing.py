import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.pipeline.dubbing import (
    FALLBACK_PHRASES,
    SUPPORTED_LANGUAGES,
    generate_dubbed_clip_audio,
    synthesize_speech,
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


def test_translate_text_fallback_dictionary():
    assert translate_text("", "es") == ""
    assert translate_text("hello world", "unsupported_lang") == "hello world"

    # Fallback dictionary test
    res = translate_text("welcome to the future of technology", "es")
    assert "bienvenidos" in res
    assert "futuro" in res
    assert "tecnología" in res


def test_translate_text_gemini_mock(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake_gemini_key")

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": "Bienvenidos al emocionante futuro de la tecnología."}]
                }
            }
        ]
    }

    monkeypatch.setattr("httpx.post", lambda url, **kwargs: fake_resp)

    translated = translate_text("Welcome to the exciting future of technology.", "es")
    assert translated == "Bienvenidos al emocionante futuro de la tecnología."


def test_synthesize_speech_procedural_fallback(tmp_path):
    out_file = tmp_path / "dub_test.mp3"
    res_path = synthesize_speech("Hola mundo", "es", out_file, duration_s=1.5)
    assert res_path.exists()
    assert res_path.stat().st_size > 100


def test_generate_dubbed_clip_audio(tmp_path):
    words = [
        Word(text="welcome", start=1.0, end=1.5),
        Word(text="to", start=1.5, end=1.7),
        Word(text="the", start=1.7, end=1.9),
        Word(text="future.", start=2.0, end=2.8),
    ]

    dst_audio = tmp_path / "final_dubbed.mp3"
    out_path, translated_words = generate_dubbed_clip_audio(
        words=words,
        clip_start_s=0.5,
        clip_end_s=3.5,
        target_lang="es",
        dst_path=dst_audio,
    )

    assert out_path.exists()
    assert out_path.stat().st_size > 100
    assert len(translated_words) > 0
    # Translated words should have relative timestamps between 0 and 3.0
    for tw in translated_words:
        assert tw.start >= 0.0
        assert tw.end <= 3.1
        assert tw.end >= tw.start

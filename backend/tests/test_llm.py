import json

import httpx
import pytest

from app import llm, repo
from app.llm import LLMError, ProviderConfig, configured_providers, generate_json, parse_json_text


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OLLAMA_HOST", "CLIPFORGE_LLM_PROVIDER", "OLLAMA_MODEL"):
        monkeypatch.delenv(var, raising=False)


def test_parse_json_text_tolerates_fences_and_prose():
    assert parse_json_text('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_text('Sure! {"a": [1, 2]}') == {"a": [1, 2]}
    with pytest.raises(ValueError):
        parse_json_text("no json here")


def test_providers_from_env_and_settings_with_preference(engine, monkeypatch):
    assert configured_providers(engine) == []
    monkeypatch.setenv("GEMINI_API_KEY", "env-gemini")
    monkeypatch.setenv("OPENAI_API_KEY", "env-openai")
    assert [p.name for p in configured_providers(engine)] == ["gemini", "openai"]
    repo.put_setting(engine, "app", {"provider": "openai", "gemini_api_key": "db-gemini"})
    providers = configured_providers(engine)
    assert [p.name for p in providers] == ["openai", "gemini"]
    assert providers[1].secret == "db-gemini"


def test_no_provider_points_to_settings(engine):
    with pytest.raises(LLMError) as err:
        generate_json("s", "p", engine=engine)
    assert "Settings" in err.value.hint


class FakeResponse:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.text = json.dumps(body)

    def json(self):
        return self._body


def gemini_body(text, thought=False):
    parts = [{"text": "thinking...", "thought": True}] if thought else []
    return {"candidates": [{"content": {"parts": parts + [{"text": text}]}}]}


def test_gemini_sends_key_in_header_and_skips_retired_models(monkeypatch):
    seen = []

    def fake_post(url, json=None, headers=None, timeout=None):
        seen.append((url, headers))
        if "flash-lite" in url:
            return FakeResponse(404, {"error": "gone"})
        return FakeResponse(200, gemini_body('{"ok": true}', thought=True))

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setenv("GEMINI_API_KEY", "secret-key-123")
    data, model = generate_json("s", "p")
    assert data == {"ok": True} and model == "gemini/gemini-3.5-flash"
    assert all("secret-key-123" not in url and "key=" not in url for url, _ in seen)
    assert seen[0][1] == {"x-goog-api-key": "secret-key-123"}


def test_busy_provider_is_retried_then_next_provider_used(monkeypatch):
    calls = {"gemini": 0, "openai": 0}

    def fake_gemini(cfg, *args):
        calls["gemini"] += 1
        raise llm._Retryable("Gemini is busy (HTTP 503)")

    def fake_openai(cfg, *args):
        calls["openai"] += 1
        return '{"moments": []}', cfg.model

    monkeypatch.setitem(llm._CALLERS, "gemini", fake_gemini)
    monkeypatch.setitem(llm._CALLERS, "openai", fake_openai)
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    slept = []
    data, model = generate_json("s", "p", sleep=slept.append)
    assert data == {"moments": []} and model.startswith("openai/")
    assert calls == {"gemini": 3, "openai": 1} and slept == [2.0, 4.0]


def test_invalid_json_is_asked_again(monkeypatch):
    replies = iter(["not json", '{"ok": 1}'])
    monkeypatch.setitem(llm._CALLERS, "gemini", lambda cfg, *a: (next(replies), "m"))
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    assert generate_json("s", "p")[0] == {"ok": 1}


def test_rejected_key_fails_with_details(monkeypatch):
    def bad(cfg, *args):
        raise RuntimeError("Gemini rejected the request (HTTP 400): API key not valid")

    monkeypatch.setitem(llm._CALLERS, "gemini", bad)
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    with pytest.raises(LLMError) as err:
        generate_json("s", "p")
    assert "API key not valid" in err.value.hint


def test_anthropic_uses_sdk_with_current_model(monkeypatch):
    captured = {}

    class FakeMessages:
        def create(self, **kwargs):
            captured.update(kwargs)
            block = type("B", (), {"type": "text", "text": '{"ok": true}'})()
            return type("R", (), {"stop_reason": "end_turn", "content": [block]})()

    class FakeClient:
        def __init__(self, **kwargs):
            self.messages = FakeMessages()

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    text, model = llm._call_anthropic(ProviderConfig("anthropic", "k", llm.ANTHROPIC_MODEL), "s", "p", 1000, "low")
    assert text == '{"ok": true}' and model == "claude-opus-5-5"
    assert captured["thinking"] == {"type": "adaptive"} and captured["output_config"] == {"effort": "low"}
    assert captured["extra_body"] == {"fallbacks": "default"}

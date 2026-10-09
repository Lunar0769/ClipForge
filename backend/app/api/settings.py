"""Settings API — Provider Keys, Defaults, and Configuration."""
import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import repo
from app.api.deps import Services, get_services

logger = logging.getLogger(__name__)
router = APIRouter(tags=["settings"])


class SettingsOut(BaseModel):
    provider: str | None = None
    gemini_key_set: bool = False
    openai_key_set: bool = False
    anthropic_key_set: bool = False
    ollama_host: str | None = None
    default_subtitle_style: str = "hormozi"
    default_auto_zoom: bool = True
    default_music_mood: str | None = None


class SettingsUpdate(BaseModel):
    provider: str | None = None
    gemini_api_key: str | None = None
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    ollama_host: str | None = None
    default_subtitle_style: str | None = None
    default_auto_zoom: bool | None = None
    default_music_mood: str | None = None


class ProviderTestRequest(BaseModel):
    provider: str
    api_key: str | None = None
    ollama_host: str | None = None


class ProviderTestResponse(BaseModel):
    ok: bool
    message: str
    model: str | None = None


def _load_settings_dict(svc: Services) -> dict[str, Any]:
    return repo.get_setting(svc.engine, "app") or {}


@router.get("/settings", response_model=SettingsOut)
def get_settings(svc: Services = Depends(get_services)) -> SettingsOut:
    stored = _load_settings_dict(svc)

    provider = stored.get("provider") or os.environ.get("CLIPFORGE_LLM_PROVIDER")
    gemini_key = stored.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY")
    openai_key = stored.get("openai_api_key") or os.environ.get("OPENAI_API_KEY")
    anthropic_key = stored.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")
    ollama_host = stored.get("ollama_host") or os.environ.get("OLLAMA_HOST")

    return SettingsOut(
        provider=provider,
        gemini_key_set=bool(gemini_key),
        openai_key_set=bool(openai_key),
        anthropic_key_set=bool(anthropic_key),
        ollama_host=ollama_host,
        default_subtitle_style=stored.get("default_subtitle_style", "hormozi"),
        default_auto_zoom=stored.get("default_auto_zoom", True),
        default_music_mood=stored.get("default_music_mood"),
    )


@router.put("/settings", response_model=SettingsOut)
def update_settings(req: SettingsUpdate, svc: Services = Depends(get_services)) -> SettingsOut:
    stored = _load_settings_dict(svc)

    if req.provider is not None:
        stored["provider"] = req.provider.strip()
        os.environ["CLIPFORGE_LLM_PROVIDER"] = req.provider.strip()
    if req.gemini_api_key is not None:
        key = req.gemini_api_key.strip()
        if key:
            stored["gemini_api_key"] = key
            os.environ["GEMINI_API_KEY"] = key
        else:
            stored.pop("gemini_api_key", None)
            os.environ.pop("GEMINI_API_KEY", None)

    if req.openai_api_key is not None:
        key = req.openai_api_key.strip()
        if key:
            stored["openai_api_key"] = key
            os.environ["OPENAI_API_KEY"] = key
        else:
            stored.pop("openai_api_key", None)
            os.environ.pop("OPENAI_API_KEY", None)

    if req.anthropic_api_key is not None:
        key = req.anthropic_api_key.strip()
        if key:
            stored["anthropic_api_key"] = key
            os.environ["ANTHROPIC_API_KEY"] = key
        else:
            stored.pop("anthropic_api_key", None)
            os.environ.pop("ANTHROPIC_API_KEY", None)

    if req.ollama_host is not None:
        host = req.ollama_host.strip()
        if host:
            stored["ollama_host"] = host
            os.environ["OLLAMA_HOST"] = host
        else:
            stored.pop("ollama_host", None)
            os.environ.pop("OLLAMA_HOST", None)

    if req.default_subtitle_style is not None:
        stored["default_subtitle_style"] = req.default_subtitle_style
    if req.default_auto_zoom is not None:
        stored["default_auto_zoom"] = req.default_auto_zoom
    if req.default_music_mood is not None:
        stored["default_music_mood"] = req.default_music_mood

    repo.put_setting(svc.engine, "app", stored)
    return get_settings(svc)


@router.post("/settings/test", response_model=ProviderTestResponse)
def test_provider(req: ProviderTestRequest, svc: Services = Depends(get_services)) -> ProviderTestResponse:
    stored = _load_settings_dict(svc)
    provider = req.provider.lower().strip()

    if provider == "gemini":
        key = req.api_key or stored.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise HTTPException(400, "Gemini API key is required")
        import httpx
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}"
        try:
            resp = httpx.post(url, json={"contents": [{"parts": [{"text": "ping"}]}]}, timeout=15)
            if resp.status_code == 200:
                return ProviderTestResponse(ok=True, message="Connected successfully to Google Gemini!", model="gemini-2.0-flash")
            return ProviderTestResponse(ok=False, message=f"Gemini API returned error: {resp.text[:200]}")
        except Exception as e:
            return ProviderTestResponse(ok=False, message=f"Connection error: {e}")

    elif provider == "openai":
        key = req.api_key or stored.get("openai_api_key") or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise HTTPException(400, "OpenAI API key is required")
        import httpx
        url = "https://api.openai.com/v1/chat/completions"
        try:
            resp = httpx.post(
                url,
                json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "ping"}], "max_tokens": 5},
                headers={"Authorization": f"Bearer {key}"},
                timeout=15,
            )
            if resp.status_code == 200:
                return ProviderTestResponse(ok=True, message="Connected successfully to OpenAI!", model="gpt-4o-mini")
            return ProviderTestResponse(ok=False, message=f"OpenAI API error: {resp.text[:200]}")
        except Exception as e:
            return ProviderTestResponse(ok=False, message=f"Connection error: {e}")

    elif provider == "anthropic":
        key = req.api_key or stored.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise HTTPException(400, "Anthropic API key is required")
        import httpx
        url = "https://api.anthropic.com/v1/messages"
        try:
            resp = httpx.post(
                url,
                json={"model": "claude-3-5-haiku-20241022", "messages": [{"role": "user", "content": "ping"}], "max_tokens": 5},
                headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                timeout=15,
            )
            if resp.status_code == 200:
                return ProviderTestResponse(ok=True, message="Connected successfully to Anthropic Claude!", model="claude-3-5-haiku")
            return ProviderTestResponse(ok=False, message=f"Anthropic API error: {resp.text[:200]}")
        except Exception as e:
            return ProviderTestResponse(ok=False, message=f"Connection error: {e}")

    elif provider == "ollama":
        host = req.ollama_host or stored.get("ollama_host") or os.environ.get("OLLAMA_HOST") or "http://localhost:11434"
        import httpx
        try:
            resp = httpx.get(f"{host.rstrip('/')}/api/tags", timeout=10)
            if resp.status_code == 200:
                models = [m.get("name") for m in resp.json().get("models", [])]
                return ProviderTestResponse(
                    ok=True,
                    message=f"Connected to Ollama! Available models: {', '.join(models[:4]) or 'none'}",
                    model=models[0] if models else "ollama",
                )
            return ProviderTestResponse(ok=False, message=f"Ollama returned HTTP {resp.status_code}")
        except Exception as e:
            return ProviderTestResponse(ok=False, message=f"Could not reach Ollama at {host}: {e}")

    raise HTTPException(400, f"Unsupported provider: {provider}")

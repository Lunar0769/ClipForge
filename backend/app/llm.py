"""Shared access to the AI providers used for moment scoring, SEO packs and the Settings "test" button.

One place owns API keys, model choices, retries and log hygiene:
- keys come from Settings (database) first, then the environment / .env;
- keys travel in request headers, never in URLs (httpx logs URLs);
- busy/overloaded answers (429/5xx/timeouts) are retried with backoff, then the next provider is tried;
- callers get parsed JSON or a clear LLMError — never invented results.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from sqlalchemy import Engine

from app import repo

logger = logging.getLogger(__name__)

Provider = Literal["gemini", "anthropic", "openai", "ollama"]
Effort = Literal["low", "medium", "high"]
DEFAULT_ORDER: tuple[Provider, ...] = ("gemini", "anthropic", "openai", "ollama")

GEMINI_MODELS = ("gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-flash-latest")
ANTHROPIC_MODEL = "claude-opus-5-5"
OPENAI_MODEL = "gpt-5-mini"
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "llama3.2"

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}

# Settings keys (database) → environment variable fallbacks.
_SECRETS = {
    "gemini": ("gemini_api_key", "GEMINI_API_KEY"),
    "anthropic": ("anthropic_api_key", "ANTHROPIC_API_KEY"),
    "openai": ("openai_api_key", "OPENAI_API_KEY"),
    "ollama": ("ollama_host", "OLLAMA_HOST"),
}


class LLMError(Exception):
    """No configured provider produced a usable answer. `hint` tells the user what to do."""

    def __init__(self, message: str, hint: str) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class _Retryable(Exception):
    """A transient failure worth retrying on the same provider/model."""


@dataclass(frozen=True)
class ProviderConfig:
    name: Provider
    secret: str  # API key, or host URL for Ollama
    model: str


def _stored(engine: Engine | None) -> dict[str, Any]:
    if engine is None:
        return {}
    try:
        return repo.get_setting(engine, "app") or {}
    except Exception:  # settings table unavailable (very old database, tests without DB)
        return {}


def configured_providers(engine: Engine | None = None) -> list[ProviderConfig]:
    """Configured providers, preferred one first (Settings → provider, or CLIPFORGE_LLM_PROVIDER)."""
    stored = _stored(engine)
    preferred = (stored.get("provider") or os.environ.get("CLIPFORGE_LLM_PROVIDER") or "").strip().lower()
    order = [preferred] if preferred in DEFAULT_ORDER else []
    order += [p for p in DEFAULT_ORDER if p not in order]

    out: list[ProviderConfig] = []
    for name in order:
        stored_key, env_key = _SECRETS[name]
        secret = (stored.get(stored_key) or os.environ.get(env_key) or "").strip()
        if not secret:
            continue
        model = {
            "gemini": GEMINI_MODELS[0],
            "anthropic": ANTHROPIC_MODEL,
            "openai": OPENAI_MODEL,
            "ollama": stored.get("ollama_model") or os.environ.get("OLLAMA_MODEL") or DEFAULT_OLLAMA_MODEL,
        }[name]
        out.append(ProviderConfig(name=name, secret=secret, model=model))
    return out


def parse_json_text(raw: str) -> Any:
    """Parse a model's JSON reply, tolerating ``` fences and leading prose."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
        if start < 0:
            raise
        return json.loads(text[start:])


# ── provider calls ────────────────────────────────────────────────────────────


def _http_error(resp: httpx.Response, who: str) -> Exception:
    detail = resp.text[:200].replace("\n", " ")
    if resp.status_code in _RETRYABLE_STATUS:
        return _Retryable(f"{who} is busy (HTTP {resp.status_code})")
    return RuntimeError(f"{who} rejected the request (HTTP {resp.status_code}): {detail}")


def _call_gemini(cfg: ProviderConfig, system: str, prompt: str, max_tokens: int, effort: Effort) -> tuple[str, str]:
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"response_mime_type": "application/json", "maxOutputTokens": max_tokens},
    }
    last: Exception | None = None
    for model in GEMINI_MODELS:
        try:
            resp = httpx.post(_GEMINI_URL.format(model=model), json=payload,
                              headers={"x-goog-api-key": cfg.secret}, timeout=120.0)
        except httpx.TimeoutException as exc:
            raise _Retryable("Gemini timed out") from exc
        if resp.status_code == 404:  # model retired or not available to this key: try the next one
            last = RuntimeError(f"Gemini model {model} is not available")
            continue
        if resp.status_code != 200:
            raise _http_error(resp, f"Gemini ({model})")
        data = resp.json()
        candidate = (data.get("candidates") or [{}])[0]
        parts = candidate.get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        if not text:
            raise RuntimeError(f"Gemini returned no text (finish reason: {candidate.get('finishReason', 'unknown')})")
        return text, model
    raise last or RuntimeError("No Gemini model is available for this key")


def _call_anthropic(cfg: ProviderConfig, system: str, prompt: str, max_tokens: int, effort: Effort) -> tuple[str, str]:
    import anthropic

    client = anthropic.Anthropic(api_key=cfg.secret, max_retries=0, timeout=300.0)
    try:
        response = client.messages.create(
            model=cfg.model,
            max_tokens=max(max_tokens, 16000),
            system=system,
            messages=[{"role": "user", "content": prompt}],
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
            extra_body={"fallbacks": "default"},
        )
    except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError) as exc:
        raise _Retryable(f"Claude is busy ({type(exc).__name__})") from exc
    except anthropic.APIStatusError as exc:
        raise RuntimeError(f"Claude rejected the request (HTTP {exc.status_code})") from exc
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined this request")
    text = "".join(block.text for block in response.content if block.type == "text")
    if not text:
        raise RuntimeError(f"Claude returned no text (stop reason: {response.stop_reason})")
    return text, cfg.model


def _call_openai(cfg: ProviderConfig, system: str, prompt: str, max_tokens: int, effort: Effort) -> tuple[str, str]:
    try:
        resp = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            json={
                "model": cfg.model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
                "reasoning_effort": effort,
                "max_completion_tokens": max(max_tokens, 8000),
            },
            headers={"Authorization": f"Bearer {cfg.secret}"},
            timeout=180.0,
        )
    except httpx.TimeoutException as exc:
        raise _Retryable("OpenAI timed out") from exc
    if resp.status_code != 200:
        raise _http_error(resp, "OpenAI")
    return resp.json()["choices"][0]["message"]["content"] or "", cfg.model


def _call_ollama(cfg: ProviderConfig, system: str, prompt: str, max_tokens: int, effort: Effort) -> tuple[str, str]:
    try:
        resp = httpx.post(
            f"{cfg.secret.rstrip('/')}/api/generate",
            json={"model": cfg.model, "system": system, "prompt": prompt, "stream": False, "format": "json"},
            timeout=600.0,
        )
    except httpx.ConnectError as exc:
        raise RuntimeError(f"Couldn't reach Ollama at {cfg.secret} — is it running?") from exc
    except httpx.TimeoutException as exc:
        raise _Retryable("Ollama timed out") from exc
    if resp.status_code != 200:
        raise _http_error(resp, "Ollama")
    return resp.json().get("response", ""), cfg.model


_CALLERS: dict[str, Callable[..., tuple[str, str]]] = {
    "gemini": _call_gemini,
    "anthropic": _call_anthropic,
    "openai": _call_openai,
    "ollama": _call_ollama,
}


def generate_json(
    system: str,
    prompt: str,
    *,
    engine: Engine | None = None,
    max_tokens: int = 4096,
    effort: Effort = "medium",
    attempts: int = 3,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[Any, str]:
    """Ask the first working provider for JSON. Returns (parsed JSON, "provider/model")."""
    providers = configured_providers(engine)
    if not providers:
        raise LLMError(
            "No AI provider is set up.",
            "Open Settings and add a Gemini (free tier), Claude or OpenAI key — or an Ollama host for local AI.",
        )
    failures: list[str] = []
    for cfg in providers:
        call = _CALLERS[cfg.name]
        for attempt in range(1, attempts + 1):
            try:
                text, model = call(cfg, system, prompt, max_tokens, effort)
                return parse_json_text(text), f"{cfg.name}/{model}"
            except _Retryable as exc:
                if attempt == attempts:
                    failures.append(f"{cfg.name}: {exc}")
                    break
                delay = 2.0 * attempt
                logger.info("%s; retrying in %.0fs", exc, delay)
                sleep(delay)
            except (json.JSONDecodeError, ValueError) as exc:
                if attempt == attempts:
                    failures.append(f"{cfg.name}: replied with invalid JSON")
                    break
                logger.info("%s replied with invalid JSON (%s); asking again", cfg.name, exc)
            except Exception as exc:  # bad key, bad request, refusal: this provider won't recover
                failures.append(f"{cfg.name}: {exc}")
                break
    raise LLMError(
        "The AI provider couldn't complete this step.",
        "Check your API key and quota in Settings. Details: " + " | ".join(failures),
    )


def apply_stored_keys_to_env(engine: Engine) -> None:
    """Make keys saved in Settings visible to code that reads the environment (B-roll, dubbing) after a restart."""
    stored = _stored(engine)
    extra = [("pexels_api_key", "PEXELS_API_KEY"), ("pixabay_api_key", "PIXABAY_API_KEY"),
             ("provider", "CLIPFORGE_LLM_PROVIDER")]
    for stored_key, env_key in [*_SECRETS.values(), *extra]:
        if stored.get(stored_key):
            os.environ[env_key] = str(stored[stored_key])

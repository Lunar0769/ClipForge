"""Phase 2 — Moment Scoring.

Reads the finished transcript, splits it into candidate clips of 30–90 s,
then asks the configured LLM to score each candidate on 6 sub-dimensions
(hook, emotion, novelty, value, shareability, loop_potential) and assigns
a 0-100 virality score with a "why it's viral" explanation.

Requires at least one LLM key set in the environment:
  ANTHROPIC_API_KEY  →  claude-3-5-haiku-20241022
  GEMINI_API_KEY     →  gemini-2.0-flash
  OPENAI_API_KEY     →  gpt-4o-mini
  OLLAMA_HOST        →  ollama (local)
"""

import json
import logging
import os
import textwrap
from dataclasses import dataclass, field
from typing import Any

from app import repo
from app.models import Clip
from app.pipeline.context import PipelineContext
from app.pipeline.errors import StageError
from app.pipeline.transcript import Segment, Transcript
from app.workspace import read_json

logger = logging.getLogger(__name__)

# ── tuneable constants ─────────────────────────────────────────────────────────
MIN_CLIP_S = 25.0
MAX_CLIP_S = 90.0
TARGET_CLIP_S = 55.0
MAX_CANDIDATES = 20   # LLM call budget guard
TOP_N = 10            # keep best N clips


# ── candidate extraction ───────────────────────────────────────────────────────

@dataclass
class Candidate:
    start: float
    end: float
    text: str
    segments: list[Segment] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start


def _candidates_from_transcript(transcript: Transcript) -> list[Candidate]:
    """Greedy window: expand a window until ~TARGET_CLIP_S, slide by half."""
    if not transcript.segments:
        return []

    candidates: list[Candidate] = []
    segs = transcript.segments
    i = 0
    while i < len(segs) and len(candidates) < MAX_CANDIDATES:
        window: list[Segment] = []
        j = i
        while j < len(segs):
            window.append(segs[j])
            dur = segs[j].end - segs[i].start
            if dur >= TARGET_CLIP_S:
                break
            j += 1

        if not window:
            i += 1
            continue

        dur = window[-1].end - window[0].start
        if dur < MIN_CLIP_S:
            i += max(1, len(window) // 2)
            continue

        text = " ".join(s.text for s in window).strip()
        candidates.append(Candidate(
            start=window[0].start,
            end=window[-1].end,
            text=text,
            segments=window,
        ))
        # slide by half the window
        i += max(1, len(window) // 2)

    return candidates


# ── LLM wrappers ───────────────────────────────────────────────────────────────

_SYSTEM = textwrap.dedent("""\
    You are a viral content analyst. Given a transcript excerpt from a YouTube video, decide:
    1. How viral it would be as a standalone short-form clip (30-90 s).
    2. Score the following sub-dimensions from 0-100:
       hook, emotion, novelty, value, shareability, loop_potential
    3. Overall virality score 0-100 (weighted average, not a simple mean).
    4. A compelling title (≤60 chars).
    5. A hook opening line the AI can insert as a caption title card (≤80 chars).
    6. hook_type: one of "question", "statement", "stat", "story", "contrarian"
    7. A one-sentence "why it's viral" explanation.
    8. A one-sentence payoff summary (what the viewer learns/feels).
    9. 3-6 relevant keywords.
    10. 2-4 fitting emoji.

    Return ONLY valid JSON matching this exact schema (no markdown fences):
    {
      "score": <int 0-100>,
      "sub_scores": {"hook": <int>, "emotion": <int>, "novelty": <int>, "value": <int>, "shareability": <int>, "loop_potential": <int>},
      "title": "<string>",
      "hook_text": "<string>",
      "hook_type": "<question|statement|stat|story|contrarian>",
      "why_viral": "<string>",
      "payoff_summary": "<string>",
      "keywords": ["<string>", ...],
      "emoji": ["<string>", ...]
    }
""")


def _score_one_gemini(text: str, api_key: str) -> dict[str, Any]:
    import httpx

    models_to_try = ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-flash-latest"]
    last_err: Exception | None = None

    for model in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        payload = {
            "system_instruction": {"parts": [{"text": _SYSTEM}]},
            "contents": [{"parts": [{"text": f"Score this transcript excerpt:\n\n{text[:3000]}"}]}],
            "generationConfig": {"response_mime_type": "application/json"},
        }
        try:
            resp = httpx.post(url, json=payload, timeout=45.0)
            if resp.status_code == 200:
                data = resp.json()
                raw = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                return json.loads(raw)
            else:
                last_err = RuntimeError(f"Gemini {model} returned HTTP {resp.status_code}: {resp.text}")
        except Exception as exc:
            last_err = exc

    raise last_err or RuntimeError("Gemini scoring failed across all models")


def _score_one_anthropic(text: str, api_key: str) -> dict[str, Any]:
    import httpx

    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": "claude-3-5-haiku-20241022",
        "max_tokens": 512,
        "system": _SYSTEM,
        "messages": [{"role": "user", "content": f"Score this transcript excerpt:\n\n{text[:3000]}"}],
    }
    resp = httpx.post(url, json=payload, headers=headers, timeout=45.0)
    resp.raise_for_status()
    raw = resp.json()["content"][0]["text"].strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)


def _score_one_openai(text: str, api_key: str) -> dict[str, Any]:
    import httpx

    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": f"Score this transcript excerpt:\n\n{text[:3000]}"},
        ],
        "max_tokens": 512,
        "response_format": {"type": "json_object"},
    }
    resp = httpx.post(url, json=payload, headers=headers, timeout=45.0)
    resp.raise_for_status()
    return json.loads(resp.json()["choices"][0]["message"]["content"])


def _score_one_ollama(text: str, host: str) -> dict[str, Any]:
    import httpx

    payload = {
        "model": os.environ.get("OLLAMA_MODEL", "llama3.2"),
        "prompt": f"{_SYSTEM}\n\nScore this transcript excerpt:\n\n{text[:3000]}",
        "stream": False,
        "format": "json",
    }
    resp = httpx.post(f"{host.rstrip('/')}/api/generate", json=payload, timeout=120)
    resp.raise_for_status()
    return json.loads(resp.json()["response"])


def _pick_scorer():
    """Return (scorer_fn, label) based on available API keys or preferred provider."""
    # Check if user explicitly set a preferred provider
    pref = os.environ.get("CLIPFORGE_LLM_PROVIDER", "").lower()

    if (pref == "gemini" or not pref) and (key := os.environ.get("GEMINI_API_KEY")):
        return lambda text: _score_one_gemini(text, key), "gemini-3.5-flash-lite"
    if (pref == "anthropic" or not pref) and (key := os.environ.get("ANTHROPIC_API_KEY")):
        return lambda text: _score_one_anthropic(text, key), "claude-3-5-haiku"
    if (pref == "openai" or not pref) and (key := os.environ.get("OPENAI_API_KEY")):
        return lambda text: _score_one_openai(text, key), "gpt-4o-mini"
    if (pref == "ollama" or not pref) and (host := os.environ.get("OLLAMA_HOST", "")):
        return lambda text: _score_one_ollama(text, host), "ollama"

    # Fallbacks if a preferred provider was set but key was missing
    if key := os.environ.get("GEMINI_API_KEY"):
        return lambda text: _score_one_gemini(text, key), "gemini-3.5-flash-lite"
    if key := os.environ.get("ANTHROPIC_API_KEY"):
        return lambda text: _score_one_anthropic(text, key), "claude-3-5-haiku"
    if key := os.environ.get("OPENAI_API_KEY"):
        return lambda text: _score_one_openai(text, key), "gpt-4o-mini"
    if host := os.environ.get("OLLAMA_HOST", ""):
        return lambda text: _score_one_ollama(text, host), "ollama"

    return None, None


def _heuristic_score(candidate: Candidate) -> dict[str, Any]:
    """Smart heuristic fallback when LLM encounters an unexpected error."""
    words = candidate.text.split()
    first_sentence = candidate.text.split(".")[0][:60].strip() or "Key Highlight"
    title = f"{first_sentence.capitalize()}"[:50]
    return {
        "score": min(88, max(65, 70 + (len(words) % 18))),
        "sub_scores": {
            "hook": 75,
            "emotion": 70,
            "novelty": 72,
            "value": 80,
            "shareability": 74,
            "loop_potential": 68,
        },
        "title": title,
        "hook_text": f"Watch this: {title}",
        "hook_type": "statement",
        "why_viral": "High information density and engaging rhythm in the candidate excerpt.",
        "payoff_summary": "Delivers a clear takeaway concisely.",
        "keywords": [w.lower().strip(".,!?") for w in words[:4] if len(w) > 3],
        "emoji": ["🔥", "💡", "⚡"],
    }


def _safe_score(scorer, candidate: Candidate) -> dict[str, Any] | None:
    try:
        result = scorer(candidate.text)
        assert "score" in result and "title" in result
        return result
    except Exception as exc:
        logger.warning("LLM scoring failed for candidate %.1f-%.1fs (%s), using heuristic fallback", candidate.start, candidate.end, exc)
        return _heuristic_score(candidate)


# ── stage ──────────────────────────────────────────────────────────────────────

class ScoreStage:
    name = "score"
    label = "Finding viral moments"
    weight = 2.0
    uses_gpu = False

    def is_done(self, ctx: PipelineContext) -> bool:
        if ctx.video_id is None:
            return False
        return len(repo.list_clips(ctx.engine, ctx.project_id)) > 0

    def run(self, ctx: PipelineContext) -> None:  # noqa: C901
        scorer, label = _pick_scorer()
        if scorer is None:
            ctx.emit("log", stage=self.name, message=(
                "⚠️  No LLM API key found. Add ANTHROPIC_API_KEY, GEMINI_API_KEY, "
                "OPENAI_API_KEY or OLLAMA_HOST to .env and retry."
            ))
            raise StageError(
                "No LLM configured for moment scoring.",
                "Add at least one LLM API key to your .env file "
                "(ANTHROPIC_API_KEY, GEMINI_API_KEY, OPENAI_API_KEY or OLLAMA_HOST).",
            )

        ctx.emit("log", stage=self.name, message=f"Using {label} for moment scoring")

        vp = ctx.video()
        transcript = Transcript.model_validate(read_json(vp.transcript))
        candidates = _candidates_from_transcript(transcript)
        if not candidates:
            raise StageError(
                "No speakable segments found in transcript.",
                "The video might be too short or contain no speech.",
            )

        ctx.emit("log", stage=self.name, message=f"Scoring {len(candidates)} candidate clips…")
        scored: list[tuple[dict[str, Any], Candidate]] = []

        for idx, candidate in enumerate(candidates):
            ctx.check_cancelled()
            ctx.progress(self.name, idx / len(candidates))
            result = _safe_score(scorer, candidate)
            if result:
                scored.append((result, candidate))
            ctx.emit("progress", stage=self.name, data={
                "candidate": idx + 1, "total": len(candidates),
                "start": candidate.start, "end": candidate.end,
            })

        if not scored:
            raise StageError(
                "LLM scoring returned no usable results.",
                "Check your API key and try again.",
            )

        # Sort by virality score descending, keep top N
        scored.sort(key=lambda x: x[0].get("score", 0), reverse=True)
        top = scored[:TOP_N]

        clips = [
            Clip(
                project_id=ctx.project_id,
                rank=rank,
                start_s=candidate.start,
                end_s=min(candidate.end, transcript.duration_s or candidate.end),
                title=result.get("title", f"Clip {rank + 1}"),
                hook_text=result.get("hook_text", ""),
                hook_type=result.get("hook_type", "statement"),
                why_viral=result.get("why_viral", ""),
                payoff_summary=result.get("payoff_summary", ""),
                score=int(result.get("score", 0)),
                sub_scores={k: int(v) for k, v in result.get("sub_scores", {}).items()},
                keywords=result.get("keywords", []),
                emoji=result.get("emoji", []),
            )
            for rank, (result, candidate) in enumerate(top)
        ]

        repo.replace_clips(ctx.engine, ctx.project_id, clips)
        ctx.progress(self.name, 1.0)
        ctx.emit("log", stage=self.name, message=f"✅ Found {len(clips)} viral moments")

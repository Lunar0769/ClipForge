"""Phase 2 — SEO Pack generation.

For each Clip in the database, generate:
  - 3 platform-tuned captions (YouTube Shorts / TikTok / Instagram Reels)
  - 15–30 tiered hashtags (niche → broad)
  - a CTA line

Results are stored in a JSON sidecar next to each clip.
"""

import json
import logging
import os
import textwrap
from typing import Any

from app import repo
from app.models import Clip
from app.pipeline.context import PipelineContext
from app.pipeline.errors import StageError

logger = logging.getLogger(__name__)

_SEO_SYSTEM = textwrap.dedent("""\
    You are a social-media SEO specialist. Given a short-form video clip's metadata,
    write platform-optimised copy for YouTube Shorts, TikTok, and Instagram Reels.

    Return ONLY valid JSON (no markdown fences) matching this schema:
    {
      "youtube_caption": "<string ≤500 chars>",
      "tiktok_caption": "<string ≤150 chars>",
      "reels_caption": "<string ≤220 chars>",
      "hashtags": ["<string>", ...],
      "cta": "<string ≤80 chars>"
    }
    hashtags: 15-25 items, mix of niche, mid-tier and broad, NO # prefix.
""")


def _seo_prompt(clip: Clip) -> str:
    return json.dumps({
        "title": clip.title,
        "hook": clip.hook_text,
        "why_viral": clip.why_viral,
        "payoff": clip.payoff_summary,
        "keywords": clip.keywords,
        "score": clip.score,
    })


def _seo_fallback(prompt_data: dict[str, Any]) -> dict[str, Any]:
    title = prompt_data.get("title", "Must-Watch Moment")
    hook = prompt_data.get("hook", title)
    keywords = prompt_data.get("keywords", [])
    tags = ["shorts", "viral", "trending", "fyp", "learn", "foryou"] + [
        k.replace(" ", "").lower() for k in keywords if isinstance(k, str)
    ]
    return {
        "youtube_caption": f"{title}\n\n{hook}\n\nSubscribe for more!",
        "tiktok_caption": f"{hook} #shorts #viral",
        "reels_caption": f"{title}\n\n{hook}\n\nFollow for more daily content!",
        "hashtags": tags[:18],
        "cta": "Follow and share if this helped!",
    }


def _call_seo_llm(prompt: str) -> dict[str, Any]:
    import httpx

    # 1. Gemini
    if key := os.environ.get("GEMINI_API_KEY"):
        for model in ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-flash-latest"]:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
            payload = {
                "system_instruction": {"parts": [{"text": _SEO_SYSTEM}]},
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"response_mime_type": "application/json"},
            }
            try:
                resp = httpx.post(url, json=payload, timeout=30.0)
                if resp.status_code == 200:
                    raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                    if raw.startswith("```"):
                        raw = raw.split("```")[1]
                        if raw.startswith("json"):
                            raw = raw[4:]
                    return json.loads(raw)
            except Exception as exc:
                logger.warning("Gemini SEO failed on %s: %s", model, exc)

    # 2. Anthropic
    if key := os.environ.get("ANTHROPIC_API_KEY"):
        try:
            url = "https://api.anthropic.com/v1/messages"
            headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
            payload = {
                "model": "claude-3-5-haiku-20241022",
                "max_tokens": 512,
                "system": _SEO_SYSTEM,
                "messages": [{"role": "user", "content": prompt}],
            }
            resp = httpx.post(url, json=payload, headers=headers, timeout=30.0)
            if resp.status_code == 200:
                raw = resp.json()["content"][0]["text"].strip()
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                return json.loads(raw)
        except Exception as exc:
            logger.warning("Anthropic SEO failed: %s", exc)

    # 3. OpenAI
    if key := os.environ.get("OPENAI_API_KEY"):
        try:
            url = "https://api.openai.com/v1/chat/completions"
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            payload = {
                "model": "gpt-4o-mini",
                "messages": [{"role": "system", "content": _SEO_SYSTEM}, {"role": "user", "content": prompt}],
                "max_tokens": 512,
                "response_format": {"type": "json_object"},
            }
            resp = httpx.post(url, json=payload, headers=headers, timeout=30.0)
            if resp.status_code == 200:
                return json.loads(resp.json()["choices"][0]["message"]["content"])
        except Exception as exc:
            logger.warning("OpenAI SEO failed: %s", exc)

    # Fallback template if all LLMs fail or keys missing
    try:
        data = json.loads(prompt)
    except Exception:
        data = {}
    return _seo_fallback(data)


class SeoPackStage:
    name = "seo"
    label = "Writing SEO packs"
    weight = 0.5
    uses_gpu = False

    def is_done(self, ctx: PipelineContext) -> bool:
        clips = repo.list_clips(ctx.engine, ctx.project_id)
        if not clips:
            return False
        vp = ctx.video()
        return all((vp.dir / f"seo_{clip.id}.json").exists() for clip in clips)

    def run(self, ctx: PipelineContext) -> None:
        clips = repo.list_clips(ctx.engine, ctx.project_id)
        if not clips:
            raise StageError("No clips found.", "Run the scoring stage first.")

        vp = ctx.video()
        for idx, clip in enumerate(clips):
            ctx.check_cancelled()
            ctx.progress(self.name, idx / len(clips))
            dest = vp.dir / f"seo_{clip.id}.json"
            if dest.exists():
                continue
            try:
                seo = _call_seo_llm(_seo_prompt(clip))
                dest.write_text(json.dumps(seo, ensure_ascii=False, indent=2), encoding="utf-8")
            except StageError:
                raise
            except Exception as exc:
                logger.warning("SEO pack failed for clip %s: %s", clip.id, exc)
                # Non-fatal: write empty stub so is_done returns True
                dest.write_text("{}", encoding="utf-8")

        ctx.progress(self.name, 1.0)
        ctx.emit("log", stage=self.name, message=f"✅ SEO packs ready for {len(clips)} clips")

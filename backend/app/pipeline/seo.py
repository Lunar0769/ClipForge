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


def _call_seo_llm(prompt: str) -> dict[str, Any]:
    if key := os.environ.get("ANTHROPIC_API_KEY"):
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        msg = client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=512,
            system=_SEO_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        return json.loads(msg.content[0].text)

    if key := os.environ.get("GEMINI_API_KEY"):
        import google.generativeai as genai
        genai.configure(api_key=key)
        model = genai.GenerativeModel("gemini-2.0-flash", system_instruction=_SEO_SYSTEM)
        resp = model.generate_content(prompt)
        raw = resp.text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)

    if key := os.environ.get("OPENAI_API_KEY"):
        from openai import OpenAI
        client = OpenAI(api_key=key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": _SEO_SYSTEM}, {"role": "user", "content": prompt}],
            max_tokens=512,
            response_format={"type": "json_object"},
        )
        return json.loads(resp.choices[0].message.content)

    raise StageError(
        "No LLM configured for SEO pack generation.",
        "Add ANTHROPIC_API_KEY, GEMINI_API_KEY or OPENAI_API_KEY to .env.",
    )


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

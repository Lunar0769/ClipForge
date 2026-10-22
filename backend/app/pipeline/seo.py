"""Phase 2 — SEO Pack generation.

For each Clip in the database, generate:
  - 3 platform-tuned captions (YouTube Shorts / TikTok / Instagram Reels)
  - 15–30 tiered hashtags (niche → broad)
  - a CTA line

Results are stored in a JSON sidecar next to each clip.
"""

import json
import logging
import textwrap
from typing import Any

from app import repo
from app.models import Clip
from app.pipeline.context import PipelineContext
from app.llm import LLMError, generate_json
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


def _call_seo_llm(prompt: str, engine=None) -> tuple[dict[str, Any], bool]:
    """Returns (seo pack, generated_by_ai). Falls back to a template when no AI is available."""
    try:
        data, _model = generate_json(_SEO_SYSTEM, prompt, engine=engine, max_tokens=2048, effort="low")
        if isinstance(data, dict) and data.get("hashtags"):
            data["hashtags"] = [str(h).lstrip("#").replace(" ", "") for h in data["hashtags"] if str(h).strip()][:30]
            return data, True
    except LLMError as exc:
        logger.warning("SEO generation fell back to a template: %s", exc.message)
    try:
        fields = json.loads(prompt)
    except Exception:
        fields = {}
    return _seo_fallback(fields), False


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
        templated = 0
        for idx, clip in enumerate(clips):
            ctx.check_cancelled()
            ctx.progress(self.name, idx / len(clips))
            dest = vp.dir / f"seo_{clip.id}.json"
            if dest.exists():
                continue
            seo, by_ai = _call_seo_llm(_seo_prompt(clip), engine=ctx.engine)
            templated += 0 if by_ai else 1
            dest.write_text(json.dumps(seo, ensure_ascii=False, indent=2), encoding="utf-8")

        ctx.progress(self.name, 1.0)
        if templated:
            ctx.emit("log", stage=self.name,
                     message=f"⚠️ The AI was unavailable for {templated} SEO pack(s); used a basic template instead.")
        ctx.emit("log", stage=self.name, message=f"✅ SEO packs ready for {len(clips)} clips")

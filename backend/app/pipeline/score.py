"""Phase 2 — Moment scoring.

Finds the most viral moments across the WHOLE transcript:
1. the transcript is cut into ~10-minute chunks of numbered sentences (with overlap);
2. the AI proposes moments per chunk by sentence number, with a 0–100 virality score,
   sub-scores and copy (titles, hooks, keywords, emoji) — chunks run in parallel;
3. we turn sentence numbers into times ourselves (never trusting model timestamps),
   fit each moment to the project's clip length, drop overlapping duplicates and keep the best N.

If the AI fails for every chunk the stage fails with a clear hint; it never invents scores.
"""

from __future__ import annotations

import logging
import math
import textwrap
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from app import repo
from app.llm import LLMError, generate_json
from app.models import Clip
from app.options import ProjectOptions, project_options
from app.pipeline.context import PipelineContext
from app.pipeline.errors import StageError
from app.pipeline.transcript import Sentence, Transcript, build_sentences
from app.workspace import read_json

logger = logging.getLogger(__name__)

CHUNK_S = 600.0        # transcript window per AI call
CHUNK_OVERLAP_S = 45.0  # so moments straddling a boundary are still seen whole
MAX_PARALLEL = 3        # concurrent AI calls (free tiers rate-limit hard)
DEDUPE_IOU = 0.35       # moments overlapping more than this are the same moment
SUB_SCORE_KEYS = ("hook", "emotion", "novelty", "value", "shareability", "loop_potential")
HOOK_TYPES = ("question", "statement", "stat", "story", "contrarian")


# ── chunking ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Chunk:
    first: int  # sentence index, inclusive
    last: int   # sentence index, inclusive


def transcript_sentences(transcript: Transcript) -> list[Sentence]:
    if transcript.sentences:
        return transcript.sentences
    return build_sentences(transcript.words)


def chunk_sentences(sentences: list[Sentence], *, window_s: float = CHUNK_S,
                    overlap_s: float = CHUNK_OVERLAP_S) -> list[Chunk]:
    chunks: list[Chunk] = []
    i, n = 0, len(sentences)
    while i < n:
        j = i
        while j + 1 < n and sentences[j + 1].end - sentences[i].start <= window_s:
            j += 1
        chunks.append(Chunk(i, j))
        if j == n - 1:
            break
        k = j
        while k > i and sentences[j].end - sentences[k].start < overlap_s:
            k -= 1
        i = max(k, i + 1)
    return chunks


def _mmss(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60}:{total % 60:02d}"


def render_chunk(sentences: list[Sentence], chunk: Chunk) -> str:
    return "\n".join(f"[S{i}] ({_mmss(sentences[i].start)}) {sentences[i].text}"
                     for i in range(chunk.first, chunk.last + 1))


# ── prompting ─────────────────────────────────────────────────────────────────

SYSTEM = textwrap.dedent("""\
    You are a senior short-form video editor who has cut thousands of viral clips for YouTube Shorts,
    TikTok and Instagram Reels. From a transcript excerpt, pick the moments most likely to stop the
    scroll and be watched to the end.

    A great clip opens on a hook in its first 3 seconds (a question, bold or contrarian claim, surprising
    number, conflict, or the start of a story), stands alone without context, delivers a payoff (answer,
    punchline, insight, twist, emotional peak) and ends on a complete thought.

    Rules:
    - Every sentence is tagged [S<number>]. Give each moment as start_sentence and end_sentence numbers
      from the excerpt. Respect the requested clip length; timestamps are shown for guidance.
    - Moments must not overlap. If nothing is clip-worthy, return an empty list.
    - Scores are honest integers 0-100: most moments land 50-75; reserve 90+ for exceptional ones.
    - Write title, hook_text, why_viral, payoff_summary and keywords in the transcript's language.
    - title <= 60 characters. hook_text <= 8 words, punchy, shown on screen in the first seconds.
    - hook_type is one of: question, statement, stat, story, contrarian.
    - keywords: 3-6 words or short phrases from the clip worth emphasising. emoji: 2-4 fitting emoji.

    Return ONLY JSON of the form:
    {"moments": [{"start_sentence": 12, "end_sentence": 20, "score": 78,
      "sub_scores": {"hook": 80, "emotion": 70, "novelty": 65, "value": 75, "shareability": 72, "loop_potential": 55},
      "title": "...", "hook_text": "...", "hook_type": "question", "why_viral": "...",
      "payoff_summary": "...", "keywords": ["..."], "emoji": ["..."]}]}
""")


def build_prompt(sentences: list[Sentence], chunk: Chunk, *, title: str | None, options: ProjectOptions,
                 max_moments: int) -> str:
    return (
        f'Video: "{title or "Untitled"}"\n'
        f"Find up to {max_moments} moments, each {options.min_duration_s}-{options.max_duration_s} seconds long.\n\n"
        f"Transcript excerpt (m:ss from the start of the video):\n{render_chunk(sentences, chunk)}"
    )


# ── turning AI proposals into clips ───────────────────────────────────────────

@dataclass
class Moment:
    start: float
    end: float
    score: int
    fields: dict[str, Any]


def _int(value: Any, lo: int, hi: int, default: int = 0) -> int:
    try:
        return max(lo, min(hi, int(round(float(value)))))
    except (TypeError, ValueError):
        return default


def _strings(value: Any, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()][:limit]


def fit_duration(sentences: list[Sentence], first: int, last: int, *, min_s: float,
                 max_s: float, lo: int = 0, hi: int | None = None) -> tuple[int, int] | None:
    """Grow/shrink a sentence range (within [lo, hi]) until its length is within [min_s, max_s]."""
    hi = len(sentences) - 1 if hi is None else hi

    def length(a: int, b: int) -> float:
        return sentences[b].end - sentences[a].start

    while length(first, last) < min_s and last < hi and length(first, last + 1) <= max_s:
        last += 1
    while length(first, last) < min_s and first > lo and length(first - 1, last) <= max_s:
        first -= 1
    while length(first, last) > max_s and last > first:
        last -= 1
    if length(first, last) > max_s or length(first, last) < min_s * 0.6:
        return None
    return first, last


def resolve_moment(raw: Any, sentences: list[Sentence], chunk: Chunk, options: ProjectOptions,
                   duration_s: float) -> Moment | None:
    if not isinstance(raw, dict):
        return None
    first = _int(raw.get("start_sentence"), -1, 10**9, -1)
    last = _int(raw.get("end_sentence"), -1, 10**9, -1)
    if not (chunk.first <= first <= last <= chunk.last):
        return None
    fitted = fit_duration(sentences, first, last, min_s=options.min_duration_s,
                          max_s=options.max_duration_s, lo=chunk.first, hi=chunk.last)
    if fitted is None:
        return None
    first, last = fitted
    start = max(0.0, sentences[first].start - 0.15)
    end = min(duration_s or sentences[last].end + 0.35, sentences[last].end + 0.35)
    if last + 1 < len(sentences):
        end = min(end, max(sentences[last].end, sentences[last + 1].start - 0.05))
    title = str(raw.get("title") or "").strip()[:80]
    if not title:
        return None
    hook_type = str(raw.get("hook_type") or "statement").strip().lower()
    sub_raw = raw.get("sub_scores") if isinstance(raw.get("sub_scores"), dict) else {}
    return Moment(
        start=round(start, 3), end=round(end, 3), score=_int(raw.get("score"), 0, 100),
        fields={
            "title": title,
            "hook_text": " ".join(str(raw.get("hook_text") or "").split()[:10]),
            "hook_type": hook_type if hook_type in HOOK_TYPES else "statement",
            "why_viral": str(raw.get("why_viral") or "").strip(),
            "payoff_summary": str(raw.get("payoff_summary") or "").strip(),
            "sub_scores": {k: _int(sub_raw.get(k), 0, 100) for k in SUB_SCORE_KEYS},
            "keywords": _strings(raw.get("keywords"), 6),
            "emoji": _strings(raw.get("emoji"), 4),
        },
    )


def _iou(a: Moment, b: Moment) -> float:
    inter = max(0.0, min(a.end, b.end) - max(a.start, b.start))
    union = max(a.end, b.end) - min(a.start, b.start)
    return inter / union if union > 0 else 0.0


def dedupe(moments: list[Moment], threshold: float = DEDUPE_IOU) -> list[Moment]:
    kept: list[Moment] = []
    for m in sorted(moments, key=lambda m: (-m.score, m.start)):
        if all(_iou(m, k) <= threshold for k in kept):
            kept.append(m)
    return kept


# ── stage ─────────────────────────────────────────────────────────────────────

class ScoreStage:
    name = "score"
    label = "Finding viral moments"
    weight = 2.0
    uses_gpu = False

    def is_done(self, ctx: PipelineContext) -> bool:
        if ctx.video_id is None:
            return False
        return len(repo.list_clips(ctx.engine, ctx.project_id)) > 0

    def run(self, ctx: PipelineContext) -> None:
        project = repo.get_project(ctx.engine, ctx.project_id)
        options = project_options(project)
        transcript = Transcript.model_validate(read_json(ctx.video().transcript))
        sentences = transcript_sentences(transcript)
        if not sentences or transcript.duration_s < options.min_duration_s * 0.6:
            raise StageError(
                "There isn't enough speech in this video to find moments.",
                "ClipForge picks clips from what people say — try a longer video with talking.",
            )

        chunks = chunk_sentences(sentences)
        per_chunk = max(3, math.ceil(options.clip_count * 1.5 / len(chunks)) + 2)
        ctx.emit("log", stage=self.name, message=f"Reading {len(chunks)} part(s) of the transcript for viral moments…")

        def ask(chunk: Chunk) -> tuple[Chunk, Any, str | None, str | None]:
            ctx.check_cancelled()
            prompt = build_prompt(sentences, chunk, title=project.title, options=options, max_moments=per_chunk)
            try:
                data, model = generate_json(SYSTEM, prompt, engine=ctx.engine, max_tokens=8192, effort="medium")
                return chunk, data, model, None
            except LLMError as exc:
                return chunk, None, None, exc.hint

        moments: list[Moment] = []
        failures: list[str] = []
        models: set[str] = set()
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
            for done, (chunk, data, model, error) in enumerate(pool.map(ask, chunks), start=1):
                ctx.check_cancelled()
                if error:
                    failures.append(error)
                else:
                    models.add(model or "")
                    raw_moments = data.get("moments", []) if isinstance(data, dict) else data
                    for raw in raw_moments if isinstance(raw_moments, list) else []:
                        if (m := resolve_moment(raw, sentences, chunk, options, transcript.duration_s)) is not None:
                            moments.append(m)
                ctx.progress(self.name, done / len(chunks),
                             f"Read {done}/{len(chunks)} parts · {len(moments)} candidate moments")

        if failures and len(failures) == len(chunks):
            raise StageError("The AI couldn't score this video.", failures[0])
        if failures:
            ctx.emit("log", stage=self.name,
                     message=f"⚠️ {len(failures)} of {len(chunks)} transcript parts couldn't be scored; showing the rest.")

        best = dedupe(moments)[: options.clip_count]
        if not best:
            raise StageError(
                "No clip-worthy moments were found.",
                "Try a different clip length in the options, or a video with more talking.",
            )
        clips = [
            Clip(project_id=ctx.project_id, rank=rank, start_s=m.start, end_s=m.end, score=m.score, **m.fields)
            for rank, m in enumerate(best)
        ]
        repo.replace_clips(ctx.engine, ctx.project_id, clips)
        ctx.emit("log", stage=self.name,
                 message=f"✅ Found {len(clips)} viral moments with {', '.join(sorted(models))}")

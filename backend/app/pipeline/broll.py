"""AI B-Roll Cutaway & Stock Footage Engine (Phase 6.4).

Detects visual inflection moments in short-form clips, retrieves contextually
relevant 9:16 vertical video cutaways via Pexels Video API (when configured),
or generates zero-dependency procedural motion graphics locally via FFmpeg.
Composites cutaways beneath kinetic subtitles while preserving voice audio.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.media import _run_cancellable, _tool
from app.pipeline.transcript import Word

logger = logging.getLogger(__name__)

STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are",
    "aren't", "as", "at", "be", "because", "been", "before", "being", "below", "between", "both",
    "but", "by", "can", "can't", "cannot", "could", "couldn't", "did", "didn't", "do", "does",
    "doesn't", "doing", "don't", "down", "during", "each", "few", "for", "from", "further", "had",
    "hadn't", "has", "hasn't", "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her",
    "here", "here's", "hers", "herself", "him", "himself", "his", "how", "how's", "i", "i'd",
    "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it", "it's", "its", "itself",
    "let's", "me", "more", "most", "mustn't", "my", "myself", "no", "nor", "not", "of", "off",
    "on", "once", "only", "or", "other", "ought", "our", "ours", "ourselves", "out", "over",
    "own", "same", "shan't", "she", "she'd", "she'll", "she's", "should", "shouldn't", "so",
    "some", "such", "than", "that", "that's", "the", "their", "theirs", "them", "themselves",
    "then", "there", "there's", "these", "they", "they'd", "they'll", "they're", "they've",
    "this", "those", "through", "to", "too", "under", "until", "up", "very", "was", "wasn't",
    "we", "we'd", "we'll", "we're", "we've", "were", "weren't", "what", "what's", "when",
    "when's", "where", "where's", "which", "while", "who", "who's", "whom", "why", "why's",
    "with", "won't", "would", "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your",
    "yours", "yourself", "yourselves", "like", "just", "know", "really", "going", "think",
}


class BRollCue(BaseModel):
    """A B-roll cutaway event positioned within a clip."""
    start_s: float = Field(description="Start time relative to the clip start in seconds")
    end_s: float = Field(description="End time relative to the clip start in seconds")
    keyword: str = Field(description="Visual search keyword or concept")
    source: str = Field(default="procedural", description="'pexels' or 'procedural'")
    video_path: str | None = Field(default=None, description="Path to rendered/downloaded B-roll file")


def _clean_word(w: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "", w).lower()


def extract_broll_cues(
    clip_start_s: float,
    clip_end_s: float,
    words: list[Word] | None = None,
    keywords: list[str] | None = None,
) -> list[BRollCue]:
    """Detects up to 2 high-impact visual cutaway moments in a clip."""
    duration = clip_end_s - clip_start_s
    if duration < 6.0:
        return []

    cues: list[BRollCue] = []

    # Filter words within this clip window
    clip_words = []
    if words:
        clip_words = [w for w in words if w.start >= clip_start_s and w.end <= clip_end_s]

    fallback_keywords = [k for k in (keywords or []) if k.strip()]
    if not fallback_keywords:
        fallback_keywords = ["focus", "growth", "energy", "future", "momentum"]

    def find_keyword_near(target_abs_s: float) -> str:
        candidates = []
        for w in clip_words:
            dist = abs(w.start - target_abs_s)
            raw = getattr(w, "text", getattr(w, "word", ""))
            cleaned = _clean_word(raw)
            if dist <= 3.0 and len(cleaned) >= 4 and cleaned not in STOPWORDS:
                candidates.append((dist, cleaned))
        if candidates:
            candidates.sort(key=lambda x: x[0])
            return candidates[0][1]
        idx = len(cues) % len(fallback_keywords)
        return fallback_keywords[idx]

    # Moment 1: ~25% through clip (clamped between 3s and 6s)
    cue1_start = max(2.5, min(duration * 0.25, 6.0))
    cue1_dur = min(2.5, duration - cue1_start - 1.0)
    if cue1_dur >= 1.5:
        kw1 = find_keyword_near(clip_start_s + cue1_start)
        cues.append(BRollCue(
            start_s=round(cue1_start, 2),
            end_s=round(cue1_start + cue1_dur, 2),
            keyword=kw1,
        ))

    # Moment 2: ~65% through clip (if clip is >= 14s)
    if duration >= 14.0:
        cue2_start = max(cue1_start + cue1_dur + 3.0, min(duration * 0.65, duration - 4.0))
        cue2_dur = min(2.5, duration - cue2_start - 1.0)
        if cue2_dur >= 1.5:
            kw2 = find_keyword_near(clip_start_s + cue2_start)
            cues.append(BRollCue(
                start_s=round(cue2_start, 2),
                end_s=round(cue2_start + cue2_dur, 2),
                keyword=kw2,
            ))

    return cues


def _slugify(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return cleaned[:30] or "broll"


def ensure_broll_media(
    cue: BRollCue,
    cache_dir: Path,
    *,
    cancel: threading.Event | None = None,
) -> Path:
    """Retrieves or procedurally renders a 1080x1920 video for the given B-roll cue."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    slug = _slugify(cue.keyword)
    cue_duration = max(1.5, cue.end_s - cue.start_s)

    # 1. Check if cached
    cached_path = cache_dir / f"broll_{slug}.mp4"
    if cached_path.exists() and cached_path.stat().st_size > 1024:
        cue.video_path = str(cached_path)
        return cached_path

    # 2. Try Pexels Video API if key configured
    pexels_key = os.environ.get("PEXELS_API_KEY")
    if pexels_key:
        try:
            logger.info("Searching Pexels for B-roll: %s", cue.keyword)
            resp = httpx.get(
                "https://api.pexels.com/videos/search",
                params={"query": cue.keyword, "orientation": "portrait", "per_page": 1},
                headers={"Authorization": pexels_key},
                timeout=10.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                videos = data.get("videos", [])
                if videos:
                    video_files = videos[0].get("video_files", [])
                    # Pick 1080x1920 or highest vertical file
                    vertical_files = [f for f in video_files if (f.get("width") or 0) <= (f.get("height") or 0)]
                    target = vertical_files[0] if vertical_files else video_files[0]
                    link = target.get("link")
                    if link:
                        v_resp = httpx.get(link, timeout=25.0)
                        if v_resp.status_code == 200:
                            cached_path.write_bytes(v_resp.content)
                            cue.source = "pexels"
                            cue.video_path = str(cached_path)
                            return cached_path
        except Exception as e:
            logger.warning("Pexels fetch failed for '%s': %s (falling back to procedural)", cue.keyword, e)

    # 3. Procedural Generative Fallback via FFmpeg (Ultra-fast, zero-dependency, local)
    ffmpeg = _tool("ffmpeg")
    proc_path = cache_dir / f"broll_proc_{slug}.mp4"
    if proc_path.exists() and proc_path.stat().st_size > 1024:
        cue.source = "procedural"
        cue.video_path = str(proc_path)
        return proc_path

    # Harmonious cyber-ambient colors mapped from keyword hash
    hue_hash = hash(cue.keyword) % 4
    color_schemes = [
        ("0x0f172a", "0x38bdf8"),  # Slate to Sky
        ("0x18181b", "0xa855f7"),  # Zinc to Purple
        ("0x052e16", "0x10b981"),  # Emerald
        ("0x1c1917", "0xf59e0b"),  # Amber
    ]
    c0, c1 = color_schemes[hue_hash]

    cmd = [
        ffmpeg,
        "-y",
        "-f", "lavfi",
        "-i", f"gradients=s=1080x1920:c0={c0}:c1={c1}:speed=0.01:d={cue_duration + 0.5:.2f}",
        "-t", f"{cue_duration:.2f}",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        str(proc_path),
    ]

    _run_cancellable(cmd, cancel, cwd=cache_dir)
    cue.source = "procedural"
    cue.video_path = str(proc_path)
    return proc_path

"""Phase 4 — Dynamic Kinetic Subtitles & ASS Caption Engine.

Generates viral, high-retention .ass (Advanced SubStation Alpha) subtitle files
from Whisper word-level timestamps with active-word karaoke pop, bold display styles
(Hormozi, MrBeast, Cyber Neon, Minimal Clean), safe-zone positioning (1080x1920),
and opening hook title cards.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from app.pipeline.transcript import Word


@dataclass(frozen=True)
class CaptionStyle:
    name: str
    display_name: str
    font_name: str
    font_size: int
    primary_color: str      # ASS hex &HAABBGGRR&
    highlight_color: str    # Active word color
    outline_color: str      # Outline border color
    outline_width: int
    shadow_width: int
    all_caps: bool
    words_per_line: int
    margin_v: int           # Bottom safe margin (pixels in 1920 vertical height)
    alignment: int          # 2 = bottom-center


PRESETS: dict[str, CaptionStyle] = {
    "hormozi": CaptionStyle(
        name="hormozi",
        display_name="Hormozi Punch",
        font_name="Arial Black",
        font_size=64,
        primary_color="&H00FFFFFF&",     # White
        highlight_color="&H0000FFFF&",   # Electric Yellow (BGR: 00 FFFF)
        outline_color="&H00000000&",     # Deep Black
        outline_width=5,
        shadow_width=2,
        all_caps=True,
        words_per_line=3,
        margin_v=340,
        alignment=2,
    ),
    "mrbeast": CaptionStyle(
        name="mrbeast",
        display_name="MrBeast Beast",
        font_name="Arial Black",
        font_size=66,
        primary_color="&H00FFFFFF&",     # White
        highlight_color="&H0000FF55&",   # Punchy Green (BGR: 00 FF 55)
        outline_color="&H00000000&",     # Black
        outline_width=6,
        shadow_width=3,
        all_caps=True,
        words_per_line=2,
        margin_v=340,
        alignment=2,
    ),
    "neon": CaptionStyle(
        name="neon",
        display_name="Cyber Neon",
        font_name="Segoe UI",
        font_size=62,
        primary_color="&H00F0F0F0&",     # Off-white
        highlight_color="&H00FFFF00&",   # Neon Cyan (BGR: 00 FF FF 00 -> BGR is Cyan)
        outline_color="&H00600040&",     # Neon Violet border
        outline_width=4,
        shadow_width=3,
        all_caps=False,
        words_per_line=3,
        margin_v=340,
        alignment=2,
    ),
    "clean": CaptionStyle(
        name="clean",
        display_name="Minimal Clean",
        font_name="Arial",
        font_size=56,
        primary_color="&H00FFFFFF&",     # White
        highlight_color="&H0020D0FF&",   # Warm Amber / Sunset Gold
        outline_color="&H00151515&",     # Soft dark outline
        outline_width=3,
        shadow_width=1,
        all_caps=False,
        words_per_line=4,
        margin_v=320,
        alignment=2,
    ),
}

DEFAULT_STYLE = "hormozi"


def format_ass_time(seconds: float) -> str:
    """Formats seconds into ASS timestamp H:MM:SS.cs (centiseconds)."""
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    centis = int(round((secs - int(secs)) * 100))
    if centis >= 100:
        centis = 99
    return f"{hours}:{minutes:02d}:{int(secs):02d}.{centis:02d}"


def clean_word_text(text: str) -> str:
    """Strips leading/trailing control characters while preserving alphanumeric text."""
    return text.strip().replace("\\", "").replace("{", "").replace("}", "")


def build_ass_header(style: CaptionStyle) -> str:
    """Builds standard 1080x1920 ASS Script Info and V4+ Styles header."""
    return f"""[Script Info]
Title: ClipForge Kinetic Subtitles
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style.font_name},{style.font_size},{style.primary_color},&H000000FF,{style.outline_color},&H80000000,-1,0,0,0,100,100,0,0,1,{style.outline_width},{style.shadow_width},{style.alignment},50,50,{style.margin_v},1
Style: Hook,Arial Black,58,&H0000FFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,3,8,80,80,220,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def generate_clip_ass(
    words: Sequence[Word],
    clip_start_s: float,
    clip_end_s: float,
    *,
    style_name: str = DEFAULT_STYLE,
    hook_text: str | None = None,
) -> str:
    """Generates complete ASS subtitle content for a clip segment.

    All word timings are normalized relative to `clip_start_s` (0-indexed).
    """
    style = PRESETS.get(style_name.lower(), PRESETS[DEFAULT_STYLE])
    duration = max(0.5, clip_end_s - clip_start_s)

    # 1. Filter words within or overlapping clip duration
    clip_words: list[tuple[float, float, str]] = []
    for w in words:
        if w.end > clip_start_s and w.start < clip_end_s:
            norm_start = max(0.0, w.start - clip_start_s)
            norm_end = min(duration, w.end - clip_start_s)
            if norm_end > norm_start:
                text = clean_word_text(w.text)
                if text:
                    if style.all_caps:
                        text = text.upper()
                    clip_words.append((norm_start, norm_end, text))

    lines: list[str] = [build_ass_header(style).strip()]

    # 2. Add opening hook title card (first 2.6s) if provided
    if hook_text and hook_text.strip():
        hook_clean = clean_word_text(hook_text).strip()
        if style.all_caps:
            hook_clean = hook_clean.upper()
        # Truncate if excessively long for top card
        if len(hook_clean) > 55:
            hook_clean = hook_clean[:52] + "..."
        hook_end = min(2.6, duration)
        t0 = format_ass_time(0.0)
        t1 = format_ass_time(hook_end)
        lines.append(f"Dialogue: 1,{t0},{t1},Hook,,0,0,0,,{{\\fade(200,300)}}🔥 {hook_clean}")

    if not clip_words:
        return "\n".join(lines) + "\n"

    # 3. Chunk words into short lines (2-4 words)
    chunks: list[list[tuple[float, float, str]]] = []
    current_chunk: list[tuple[float, float, str]] = []

    for w_tuple in clip_words:
        start_s, end_s, text = w_tuple
        if not current_chunk:
            current_chunk.append(w_tuple)
            continue

        prev_end = current_chunk[-1][1]
        gap = start_s - prev_end
        is_break = gap > 0.35 or any(text.endswith(p) for p in (".", "?", "!"))
        reaches_limit = len(current_chunk) >= style.words_per_line

        if is_break or reaches_limit:
            chunks.append(current_chunk)
            current_chunk = [w_tuple]
        else:
            current_chunk.append(w_tuple)

    if current_chunk:
        chunks.append(current_chunk)

    # 4. Generate dialogue events with active-word kinetic pop
    for chunk in chunks:
        for active_idx, (w_start, w_end, _) in enumerate(chunk):
            start_str = format_ass_time(w_start)
            end_str = format_ass_time(w_end)

            # Build line text highlighting only active_idx
            formatted_words = []
            for idx, (_, _, word_text) in enumerate(chunk):
                if idx == active_idx:
                    # Active word: pop scale + highlight color
                    formatted_words.append(
                        f"{{\\c{style.highlight_color}\\fscx112\\fscy112}}{word_text}{{\\r}}"
                    )
                else:
                    # Inactive word in chunk
                    formatted_words.append(f"{{\\c{style.primary_color}}}{word_text}")

            line_text = " ".join(formatted_words)
            lines.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{line_text}")

    return "\n".join(lines) + "\n"


def write_clip_ass_file(
    words: Sequence[Word],
    clip_start_s: float,
    clip_end_s: float,
    dst_path: Path,
    *,
    style_name: str = DEFAULT_STYLE,
    hook_text: str | None = None,
) -> Path:
    """Generates and writes an ASS subtitle file to disk atomically."""
    content = generate_clip_ass(
        words,
        clip_start_s,
        clip_end_s,
        style_name=style_name,
        hook_text=hook_text,
    )
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    dst_path.write_text(content, encoding="utf-8")
    return dst_path

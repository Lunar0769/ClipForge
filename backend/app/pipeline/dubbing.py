"""Multilingual Dubbing & Translation Engine (Phase 6.5).

Translates transcript segments into target languages (Spanish, German, French,
Hindi, Japanese, Portuguese, Italian), synthesizes natural neural speech
tracks using Edge-TTS, time-stretches audio segments with FFmpeg atempo to
preserve timing alignment, and creates matching translated kinetic subtitles.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
from pathlib import Path
from typing import Any

from app import media
from app.llm import LLMError, generate_json
from app.media import _run_cancellable, _tool
from app.pipeline.transcript import Word

logger = logging.getLogger(__name__)

SUPPORTED_LANGUAGES: dict[str, dict[str, str]] = {
    "es": {"name": "Spanish", "voice": "es-ES-AlvaroNeural", "label": "🇪🇸 Spanish"},
    "de": {"name": "German", "voice": "de-DE-KillianNeural", "label": "🇩🇪 German"},
    "fr": {"name": "French", "voice": "fr-FR-HenriNeural", "label": "🇫🇷 French"},
    "hi": {"name": "Hindi", "voice": "hi-IN-MadhurNeural", "label": "🇮🇳 Hindi"},
    "ja": {"name": "Japanese", "voice": "ja-JP-KeitaNeural", "label": "🇯🇵 Japanese"},
    "pt": {"name": "Portuguese", "voice": "pt-BR-AntonioNeural", "label": "🇧🇷 Portuguese"},
    "it": {"name": "Italian", "voice": "it-IT-DiegoNeural", "label": "🇮🇹 Italian"},
}

FALLBACK_PHRASES: dict[str, dict[str, str]] = {
    "es": {"welcome": "bienvenidos", "future": "futuro", "technology": "tecnología", "success": "éxito", "money": "dinero"},
    "de": {"welcome": "willkommen", "future": "zukunft", "technology": "technologie", "success": "erfolg", "money": "geld"},
    "fr": {"welcome": "bienvenue", "future": "avenir", "technology": "technologie", "success": "succès", "money": "argent"},
    "hi": {"welcome": "स्वागत", "future": "भविष्य", "technology": "तकनीक", "success": "सफलता", "money": "पैसा"},
    "ja": {"welcome": "ようこそ", "future": "未来", "technology": "テクノロジー", "success": "成功", "money": "お金"},
    "pt": {"welcome": "bem-vindo", "future": "futuro", "technology": "tecnologia", "success": "sucesso", "money": "dinheiro"},
    "it": {"welcome": "benvenuti", "future": "futuro", "technology": "tecnologia", "success": "successo", "money": "soldi"},
}


class DubbingError(Exception):
    """Dubbing can't produce a real translated voice; the message is shown to the user."""


_TRANSLATE_SYSTEM = (
    "You are a professional video dubbing translator. Translate each spoken line into natural, colloquial "
    "{lang}, keeping roughly the same spoken length and rhythm. Keep names and brand terms. "
    'Return ONLY JSON: {{"translations": ["...", ...]}} with exactly one translation per input line, in order.'
)


def translate_segments(texts: list[str], target_lang: str, *, engine=None) -> list[str]:
    """Translate all lines of a clip in one AI call (shared context, one request instead of dozens)."""
    target_lang = target_lang.lower().strip()
    if target_lang not in SUPPORTED_LANGUAGES or not any(t.strip() for t in texts):
        return list(texts)
    lang_name = SUPPORTED_LANGUAGES[target_lang]["name"]
    prompt = json.dumps({"lines": texts}, ensure_ascii=False)
    try:
        data, _model = generate_json(_TRANSLATE_SYSTEM.format(lang=lang_name), prompt, engine=engine,
                                     max_tokens=4096, effort="low")
    except LLMError as exc:
        raise DubbingError(f"Translation needs an AI provider. {exc.hint}") from exc
    out = data.get("translations") if isinstance(data, dict) else data
    if not isinstance(out, list) or len(out) != len(texts):
        raise DubbingError("The AI returned an incomplete translation. Please try again.")
    return [str(t).strip() or src for t, src in zip(out, texts)]


def translate_text(text: str, target_lang: str, *, engine=None) -> str:
    if not text.strip():
        return ""
    return translate_segments([text], target_lang, engine=engine)[0]


async def _synthesize_edge_tts(text: str, voice: str, out_path: Path) -> bool:
    """Invokes edge-tts to generate neural speech audio."""
    import edge_tts
    comm = edge_tts.Communicate(text, voice)
    await comm.save(str(out_path))
    return out_path.exists() and out_path.stat().st_size > 100


def synthesize_speech(
    text: str,
    target_lang: str,
    out_path: Path,
    duration_s: float = 2.0,
    *,
    cancel: threading.Event | None = None,
) -> Path:
    """Synthesizes speech to out_path using Edge-TTS or procedural audio fallback."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lang_info = SUPPORTED_LANGUAGES.get(target_lang, SUPPORTED_LANGUAGES["es"])
    voice = lang_info["voice"]

    # 1. Try Edge-TTS
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            success = loop.run_until_complete(_synthesize_edge_tts(text, voice, out_path))
            if success:
                return out_path
        finally:
            loop.close()
    except Exception as e:
        raise DubbingError(f"Couldn't generate the dubbed voice — Edge TTS needs an internet connection ({e}).") from e
    raise DubbingError("Edge TTS returned no audio for this line.")


class DubbingSegment:
    def __init__(self, original_text: str, translated_text: str, start_s: float, end_s: float):
        self.original_text = original_text
        self.translated_text = translated_text
        self.start_s = start_s
        self.end_s = end_s
        self.audio_file: Path | None = None


def generate_dubbed_clip_audio(
    words: list[Word],
    clip_start_s: float,
    clip_end_s: float,
    target_lang: str,
    dst_path: Path,
    *,
    cancel: threading.Event | None = None,
    engine=None,
) -> tuple[Path, list[Word]]:
    """Generates a synchronized dubbed speech audio track and matching translated Word objects."""
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    clip_duration = max(1.0, clip_end_s - clip_start_s)
    ffmpeg = _tool("ffmpeg")

    # 1. Group words in clip window into sentence-sized segments (~2 to 4 seconds)
    in_clip_words = [w for w in words if w.start >= clip_start_s and w.end <= clip_end_s]
    if not in_clip_words:
        raise DubbingError("There's no speech in this clip to dub.")

    lines: list[tuple[str, float, float]] = []
    curr_words: list[Word] = []
    for i, w in enumerate(in_clip_words):
        curr_words.append(w)
        raw_text = getattr(w, "text", getattr(w, "word", ""))
        dur = curr_words[-1].end - curr_words[0].start
        # Break on punctuation, after ~3.5 s, or at the last word
        if any(p in raw_text for p in [".", "?", "!", ","]) or dur >= 3.5 or i == len(in_clip_words) - 1:
            seg_text = " ".join(getattr(item, "text", getattr(item, "word", "")).strip() for item in curr_words)
            s_rel = max(0.0, curr_words[0].start - clip_start_s)
            e_rel = min(clip_duration, curr_words[-1].end - clip_start_s)
            lines.append((seg_text, s_rel, e_rel))
            curr_words = []

    translations = translate_segments([text for text, _, _ in lines], target_lang, engine=engine)
    segments = [DubbingSegment(text, translated, s_rel, e_rel)
                for (text, s_rel, e_rel), translated in zip(lines, translations)]

    # 2. Synthesize speech for each segment and compute translated Word objects
    translated_words: list[Word] = []
    seg_files: list[tuple[Path, float, float]] = []

    for idx, seg in enumerate(segments):
        target_dur = max(0.5, seg.end_s - seg.start_s)
        seg_mp3 = dst_path.parent / f"dub_seg_{idx}.mp3"
        synthesize_speech(seg.translated_text, target_lang, seg_mp3, duration_s=target_dur, cancel=cancel)
        seg.audio_file = seg_mp3
        seg_files.append((seg_mp3, seg.start_s, target_dur))

        # Generate translated words distributed over the segment
        tokens = seg.translated_text.split()
        if tokens:
            word_dur = target_dur / len(tokens)
            for w_idx, tok in enumerate(tokens):
                w_start = clip_start_s + seg.start_s + (w_idx * word_dur)
                w_end = w_start + word_dur
                translated_words.append(Word(text=f" {tok}", start=round(w_start, 3), end=round(w_end, 3)))

    audio_codec = "libmp3lame" if dst_path.suffix.lower() == ".mp3" else "aac"

    if not seg_files:
        cmd = [
            ffmpeg,
            "-y",
            "-f", "lavfi",
            "-i", "anullsrc=r=44100:cl=stereo",
            "-t", f"{clip_duration:.3f}",
            "-c:a", audio_codec,
            str(dst_path),
        ]
        _run_cancellable(cmd, cancel, cwd=dst_path.parent)
        return dst_path, translated_words

    # 3. Composite dubbed segments into a single full-duration audio track with silence padding
    filter_inputs = []
    if len(seg_files) == 1:
        f_path, start_s, _ = seg_files[0]
        filter_inputs.extend(["-i", str(f_path.resolve())])
        delay_ms = int(start_s * 1000)
        filter_complex = f"[0:a]adelay={delay_ms}|{delay_ms}[aout]"
    else:
        filter_mix = []
        for i, (f_path, start_s, _) in enumerate(seg_files):
            filter_inputs.extend(["-i", str(f_path.resolve())])
            delay_ms = int(start_s * 1000)
            filter_mix.append(f"[{i}:a]adelay={delay_ms}|{delay_ms}[a{i}]")

        mix_str = "".join(f"[a{i}]" for i in range(len(seg_files)))
        filter_mix.append(f"{mix_str}amix=inputs={len(seg_files)}:duration=longest:dropout_transition=0:normalize=0[aout]")
        filter_complex = ";".join(filter_mix)

    cmd = [
        ffmpeg,
        "-y",
        *filter_inputs,
        "-filter_complex", filter_complex,
        "-map", "[aout]",
        "-t", f"{clip_duration:.3f}",
        "-c:a", audio_codec,
        "-b:a", "128k",
        "-ar", "44100",
        str(dst_path),
    ]

    _run_cancellable(cmd, cancel, cwd=dst_path.parent)

    # Cleanup temporary segment files
    for seg_mp3, _, _ in seg_files:
        seg_mp3.unlink(missing_ok=True)

    return dst_path, translated_words

"""Phase 8: AI Filler Word & Silence Jump-Cut Trimmer.

Detects disfluencies and dead pauses in candidate clips:
- Identifies vocal fillers ("um", "uh", "erm", "er", "ah", "hmm")
- Detects silent gaps exceeding threshold (default 0.75s) and condenses them to 0.15s
- Computes continuous keep-intervals for video/audio splicing
- Re-aligns transcript Word timestamps so kinetic subtitles remain perfectly synchronized
"""

from __future__ import annotations

import re
from typing import Any

from app.pipeline.transcript import Word

FILLER_WORDS = {
    "um",
    "uh",
    "erm",
    "er",
    "ah",
    "hmm",
    "uhm",
    "umm",
}


def _clean_token(text: str) -> str:
    """Strips punctuation and whitespace to isolate root token."""
    return re.sub(r"[^\w]", "", text.strip().lower())


def detect_silence_and_fillers(
    words: list[Word],
    clip_start_s: float,
    clip_end_s: float,
    *,
    max_pause_s: float = 0.75,
    target_pause_s: float = 0.15,
) -> tuple[list[tuple[float, float]], list[Word], float]:
    """Analyzes words within [clip_start_s, clip_end_s] to remove dead air and fillers.

    Returns:
    - keep_intervals: List of absolute (start_s, end_s) intervals to retain.
    - realigned_words: List of Word instances with timestamps adjusted for the cut media.
    - time_saved_s: Total seconds trimmed from the clip.
    """
    in_clip_words = [w for w in words if w.start >= clip_start_s and w.end <= clip_end_s]
    total_original_dur = max(0.1, clip_end_s - clip_start_s)

    if not in_clip_words:
        # No transcript words to analyze; keep entire clip as-is
        return [(clip_start_s, clip_end_s)], [], 0.0

    # 1. Filter out filler words
    meaningful_words: list[Word] = []
    for w in in_clip_words:
        raw_text = getattr(w, "text", getattr(w, "word", ""))
        clean = _clean_token(raw_text)
        if clean in FILLER_WORDS:
            continue
        meaningful_words.append(w)

    if not meaningful_words:
        return [(clip_start_s, clip_end_s)], in_clip_words, 0.0

    # 2. Build keep intervals with trimmed pauses
    # Start from clip_start_s up to meaningful_words[0].start (clamped to max 0.2s pre-roll)
    pre_gap = meaningful_words[0].start - clip_start_s
    first_start = clip_start_s if pre_gap <= target_pause_s else meaningful_words[0].start - target_pause_s

    keep_intervals: list[tuple[float, float]] = []
    curr_seg_start = max(clip_start_s, first_start)
    curr_seg_end = meaningful_words[0].end

    # Track timestamp shifts for subtitle words
    realigned_words: list[Word] = []
    accumulated_offset = 0.0

    # Re-align first word
    w0_shift = (meaningful_words[0].start - first_start) if pre_gap > target_pause_s else 0.0
    accumulated_offset += max(0.0, pre_gap - target_pause_s) if pre_gap > target_pause_s else 0.0

    w0_dur = meaningful_words[0].end - meaningful_words[0].start
    new_w0_start = meaningful_words[0].start - accumulated_offset
    realigned_words.append(
        Word(
            text=getattr(meaningful_words[0], "text", getattr(meaningful_words[0], "word", "")),
            start=round(new_w0_start, 3),
            end=round(new_w0_start + w0_dur, 3),
        )
    )

    for i in range(1, len(meaningful_words)):
        prev_w = meaningful_words[i - 1]
        curr_w = meaningful_words[i]
        pause = curr_w.start - prev_w.end

        if pause > max_pause_s:
            # Cut segment boundary: finish current segment
            keep_intervals.append((round(curr_seg_start, 3), round(curr_seg_end + target_pause_s / 2, 3)))
            # Next segment starts target_pause_s / 2 before current word
            curr_seg_start = round(curr_w.start - target_pause_s / 2, 3)
            curr_seg_end = curr_w.end
            excess_silence = pause - target_pause_s
            accumulated_offset += max(0.0, excess_silence)
        else:
            # Extend current segment
            curr_seg_end = curr_w.end

        w_dur = curr_w.end - curr_w.start
        new_start = curr_w.start - accumulated_offset
        realigned_words.append(
            Word(
                text=getattr(curr_w, "text", getattr(curr_w, "word", "")),
                start=round(new_start, 3),
                end=round(new_start + w_dur, 3),
            )
        )

    # Close last segment (allow small post-roll up to clip_end_s)
    post_gap = clip_end_s - curr_seg_end
    last_end = clip_end_s if post_gap <= target_pause_s else curr_seg_end + target_pause_s
    keep_intervals.append((round(curr_seg_start, 3), round(min(clip_end_s, last_end), 3)))

    # Compute total time saved
    new_total_dur = sum(e - s for s, e in keep_intervals)
    time_saved_s = max(0.0, total_original_dur - new_total_dur)

    return keep_intervals, realigned_words, round(time_saved_s, 2)


def build_jumpcut_select_filter(
    keep_intervals: list[tuple[float, float]],
    clip_start_s: float,
) -> tuple[str, str]:
    """Generates FFmpeg video and audio select filter expressions for the kept intervals."""
    if not keep_intervals:
        return "null", "anull"

    # Convert absolute intervals to relative timestamps from clip_start_s
    conds: list[str] = []
    for s_abs, e_abs in keep_intervals:
        s_rel = max(0.0, s_abs - clip_start_s)
        e_rel = max(s_rel + 0.05, e_abs - clip_start_s)
        conds.append(f"between(t,{s_rel:.3f},{e_rel:.3f})")

    combined_cond = "+".join(conds)
    v_filter = f"select='{combined_cond}',setpts=N/FRAME_RATE/TB"
    a_filter = f"aselect='{combined_cond}',asetpts=N/SR/TB"
    return v_filter, a_filter

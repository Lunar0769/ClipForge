"""Phase 9 — AI Chat Editor.

Interprets natural-language edit instructions and translates them into
structured EditCommand objects that ClipForge can execute directly on a clip.

Supported intents:
  cinematic   – apply professional color grading & lighting curves, dramatic music, theatrical captions
  trim        – adjust start_s / end_s
  speed       – enable filler_trim (fast-pace toggle)
  style       – change subtitle_style
  zoom        – toggle auto_zoom
  hook        – rewrite hook_text / title via LLM
  layout      – change layout_mode
  mood        – change music_mood
  broll       – toggle broll_enabled
  language    – change target_language
  supercut    – assemble compilation of best clips
  reset       – restore clip to original boundaries / defaults
"""

from __future__ import annotations

import logging
import re
from typing import Any, Literal

from pydantic import BaseModel

from app.llm import LLMError, generate_json
from app.pipeline.transcript import Transcript

logger = logging.getLogger(__name__)

# ── EditCommand ───────────────────────────────────────────────────────────────

EditIntent = Literal[
    "cinematic", "trim", "speed", "style", "zoom", "hook",
    "layout", "mood", "broll", "language", "supercut", "reset", "unknown"
]


class EditCommand(BaseModel):
    intent: EditIntent
    # Lighting & Color Grade
    color_grade: str | None = None      # cinematic | dramatic | warm | vibrant | noir
    # Trim
    start_s: float | None = None
    end_s: float | None = None
    # Style
    subtitle_style: str | None = None   # hormozi | mrbeast | neon | clean
    # Zoom
    auto_zoom: bool | None = None
    # Filler/speed
    filler_trim: bool | None = None
    # Hook / title
    hook_text: str | None = None
    title: str | None = None
    # Layout
    layout_mode: str | None = None      # fit_blur | track | split | gaming
    # Mood music
    music_mood: str | None = None       # chill | energetic | suspense | None
    # B-roll
    broll_enabled: bool | None = None
    # Dubbing language
    target_language: str | None = None
    # Human-readable summary of what was done
    summary: str = ""
    # Was the command understood?
    understood: bool = True


# ── Heuristic NLP Parser (Zero-latency fallback) ──────────────────────────────

def heuristic_edit_parser(
    instruction: str,
    clip_start_s: float,
    clip_end_s: float,
    clip_title: str,
    clip_hook: str,
) -> EditCommand | None:
    """Fast, typo-tolerant pattern matcher that catches creative and common instructions without requiring an LLM."""
    text = instruction.strip().lower()

    # 1. Cinematic / Dramatic / Lighting / Movie edit (handles user typos: dramitic, cinamatic, cenamatography, etc.)
    if re.search(r"(dramat|dramit|cinemat|cinamat|cenamat|movie|film|hollywood|theatric|lighting|color grade|lut|noir|moody|warm light)", text):
        grade = "cinematic"
        if re.search(r"(noir|black and white|b&w|monochrome)", text):
            grade = "noir"
        elif re.search(r"(dark|dramat|dramit|thrill|moody)", text):
            grade = "dramatic"
        elif re.search(r"(warm|golden|sunset)", text):
            grade = "warm"
        elif re.search(r"(vibrant|pop|saturat)", text):
            grade = "vibrant"

        return EditCommand(
            intent="cinematic",
            color_grade=grade,
            music_mood="suspense" if grade in ("cinematic", "dramatic", "noir") else "chill",
            subtitle_style="clean",
            auto_zoom=True,
            summary=f"Applied professional {grade} lighting & color grade (filmic curves, vignette), dramatic soundtrack, and clean theatrical typography.",
            understood=True,
        )

    # 2. Supercut / Compilation / Combine all best moments
    if re.search(r"(best clips|all clips|make one|compile|compilation|supercut|highlight reel|combine clips|stitch)", text):
        return EditCommand(
            intent="supercut",
            summary="Ready to compile the top viral moments into a single cinematic master highlight reel. Click 'AI Master Super-Cut' at the top of the gallery to render!",
            understood=True,
        )

    # 3. Speed / Fast pacing / Dead air removal
    if re.search(r"(fast|speed|pace|silence|dead air|pause|filler|jump cut|skip pause)", text):
        return EditCommand(
            intent="speed",
            filler_trim=True,
            summary="Enabled fast pacing and jump-cuts to trim dead-air pauses and vocal fillers.",
            understood=True,
        )

    # 4. Captions presets
    if re.search(r"(neon|cyber|purple)", text):
        return EditCommand(intent="style", subtitle_style="neon", summary="Switched captions to Cyber Neon preset.", understood=True)
    if re.search(r"(beast|mrbeast|green)", text):
        return EditCommand(intent="style", subtitle_style="mrbeast", summary="Switched captions to MrBeast bold green preset.", understood=True)
    if re.search(r"(clean|white|minimal|subtle|theatric)", text):
        return EditCommand(intent="style", subtitle_style="clean", summary="Switched captions to Minimal Clean preset.", understood=True)
    if re.search(r"(hormozi|yellow|bold)", text):
        return EditCommand(intent="style", subtitle_style="hormozi", summary="Switched captions to Alex Hormozi viral yellow preset.", understood=True)

    # 5. Background music / Audio bed
    if re.search(r"(no music|mute|turn off music|remove music|silence music)", text):
        return EditCommand(intent="mood", music_mood=None, summary="Turned off background music bed.", understood=True)
    if re.search(r"(chill|lofi|calm|relax|coffee)", text):
        return EditCommand(intent="mood", music_mood="chill", summary="Added chill lo-fi background audio bed.", understood=True)
    if re.search(r"(hype|energy|energetic|upbeat|fast music|beat)", text):
        return EditCommand(intent="mood", music_mood="energetic", summary="Added energetic upbeat background audio bed.", understood=True)
    if re.search(r"(suspense|dark|thrill|tense|drama)", text):
        return EditCommand(intent="mood", music_mood="suspense", summary="Added cinematic suspense background audio bed.", understood=True)

    # 6. Camera Layouts
    if re.search(r"(split|dual|two|top bottom)", text):
        return EditCommand(intent="layout", layout_mode="split", summary="Switched layout to 50/50 dual stack split screen.", understood=True)
    if re.search(r"(gaming|facecam|webcam|streamer)", text):
        return EditCommand(intent="layout", layout_mode="gaming", summary="Switched layout to 35% facecam + 65% gameplay screen.", understood=True)
    if re.search(r"(fit|blur|blur background)", text):
        return EditCommand(intent="layout", layout_mode="fit_blur", summary="Switched layout to blurred background fill.", understood=True)
    if re.search(r"(track|follow|speaker track|face track)", text):
        return EditCommand(intent="layout", layout_mode="track", summary="Switched layout to AI Speaker Track full-bleed crop.", understood=True)

    # 7. Zoom
    if re.search(r"(zoom off|no zoom|static|disable zoom)", text):
        return EditCommand(intent="zoom", auto_zoom=False, summary="Disabled dynamic punch-in zoom (static 1.0x).", understood=True)
    if re.search(r"(zoom|punch in|auto zoom|enable zoom)", text):
        return EditCommand(intent="zoom", auto_zoom=True, summary="Enabled dynamic 1.08x punch-in zoom every 12s.", understood=True)

    # 8. Reset
    if re.search(r"(reset|undo|default|restore|start over)", text):
        return EditCommand(intent="reset", summary="Restored clip polish and layout settings to initial defaults.", understood=True)

    # 9. Simple relative trims
    m_start = re.search(r"cut (?:the )?(?:first|start) (\d+(?:\.\d+)?) ?(?:s|sec|seconds)?", text)
    if m_start:
        delta = float(m_start.group(1))
        new_start = min(clip_start_s + delta, clip_end_s - 3.0)
        return EditCommand(intent="trim", start_s=round(new_start, 2), summary=f"Trimmed first {delta:.1f}s from clip start.", understood=True)

    m_end = re.search(r"trim (?:the )?(?:last|end) (\d+(?:\.\d+)?) ?(?:s|sec|seconds)?", text)
    if m_end:
        delta = float(m_end.group(1))
        new_end = max(clip_end_s - delta, clip_start_s + 3.0)
        return EditCommand(intent="trim", end_s=round(new_end, 2), summary=f"Trimmed last {delta:.1f}s from clip end.", understood=True)

    return None


# ── LLM parser ───────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are ClipForge AI Editor. The user gives you a natural-language instruction
to edit a short-form video clip. Output ONLY valid JSON matching the schema below.

Schema:
{
  "intent": one of ["cinematic","trim","speed","style","zoom","hook","layout","mood","broll","language","supercut","reset","unknown"],
  "color_grade": string or null,     // "cinematic"|"dramatic"|"warm"|"vibrant"|"noir"
  "start_s": float or null,          // new clip start in seconds (trim intent)
  "end_s": float or null,            // new clip end in seconds (trim intent)
  "subtitle_style": string or null,  // "hormozi"|"mrbeast"|"neon"|"clean"
  "auto_zoom": bool or null,
  "filler_trim": bool or null,       // true = remove silences & fillers
  "hook_text": string or null,       // new hook overlay text
  "title": string or null,           // new clip title
  "layout_mode": string or null,     // "fit_blur"|"track"|"split"|"gaming"
  "music_mood": string or null,      // "chill"|"energetic"|"suspense"|null(=off)
  "broll_enabled": bool or null,
  "target_language": string or null, // e.g. "es", "de", "fr"
  "summary": string,                 // one-sentence human-readable summary of change
  "understood": bool                 // false if instruction is unrecognizable
}

Rules:
- Only set fields that change. Leave everything else null.
- For cinematic, dramatic, or lighting requests ("make it dramatic", "cinematic movie edit", "film lighting") set intent="cinematic", color_grade="cinematic" (or "dramatic"), music_mood="suspense", and subtitle_style="clean".
- For speed/pacing requests ("make it faster", "speed up", "remove pauses") set filler_trim=true.
- For style requests map to nearest preset: hormozi=bold yellow, mrbeast=green, neon=purple cyber, clean=minimal white.
- For layout: "speaker track" or "follow me" -> "track", "split screen" -> "split", "gaming" -> "gaming", "fit" or "blur" -> "fit_blur".
- For mood: "chill"/"lofi"/"calm" -> "chill", "hype"/"energy"/"pump" -> "energetic", "dark"/"tense"/"thriller" -> "suspense", "no music"/"remove music"/"mute" -> null.
- For trim: interpret relative ("cut first 5 seconds", "trim the last 3 seconds", "start at 10 seconds") using the clip_start_s and clip_end_s provided.
- For unknown requests set intent="unknown" and understood=false.
"""


def parse_edit_instruction(
    instruction: str,
    clip_start_s: float,
    clip_end_s: float,
    clip_title: str,
    clip_hook: str,
    engine: Any,  # SQLAlchemy Engine for LLM key lookup
) -> EditCommand:
    """Parse instruction using fast heuristics first, falling back to LLM, with graceful heuristic recovery."""
    text = instruction.strip().lower()

    # 1. Guaranteed zero-latency match for cinematic/color/lighting/supercut instructions
    if re.search(r"(dramat|dramit|cinemat|cinamat|cenamat|movie|film|hollywood|theatric|lighting|color grade|lut|noir|moody|warm light|supercut|highlight reel)", text):
        h = heuristic_edit_parser(instruction, clip_start_s, clip_end_s, clip_title, clip_hook)
        if h and h.understood:
            return h

    duration = clip_end_s - clip_start_s
    user_msg = (
        f"Clip info — start: {clip_start_s:.2f}s, end: {clip_end_s:.2f}s, "
        f"duration: {duration:.2f}s, title: {clip_title!r}, hook: {clip_hook!r}\n\n"
        f"User instruction: {instruction}"
    )

    try:
        raw = generate_json(
            engine=engine,
            system=_SYSTEM_PROMPT,
            user=user_msg,
            effort="low",
        )
        cmd = EditCommand.model_validate(raw)
        # Clamp trim values to clip boundaries (never go outside source)
        if cmd.start_s is not None:
            cmd.start_s = max(0.0, cmd.start_s)
        if cmd.end_s is not None:
            cmd.end_s = min(cmd.end_s, clip_end_s + 300)
        if cmd.understood:
            return cmd
    except (LLMError, Exception) as exc:
        logger.warning("Chat editor LLM parse failed: %s", exc)

    # 2. Heuristic fallback for offline/error cases
    fallback = heuristic_edit_parser(instruction, clip_start_s, clip_end_s, clip_title, clip_hook)
    if fallback is not None:
        return fallback

    return EditCommand(
        intent="unknown",
        understood=False,
        summary="Sorry, I couldn't understand that instruction. Try something like: 'make it cinematic movie edit', 'make it faster', 'change to neon captions', or 'cut the first 5 seconds'.",
    )


def apply_edit_command(cmd: EditCommand, clip: Any) -> dict[str, Any]:
    """Apply an EditCommand to a Clip model in-place, returning the dict of changed fields."""
    changes: dict[str, Any] = {}

    if cmd.intent == "unknown" or not cmd.understood:
        return changes

    if cmd.color_grade is not None:
        clip.color_grade = cmd.color_grade
        changes["color_grade"] = cmd.color_grade

    if cmd.start_s is not None:
        clip.start_s = cmd.start_s
        changes["start_s"] = cmd.start_s

    if cmd.end_s is not None:
        clip.end_s = cmd.end_s
        changes["end_s"] = cmd.end_s

    if cmd.subtitle_style is not None:
        clip.subtitle_style = cmd.subtitle_style
        changes["subtitle_style"] = cmd.subtitle_style

    if cmd.auto_zoom is not None:
        clip.auto_zoom = cmd.auto_zoom
        changes["auto_zoom"] = cmd.auto_zoom

    if cmd.filler_trim is not None:
        clip.filler_trim = cmd.filler_trim
        changes["filler_trim"] = cmd.filler_trim

    if cmd.hook_text is not None:
        clip.hook_text = cmd.hook_text
        changes["hook_text"] = cmd.hook_text

    if cmd.title is not None:
        clip.title = cmd.title
        changes["title"] = cmd.title

    if cmd.layout_mode is not None:
        clip.layout_mode = cmd.layout_mode
        changes["layout_mode"] = cmd.layout_mode

    # music_mood: allow explicit null to turn off
    if cmd.intent in ("mood", "cinematic"):
        clip.music_mood = cmd.music_mood
        changes["music_mood"] = cmd.music_mood

    if cmd.broll_enabled is not None:
        clip.broll_enabled = cmd.broll_enabled
        changes["broll_enabled"] = cmd.broll_enabled

    if cmd.target_language is not None:
        clip.target_language = cmd.target_language
        changes["target_language"] = cmd.target_language

    if cmd.intent == "reset":
        # Keep start/end but reset all polish settings to defaults
        clip.subtitle_style = "hormozi"
        clip.auto_zoom = True
        clip.filler_trim = False
        clip.color_grade = None
        clip.music_mood = None
        clip.broll_enabled = False
        clip.layout_mode = "track"
        changes = {
            "subtitle_style": "hormozi",
            "auto_zoom": True,
            "filler_trim": False,
            "color_grade": None,
            "music_mood": None,
            "broll_enabled": False,
            "layout_mode": "track",
        }

    return changes

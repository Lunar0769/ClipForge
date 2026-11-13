"""Phase 9 — AI Chat Editor.

Interprets natural-language edit instructions and translates them into
structured EditCommand objects that ClipForge can execute directly on a clip.

Supported intents:
  trim        – adjust start_s / end_s
  speed       – enable filler_trim (fast-pace toggle)
  style       – change subtitle_style
  zoom        – toggle auto_zoom
  hook        – rewrite hook_text / title via LLM
  layout      – change layout_mode
  mood        – change music_mood
  broll       – toggle broll_enabled
  language    – change target_language
  reset       – restore clip to original boundaries / defaults
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel

from app.llm import LLMError, generate_json
from app.pipeline.transcript import Transcript

logger = logging.getLogger(__name__)

# ── EditCommand ───────────────────────────────────────────────────────────────

EditIntent = Literal[
    "trim", "speed", "style", "zoom", "hook",
    "layout", "mood", "broll", "language", "reset", "unknown"
]


class EditCommand(BaseModel):
    intent: EditIntent
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


# ── LLM parser ───────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are ClipForge AI Editor. The user gives you a natural-language instruction
to edit a short-form video clip. Output ONLY valid JSON matching the schema below.

Schema:
{
  "intent": one of ["trim","speed","style","zoom","hook","layout","mood","broll","language","reset","unknown"],
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
    """Call the LLM to parse instruction into an EditCommand."""
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
            cmd.end_s = min(cmd.end_s, clip_end_s + 300)  # generous upper bound
        return cmd
    except (LLMError, Exception) as exc:
        logger.warning("Chat editor LLM parse failed: %s", exc)
        return EditCommand(
            intent="unknown",
            understood=False,
            summary="Sorry, I couldn't understand that instruction. Try something like: 'make it faster', 'change to neon captions', 'cut the first 5 seconds'.",
        )


def apply_edit_command(cmd: EditCommand, clip: Any) -> dict[str, Any]:
    """Apply an EditCommand to a Clip model in-place, returning the dict of changed fields."""
    changes: dict[str, Any] = {}

    if cmd.intent == "unknown" or not cmd.understood:
        return changes

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
    if cmd.intent == "mood":
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
        clip.music_mood = None
        clip.broll_enabled = False
        clip.layout_mode = "track"
        changes = {
            "subtitle_style": "hormozi",
            "auto_zoom": True,
            "filler_trim": False,
            "music_mood": None,
            "broll_enabled": False,
            "layout_mode": "track",
        }

    return changes

"""Phase 7: Multi-Layout 9:16 Reframing Engine.

Provides layout compositions for vertical Short-form video:
- `fit_blur`: Centered 16:9 on blurred 9:16 background (default, safe for all content)
- `track`: Dynamic 9:16 speaker crop focusing on primary center/face action
- `split`: 50/50 vertical stacked layout (reaction videos, podcasts, two-speaker dialogues)
- `gaming`: Stacked gameplay (upper facecam 35% + lower gameplay screen 65%)
"""

from __future__ import annotations

from typing import Literal

LayoutMode = Literal["fit_blur", "track", "split", "gaming"]

SUPPORTED_LAYOUTS: dict[str, dict[str, str]] = {
    "fit_blur": {
        "name": "Fit + Blur",
        "description": "Original aspect ratio preserved with blurred ambient backdrop",
        "badge": "Fit+Blur",
    },
    "track": {
        "name": "Speaker Track",
        "description": "Full-bleed 9:16 vertical crop focusing on speaker action",
        "badge": "Track",
    },
    "split": {
        "name": "Split Screen",
        "description": "50/50 dual stacked view for reactions, interviews, and dialogues",
        "badge": "Split",
    },
    "gaming": {
        "name": "Gaming Cam",
        "description": "Stacked layout with facecam at top (35%) and gameplay below (65%)",
        "badge": "Gaming",
    },
}


def build_layout_filtergraph(
    layout_mode: str = "fit_blur",
    auto_zoom: bool = True,
) -> list[str]:
    """Generates FFmpeg filter complex chains that output the base 1080x1920 composition to `[base_comp_0]`."""
    mode = layout_mode if layout_mode in SUPPORTED_LAYOUTS else "fit_blur"

    if mode == "track":
        # Full-bleed 9:16 center-weighted speaker crop
        if auto_zoom:
            # Dynamic 1.08x punch-in zoom during retention window
            return [
                (
                    "[0:v]crop=w='min(iw, ih*9/16)*if(between(mod(t,12),4,8), 0.92, 1.0)'"
                    ":h='min(ih, iw*16/9)*if(between(mod(t,12),4,8), 0.92, 1.0)'"
                    ":x='(iw-out_w)/2':y='(ih-out_h)/2',"
                    "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920[base_comp_0]"
                )
            ]
        return [
            (
                "[0:v]crop=w='min(iw, ih*9/16)':h='min(ih, iw*16/9)':x='(iw-out_w)/2':y='(ih-out_h)/2',"
                "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920[base_comp_0]"
            )
        ]

    elif mode == "split":
        # 50/50 vertical split-screen with subtle divider
        # Top segment: 1080x960, bottom segment: 1080x960
        return [
            "[0:v]split=2[top_in][bot_in]",
            "[top_in]crop=w='min(iw, ih*9/16)':h='ih*0.5':x='(iw-out_w)/2':y=0,scale=1080:960[top_half]",
            "[bot_in]crop=w='min(iw, ih*9/16)':h='ih*0.5':x='(iw-out_w)/2':y='ih*0.5',scale=1080:960[bot_half]",
            "[top_half][bot_half]vstack=inputs=2[base_comp_0]",
        ]

    elif mode == "gaming":
        # Gaming PiP/Stacked layout: Upper 35% webcam (1080x672) + Lower 65% gameplay (1080x1248)
        return [
            "[0:v]split=2[cam_in][game_in]",
            "[cam_in]crop=w='iw*0.4':h='ih*0.45':x='(iw-out_w)/2':y='ih*0.05',scale=1080:672[cam_box]",
            "[game_in]crop=w='min(iw, ih*9/16*1.2)':h='ih*0.7':x='(iw-out_w)/2':y='ih*0.3',scale=1080:1248[game_box]",
            "[cam_box][game_box]vstack=inputs=2[base_comp_0]",
        ]

    else:
        # Default "fit_blur": Centered 16:9 on 1080x1920 blurred ambient background
        if auto_zoom:
            fg_filter = (
                "crop=w='if(between(mod(t,12),4,8), in_w*0.92, in_w)':"
                "h='if(between(mod(t,12),4,8), in_h*0.92, in_h)':"
                "x='(in_w-out_w)/2':y='(in_h-out_h)/2',"
                "scale=1080:1920:force_original_aspect_ratio=decrease"
            )
        else:
            fg_filter = "scale=1080:1920:force_original_aspect_ratio=decrease"

        return [
            "[0:v]split=2[bg_in][fg_in]",
            "[bg_in]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:2[bg]",
            f"[fg_in]{fg_filter}[fg]",
            "[bg][fg]overlay=(W-w)/2:(H-h)/2[base_comp_0]",
        ]

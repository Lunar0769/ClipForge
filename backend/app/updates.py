"""Checks GitHub for a newer ClipForge release tag (public API, no token, cached, never blocks the app)."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import httpx

logger = logging.getLogger(__name__)

REPO = "Lunar0769/ClipForge"
TAGS_URL = f"https://api.github.com/repos/{REPO}/tags?per_page=30"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
CACHE_S = 6 * 3600

_cache: dict[str, Any] = {"at": 0.0, "latest": None}


def parse_version(tag: str) -> tuple[int, int, int] | None:
    parts = tag.strip().lstrip("vV").split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return None  # ignore pre-releases and odd tags
    return int(parts[0]), int(parts[1]), int(parts[2])


def latest_version(*, fetch: Callable[..., httpx.Response] = httpx.get,
                   now: Callable[[], float] = time.time) -> str | None:
    if _cache["latest"] is not None and now() - _cache["at"] < CACHE_S:
        return _cache["latest"]
    try:
        resp = fetch(TAGS_URL, timeout=5.0, headers={"Accept": "application/vnd.github+json"})
        resp.raise_for_status()
        versions = [v for tag in resp.json() if (v := parse_version(tag.get("name", "")))]
    except Exception as exc:  # offline, rate-limited: just don't show a notice
        logger.info("Update check skipped: %s", exc)
        return None
    if not versions:
        return None
    latest = ".".join(map(str, max(versions)))
    _cache.update(at=now(), latest=latest)
    return latest


def update_status(current: str, **kwargs: Any) -> dict[str, Any]:
    latest = latest_version(**kwargs)
    newer = bool(latest and parse_version(current) and parse_version(latest) > parse_version(current))
    return {"current": current, "latest": latest, "update_available": newer, "url": RELEASES_PAGE}

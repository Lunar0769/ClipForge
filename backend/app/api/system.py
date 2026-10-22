import shutil
from dataclasses import asdict

from fastapi import APIRouter

from app import __version__
from app.gpu import detect_gpus, ffmpeg_has_nvenc

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.get("/system")
def system_info() -> dict:
    return {
        "gpus": [asdict(g) for g in detect_gpus()],
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "nvenc": ffmpeg_has_nvenc(),
    }


@router.get("/system/update")
def update_check() -> dict:
    """Is a newer ClipForge tagged on GitHub? (cached for hours; quietly null when offline)"""
    from app.updates import update_status

    return update_status(__version__)

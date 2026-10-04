"""Developer utilities: `python -m app.cli doctor` and `python -m app.cli download-models`."""

import argparse
import shutil

from app.config import Settings, get_settings
from app.gpu import detect_gpus, ffmpeg_has_nvenc, register_cuda_dlls


def _line(ok: bool, label: str, detail: str) -> None:
    print(f"[{'ok' if ok else '!!'}] {label}: {detail}")


def _whisper_cache(settings: Settings) -> bool:
    cache = settings.models_dir / "whisper"
    return cache.exists() and any(cache.rglob("model.bin"))


def doctor(settings: Settings) -> int:
    critical_ok = True
    for tool in ("ffmpeg", "ffprobe", "node"):
        path = shutil.which(tool)
        _line(path is not None, tool, path or "not found on PATH")
        critical_ok &= path is not None
    _line(ffmpeg_has_nvenc(), "NVENC", "h264_nvenc available" if ffmpeg_has_nvenc() else "not available (CPU encoding will be used)")
    gpus = detect_gpus()
    _line(bool(gpus), "GPU", ", ".join(f"{g.name} ({g.memory_total_mb} MB)" for g in gpus) or "no NVIDIA GPU detected")
    try:
        import ctranslate2

        cuda_devices = ctranslate2.get_cuda_device_count()
    except Exception as exc:  # noqa: BLE001 — report any loader failure
        cuda_devices = 0
        _line(False, "CUDA for Whisper", f"ctranslate2 failed to load: {exc}")
    else:
        _line(cuda_devices > 0, "CUDA for Whisper", f"{cuda_devices} device(s)" if cuda_devices else "unavailable — Whisper will run on CPU")
    cached = _whisper_cache(settings)
    _line(cached, "Whisper model", f"{settings.whisper_model} cached" if cached else "not downloaded — run `python -m app.cli download-models`")
    return 0 if critical_ok else 1


def download_models(settings: Settings) -> int:
    from faster_whisper import download_model

    target = settings.models_dir / "whisper"
    print(f"Downloading Whisper '{settings.whisper_model}' into {target} …")
    path = download_model(settings.whisper_model, cache_dir=str(target))
    print(f"Whisper model ready at {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="clipforge")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="check ffmpeg, GPU, CUDA and models")
    sub.add_parser("download-models", help="download the Whisper model")
    args = parser.parse_args(argv)
    settings = get_settings()
    register_cuda_dlls()
    if args.command == "doctor":
        return doctor(settings)
    return download_models(settings)


if __name__ == "__main__":
    raise SystemExit(main())

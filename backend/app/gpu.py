"""GPU discovery and Windows CUDA DLL wiring.

ctranslate2 (used by faster-whisper) needs cuBLAS and cuDNN DLLs. We install them
as pip wheels (nvidia-cublas-cu12, nvidia-cudnn-cu12); on Windows their `bin`
folders must be registered before ctranslate2 is imported.
"""

import importlib.util
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GpuInfo:
    name: str
    memory_total_mb: int
    driver: str


def register_cuda_dlls() -> list[Path]:
    if sys.platform != "win32":
        return []
    spec = importlib.util.find_spec("nvidia")
    if spec is None or not spec.submodule_search_locations:
        return []
    added: list[Path] = []
    for base in spec.submodule_search_locations:
        for bin_dir in sorted(Path(base).glob("*/bin")):
            os.add_dll_directory(str(bin_dir))
            os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"
            added.append(bin_dir)
    logger.debug("Registered CUDA DLL directories: %s", added)
    return added


def parse_nvidia_smi(output: str) -> list[GpuInfo]:
    gpus: list[GpuInfo] = []
    for line in output.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 3:
            continue
        name, memory, driver = parts
        try:
            memory_mb = int(memory.split()[0])
        except (ValueError, IndexError):
            continue
        gpus.append(GpuInfo(name, memory_mb, driver))
    return gpus


@lru_cache
def detect_gpus() -> list[GpuInfo]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    try:
        proc = subprocess.run(
            [exe, "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=True,
        )
    except (subprocess.SubprocessError, OSError):
        return []
    return parse_nvidia_smi(proc.stdout)


@lru_cache
def ffmpeg_has_nvenc() -> bool:
    exe = shutil.which("ffmpeg")
    if not exe:
        return False
    try:
        proc = subprocess.run(
            [exe, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=15
        )
    except (subprocess.SubprocessError, OSError):
        return False
    return "h264_nvenc" in proc.stdout

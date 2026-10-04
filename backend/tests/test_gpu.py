import sys

from fastapi.testclient import TestClient

from app import gpu
from app.api import system
from app.gpu import GpuInfo, parse_nvidia_smi
from app.main import create_app


def test_parse_nvidia_smi_without_units():
    out = "NVIDIA GeForce RTX 3050 Laptop GPU, 4096, 610.62\n"
    assert parse_nvidia_smi(out) == [GpuInfo("NVIDIA GeForce RTX 3050 Laptop GPU", 4096, "610.62")]


def test_parse_nvidia_smi_with_units_and_multiple_gpus():
    out = "GPU A, 8192 MiB, 600.1\nGPU B, 4096 MiB, 600.1\n"
    assert [g.memory_total_mb for g in parse_nvidia_smi(out)] == [8192, 4096]


def test_parse_nvidia_smi_ignores_garbage():
    assert parse_nvidia_smi("No devices were found\n\n") == []


def test_register_cuda_dlls_is_noop_off_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert gpu.register_cuda_dlls() == []


def test_system_endpoint_reports_gpu_and_ffmpeg(settings, monkeypatch):
    monkeypatch.setattr(system, "detect_gpus", lambda: [GpuInfo("Test GPU", 4096, "1.0")])
    monkeypatch.setattr(system, "ffmpeg_has_nvenc", lambda: True)
    with TestClient(create_app(settings)) as client:
        body = client.get("/api/system").json()
    assert body["gpus"] == [{"name": "Test GPU", "memory_total_mb": 4096, "driver": "1.0"}]
    assert body["nvenc"] is True
    assert isinstance(body["ffmpeg"], bool)

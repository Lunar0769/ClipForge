from app import cli


def test_doctor_reports_every_check(capsys, monkeypatch, settings):
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    code = cli.main(["doctor"])
    out = capsys.readouterr().out
    assert code in (0, 1)
    for label in ("ffmpeg", "ffprobe", "node", "NVENC", "GPU", "CUDA for Whisper", "Whisper model"):
        assert label in out

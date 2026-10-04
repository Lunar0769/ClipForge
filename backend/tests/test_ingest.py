import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app import repo
from app.models import SourceType
from app.pipeline.download import DownloadResult
from app.pipeline.errors import StageError
from app.pipeline.ingest import IngestStage
from app.workspace import read_json


class FakeDownloader:
    def __init__(self, source: Path, title: str = "My Talk") -> None:
        self.source, self.title, self.calls = source, title, 0

    def __call__(self, url, dest_dir, on_progress, cancel):
        self.calls += 1
        dest_dir.mkdir(parents=True, exist_ok=True)
        target = dest_dir / "download.mp4"
        shutil.copy(self.source, target)
        on_progress(0.5, "Downloading… 50%")
        on_progress(1.0, "Downloading… 100%")
        return DownloadResult(path=target, title=self.title, channel="Chan", webpage_url=url)


def make_upload(make_ctx, workspace, src: Path, name: str = "sample vidéo.mp4"):
    ctx = make_ctx(source_type=SourceType.upload, original_filename=name)
    shutil.copy(src, workspace.project_dir(ctx.project_id) / f"upload{Path(name).suffix}")
    return ctx


def test_ingest_upload(make_ctx, workspace, engine, sample_video):
    ctx = make_upload(make_ctx, workspace, sample_video)
    stage = IngestStage(downloader=FakeDownloader(sample_video))
    assert not stage.is_done(ctx)

    stage.run(ctx)

    assert ctx.video_id
    vp = ctx.video()
    assert vp.find_source().name == "source.mp4"
    assert vp.audio.exists()
    meta = read_json(vp.meta)
    assert meta["video_id"] == ctx.video_id and meta["width"] == 640
    project = repo.get_project(engine, ctx.project_id)
    assert project.video_id == ctx.video_id
    assert project.title == "sample vidéo"
    assert project.duration_s == pytest.approx(3, abs=0.2)
    assert not list(workspace.project_dir(ctx.project_id).glob("upload.*"))
    assert stage.is_done(ctx)


def test_ingest_url_uses_downloader_title_and_reports_progress(make_ctx, engine, bus, sample_video):
    ctx = make_ctx(source_type=SourceType.url, source_url="https://youtu.be/x")
    downloader = FakeDownloader(sample_video, title="My Talk")
    IngestStage(downloader=downloader).run(ctx)
    assert downloader.calls == 1
    assert repo.get_project(engine, ctx.project_id).title == "My Talk"
    assert read_json(ctx.video().meta)["channel"] == "Chan"
    progress = [e.progress for e in bus.history(ctx.job_id) if e.type == "progress"]
    assert progress and max(progress) <= 1.0


def test_same_file_twice_shares_one_video_dir(make_ctx, workspace, sample_video):
    stage = IngestStage(downloader=FakeDownloader(sample_video))
    a = make_upload(make_ctx, workspace, sample_video)
    b = make_upload(make_ctx, workspace, sample_video)
    stage.run(a)
    stage.run(b)
    assert a.video_id == b.video_id
    assert len(list(workspace.videos_dir.iterdir())) == 1


def test_concurrent_ingest_of_same_file(make_ctx, workspace, sample_video):
    stage = IngestStage(downloader=FakeDownloader(sample_video))
    contexts = [make_upload(make_ctx, workspace, sample_video) for _ in range(3)]
    with ThreadPoolExecutor(3) as pool:
        list(pool.map(stage.run, contexts))
    assert len({c.video_id for c in contexts}) == 1
    assert contexts[0].video().audio.exists()
    assert len(list(workspace.videos_dir.iterdir())) == 1


def test_ingest_rejects_video_without_audio(make_ctx, workspace, no_audio_video):
    ctx = make_upload(make_ctx, workspace, no_audio_video, name="no audio.mp4")
    with pytest.raises(StageError, match="no audio track"):
        IngestStage(downloader=FakeDownloader(no_audio_video)).run(ctx)


def test_ingest_rejects_non_video(make_ctx, workspace, tmp_path):
    bogus = tmp_path / "fake.mp4"
    bogus.write_text("hello")
    ctx = make_upload(make_ctx, workspace, bogus, name="fake.mp4")
    with pytest.raises(StageError, match="couldn't be read"):
        IngestStage(downloader=FakeDownloader(bogus)).run(ctx)


def test_ingest_missing_upload(make_ctx, sample_video):
    ctx = make_ctx(source_type=SourceType.upload, original_filename="gone.mp4")
    with pytest.raises(StageError, match="missing"):
        IngestStage(downloader=FakeDownloader(sample_video)).run(ctx)


def test_ingest_resumes_when_audio_extraction_was_interrupted(make_ctx, workspace, sample_video):
    ctx = make_upload(make_ctx, workspace, sample_video)
    stage = IngestStage(downloader=FakeDownloader(sample_video))
    stage.run(ctx)
    ctx.video().audio.unlink()  # simulate crash after the source was imported
    assert not stage.is_done(ctx)
    stage.run(ctx)  # must not need the (already moved) upload again
    assert ctx.video().audio.exists()

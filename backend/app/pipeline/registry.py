from app.config import Settings
from app.jobs.queue import StagesFactory
from app.pipeline.download import YtDlpDownloader
from app.pipeline.ingest import IngestStage
from app.pipeline.render import RenderStage
from app.pipeline.score import ScoreStage
from app.pipeline.seo import SeoPackStage
from app.pipeline.transcribe import FasterWhisperTranscriber, TranscribeStage


def default_stages_factory(settings: Settings) -> StagesFactory:
    # Built once: the transcriber keeps the Whisper model loaded between jobs.
    stages = [
        IngestStage(YtDlpDownloader(
            max_height=settings.max_download_height,
            cookies_file=settings.ytdlp_cookies_file,
            js_runtime=settings.ytdlp_js_runtime,
        )),
        TranscribeStage(FasterWhisperTranscriber(
            model_name=settings.whisper_model,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
            download_root=settings.models_dir / "whisper",
        )),
        ScoreStage(),
        SeoPackStage(),
        RenderStage(),
    ]
    return lambda: stages

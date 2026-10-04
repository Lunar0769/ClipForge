import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import __version__, repo
from app.api import jobs, projects, system
from app.api.deps import Services
from app.config import Settings, get_settings
from app.db import make_engine
from app.events import EventBus
from app.gpu import register_cuda_dlls
from app.jobs.queue import JobQueue, StagesFactory
from app.workspace import Workspace

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(settings: Settings | None = None, stages_factory: StagesFactory | None = None) -> FastAPI:
    settings = settings or get_settings()
    register_cuda_dlls()  # before anything imports ctranslate2

    workspace = Workspace(settings.workspace_dir)
    engine = make_engine(settings.db_url)
    bus = EventBus()
    if stages_factory is None:
        from app.pipeline.registry import default_stages_factory

        stages_factory = default_stages_factory(settings)
    queue = JobQueue(
        engine=engine, workspace=workspace, settings=settings, bus=bus,
        stages_factory=stages_factory, concurrency=settings.job_concurrency,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await queue.start()
        for job_id in repo.recover_interrupted_jobs(engine):
            queue.submit(job_id)
        yield
        await queue.stop()
        engine.dispose()

    app = FastAPI(title="ClipForge API", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.services = Services(settings, engine, workspace, bus, queue, stages_factory)
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"],
    )
    app.include_router(system.router, prefix="/api")
    app.include_router(projects.router, prefix="/api")
    app.include_router(jobs.router, prefix="/api")
    app.mount("/files", StaticFiles(directory=workspace.videos_dir), name="files")
    return app

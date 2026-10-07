import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocketClose

from app import __version__, repo
from app.api import clips, jobs, projects, system
from app.api.deps import Services
from app.config import Settings, get_settings
from app.db import make_engine
from app.events import EventBus
from app.gpu import register_cuda_dlls
from app.jobs.queue import JobQueue, StagesFactory
from app.workspace import Workspace

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# "testserver" is the Host header FastAPI's TestClient sends.
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "testserver"]
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class OriginGuardMiddleware:
    """Rejects state-changing requests and WebSocket upgrades sent by other websites.

    CORS only stops a foreign page from *reading* responses; a cross-site form POST or
    WebSocket still reaches a local server. Requests without an Origin header (curl, scripts)
    are allowed: this guards against browsers on other origins, not local tools.
    """

    def __init__(self, app: ASGIApp, allowed_origins: list[str]) -> None:
        self.app = app
        self.allowed = {o.rstrip("/").lower() for o in allowed_origins}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            origin = next((v.decode("latin-1") for k, v in scope["headers"] if k == b"origin"), None)
            unsafe = scope["type"] == "websocket" or scope["method"] not in _SAFE_METHODS
            if unsafe and origin is not None and origin.rstrip("/").lower() not in self.allowed:
                if scope["type"] == "websocket":
                    await WebSocketClose(code=1008)(scope, receive, send)  # closed before accept -> HTTP 403
                else:
                    await JSONResponse({"detail": "Origin not allowed"}, status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)


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
    app.add_middleware(OriginGuardMiddleware, allowed_origins=settings.cors_origins)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)  # outermost: blocks DNS rebinding
    app.include_router(system.router, prefix="/api")
    app.include_router(projects.router, prefix="/api")
    app.include_router(jobs.router, prefix="/api")
    app.include_router(clips.router, prefix="/api")
    app.mount("/files", StaticFiles(directory=workspace.videos_dir), name="files")
    return app

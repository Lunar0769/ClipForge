from dataclasses import dataclass

from fastapi import Request
from sqlalchemy import Engine

from app.config import Settings
from app.events import EventBus
from app.jobs.queue import JobQueue, StagesFactory
from app.workspace import Workspace


@dataclass
class Services:
    settings: Settings
    engine: Engine
    workspace: Workspace
    bus: EventBus
    queue: JobQueue
    stages_factory: StagesFactory


def get_services(request: Request) -> Services:
    return request.app.state.services

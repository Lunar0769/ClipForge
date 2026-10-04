from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect

from app import repo
from app.api.deps import Services, get_services
from app.api.schemas import JobOut, StageInfo
from app.models import TERMINAL_STATUSES

router = APIRouter(tags=["jobs"])


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, svc: Services = Depends(get_services)) -> JobOut:
    job = repo.get_job(svc.engine, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return JobOut.model_validate(job)


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: str, svc: Services = Depends(get_services)) -> JobOut:
    job = repo.get_job(svc.engine, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    if job.status in TERMINAL_STATUSES or not svc.queue.cancel(job_id):
        raise HTTPException(409, "This job has already finished")
    return JobOut.model_validate(repo.get_job(svc.engine, job_id))


@router.get("/pipeline/stages", response_model=list[StageInfo])
def pipeline_stages(svc: Services = Depends(get_services)) -> list[StageInfo]:
    return [StageInfo(name=s.name, label=s.label, weight=s.weight) for s in svc.stages_factory()]


@router.websocket("/jobs/{job_id}/events")
async def job_events(websocket: WebSocket, job_id: str) -> None:
    svc: Services = websocket.app.state.services
    await websocket.accept()
    queue = svc.bus.subscribe(job_id)
    try:
        while True:
            event = await queue.get()
            await websocket.send_text(event.model_dump_json())
    except WebSocketDisconnect:
        pass
    finally:
        svc.bus.unsubscribe(job_id, queue)

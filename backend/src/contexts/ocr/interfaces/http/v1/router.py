from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse

from src.contexts.ocr.application.dto import (
    ArtifactListDTO,
    CompleteUploadDTO,
    CompleteUploadRequest,
    CreateJobRequest,
    CreateUploadRequest,
    HealthDTO,
    JobDTO,
    JobEventDTO,
    JobListDTO,
    UploadDTO,
)
from src.contexts.ocr.application.services import OCRApplicationService
from src.contexts.ocr.domain.models import JobState
from src.shared.api import ApiEnvelope, InternalStatusCode
from src.shared.errors import BusinessError

from .dependencies import get_authenticated_owner_id, get_request_id, get_service

router = APIRouter(prefix="/v1", tags=["ocr"])
health_router = APIRouter(tags=["health"])

Service = Annotated[OCRApplicationService, Depends(get_service)]
OwnerID = Annotated[str, Depends(get_authenticated_owner_id)]
RequestID = Annotated[str, Depends(get_request_id)]


@router.post("/uploads", response_model=ApiEnvelope[UploadDTO])
async def create_upload(
    payload: CreateUploadRequest,
    service: Service,
    owner_id: OwnerID,
    request_id: RequestID,
) -> ApiEnvelope[UploadDTO]:
    return ApiEnvelope.success(
        await service.create_upload(payload, owner_id=owner_id), request_id=request_id
    )


@router.post("/uploads/{upload_id}/complete", response_model=ApiEnvelope[CompleteUploadDTO])
async def complete_upload(
    upload_id: UUID,
    service: Service,
    owner_id: OwnerID,
    request_id: RequestID,
    payload: CompleteUploadRequest | None = None,
) -> ApiEnvelope[CompleteUploadDTO]:
    return ApiEnvelope.success(
        await service.complete_upload(
            upload_id,
            owner_id=owner_id,
            provided_sha256=payload.sha256 if payload else None,
            multipart_upload_id=payload.multipart_upload_id if payload else None,
            parts=[(part.part_number, part.etag) for part in payload.parts] if payload else [],
        ),
        request_id=request_id,
    )


@router.post("/jobs", response_model=ApiEnvelope[JobDTO])
async def create_job(
    payload: CreateJobRequest,
    service: Service,
    owner_id: OwnerID,
    request_id: RequestID,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ApiEnvelope[JobDTO]:
    if idempotency_key is not None and not (1 <= len(idempotency_key) <= 160):
        raise BusinessError(
            InternalStatusCode.COMMON_INVALID_ARGUMENT,
            "幂等键长度必须为 1 到 160 个字符",
            "invalid_idempotency_key",
        )
    return ApiEnvelope.success(
        await service.create_job(
            payload,
            owner_id=owner_id,
            request_id=request_id,
            idempotency_key=idempotency_key,
        ),
        request_id=request_id,
    )


@router.get("/jobs", response_model=ApiEnvelope[JobListDTO])
async def list_jobs(
    service: Service,
    owner_id: OwnerID,
    request_id: RequestID,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ApiEnvelope[JobListDTO]:
    return ApiEnvelope.success(
        await service.list_jobs(owner_id=owner_id, page=page, page_size=page_size),
        request_id=request_id,
    )


@router.get("/jobs/{job_id}", response_model=ApiEnvelope[JobDTO])
async def get_job(
    job_id: UUID,
    service: Service,
    owner_id: OwnerID,
    request_id: RequestID,
) -> ApiEnvelope[JobDTO]:
    return ApiEnvelope.success(
        await service.get_job(job_id, owner_id=owner_id), request_id=request_id
    )


@router.post("/jobs/{job_id}/cancel", response_model=ApiEnvelope[JobDTO])
async def cancel_job(
    job_id: UUID,
    service: Service,
    owner_id: OwnerID,
    request_id: RequestID,
) -> ApiEnvelope[JobDTO]:
    return ApiEnvelope.success(
        await service.cancel_job(
            job_id, owner_id=owner_id, request_id=request_id
        ),
        request_id=request_id,
    )


@router.post("/jobs/{job_id}/retry", response_model=ApiEnvelope[JobDTO])
async def retry_job(
    job_id: UUID,
    service: Service,
    owner_id: OwnerID,
    request_id: RequestID,
) -> ApiEnvelope[JobDTO]:
    return ApiEnvelope.success(
        await service.retry_job(
            job_id, owner_id=owner_id, request_id=request_id
        ),
        request_id=request_id,
    )


@router.get("/jobs/{job_id}/artifacts", response_model=ApiEnvelope[ArtifactListDTO])
async def list_artifacts(
    job_id: UUID,
    service: Service,
    owner_id: OwnerID,
    request_id: RequestID,
) -> ApiEnvelope[ArtifactListDTO]:
    return ApiEnvelope.success(
        await service.list_artifacts(job_id, owner_id=owner_id), request_id=request_id
    )


@router.get("/jobs/{job_id}/events", response_class=StreamingResponse)
async def stream_job_events(
    job_id: UUID,
    request: Request,
    service: Service,
    owner_id: OwnerID,
    request_id: RequestID,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    job = await service.get_job_domain(job_id, owner_id=owner_id)
    try:
        sequence = int(last_event_id or 0)
        if sequence < 0:
            raise ValueError
    except ValueError as exc:
        raise BusinessError(
            InternalStatusCode.COMMON_INVALID_ARGUMENT,
            "Last-Event-ID 必须为非负整数",
            "invalid_last_event_id",
        ) from exc

    events = request.app.state.container.events
    heartbeat_seconds = request.app.state.container.settings.sse_heartbeat_seconds

    async def generate():
        nonlocal sequence, job
        while True:
            pending = await events.list_after(job_id, sequence)
            if not pending:
                pending = await events.wait_after(job_id, sequence, heartbeat_seconds)
            if not pending:
                if await request.is_disconnected():
                    break
                latest = await service.get_job_domain(job_id, owner_id=owner_id)
                if latest.terminal:
                    break
                yield ": heartbeat\n\n"
                continue
            for event in pending:
                sequence = event.sequence
                envelope = ApiEnvelope.success(
                    JobEventDTO.from_domain(event), request_id=event.request_id
                )
                yield f"id: {event.sequence}\nevent: {event.event_type}\ndata: {envelope.model_dump_json()}\n\n"
            latest = await service.get_job_domain(job_id, owner_id=owner_id)
            last = pending[-1]
            if (
                latest.terminal
                and last.state is latest.state
                and last.payload.get("attempt") == latest.attempt
            ):
                return

    return StreamingResponse(
        generate(),
        status_code=200,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@health_router.get("/health/live", response_model=ApiEnvelope[HealthDTO])
async def live(request_id: RequestID) -> ApiEnvelope[HealthDTO]:
    return ApiEnvelope.success(HealthDTO(status="ok"), request_id=request_id)


@health_router.get("/health/ready", response_model=ApiEnvelope[HealthDTO])
async def ready(request: Request, request_id: RequestID) -> ApiEnvelope[HealthDTO]:
    report = await request.app.state.container.readiness.check()
    data = HealthDTO(
        status="ready" if report.ready else "not_ready",
        checks=report.checks,
    )
    if report.ready:
        return ApiEnvelope.success(data, request_id=request_id)
    return ApiEnvelope.failure(
        report.internal_code or InternalStatusCode.INTERNAL_CONTROLLED_ERROR,
        message="服务依赖尚未就绪",
        request_id=request_id,
        error_reason=report.error_reason or "readiness_dependency_unavailable",
        data=data,
    )

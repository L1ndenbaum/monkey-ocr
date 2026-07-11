import hashlib

import pytest

from src.container import create_memory_container
from src.contexts.ocr.application.dto import CreateJobRequest, CreateUploadRequest
from src.contexts.ocr.domain.models import JobState
from src.shared.api import InternalStatusCode
from src.shared.errors import BusinessError


PNG = b"\x89PNG\r\n\x1a\n" + b"test-image"


async def create_completed_upload(container, *, owner: str = "owner"):
    request = CreateUploadRequest(
        filename="../invoice.png",
        size_bytes=len(PNG),
        content_type="image/png",
        sha256=hashlib.sha256(PNG).hexdigest(),
    )
    upload = await container.service.create_upload(request, owner_id=owner)
    await container.storage.put_bytes(upload.object_key, PNG, content_type="image/png")
    completed = await container.service.complete_upload(
        upload.upload_id, owner_id=owner, provided_sha256=request.sha256
    )
    return upload, completed


@pytest.mark.asyncio
async def test_upload_validation_and_idempotent_job_creation() -> None:
    container = create_memory_container()
    upload, completed = await create_completed_upload(container)
    assert completed.status == "completed"

    request = CreateJobRequest(upload_id=upload.upload_id)
    first = await container.service.create_job(
        request,
        owner_id="owner",
        request_id="request-1",
        idempotency_key="invoice-1",
    )
    second = await container.service.create_job(
        request,
        owner_id="owner",
        request_id="request-2",
        idempotency_key="invoice-1",
    )

    assert first.job_id == second.job_id
    assert first.filename == "invoice.png"
    assert len(await container.outbox.pending()) == 1


@pytest.mark.asyncio
async def test_upload_hash_mismatch_is_controlled() -> None:
    container = create_memory_container()
    request = CreateUploadRequest(
        filename="invoice.png",
        size_bytes=len(PNG),
        content_type="image/png",
        sha256="0" * 64,
    )
    upload = await container.service.create_upload(request, owner_id="owner")
    await container.storage.put_bytes(upload.object_key, PNG, content_type="image/png")

    with pytest.raises(BusinessError) as caught:
        await container.service.complete_upload(upload.upload_id, owner_id="owner")
    assert caught.value.internal_code is InternalStatusCode.UPLOAD_HASH_MISMATCH


@pytest.mark.asyncio
async def test_queued_job_cancels_immediately() -> None:
    container = create_memory_container()
    upload, _ = await create_completed_upload(container)
    job = await container.service.create_job(
        CreateJobRequest(upload_id=upload.upload_id),
        owner_id="owner",
        request_id="request",
        idempotency_key=None,
    )
    cancelled = await container.service.cancel_job(
        job.job_id, owner_id="owner", request_id="cancel"
    )
    assert cancelled.status == JobState.CANCELLED

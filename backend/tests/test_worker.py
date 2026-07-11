import asyncio
import hashlib

import pytest

from src.container import create_memory_container
from src.contexts.ocr.application.dto import CreateJobRequest, CreateUploadRequest
from src.contexts.ocr.application.ports import JobWorkMessage
from src.contexts.ocr.application.worker import OCRWorker
from src.contexts.ocr.domain.models import ArtifactKind, JobEvent, JobState
from src.infrastructure.engine import FakeOCREngine
from src.infrastructure.memory import InMemoryStructuredLogger
from src.infrastructure.preprocessor import StaticDocumentPreprocessor


PNG = b"\x89PNG\r\n\x1a\n" + b"source"


class BlockingResultStorage:
    def __init__(self, delegate) -> None:
        self.delegate = delegate
        self.result_write_started = asyncio.Event()
        self.release_result_write = asyncio.Event()

    def __getattr__(self, name: str):
        return getattr(self.delegate, name)

    async def put_bytes(self, object_key: str, data: bytes, *, content_type: str):
        if "/pages/" in object_key and object_key.endswith(".json"):
            self.result_write_started.set()
            await self.release_result_write.wait()
        return await self.delegate.put_bytes(
            object_key, data, content_type=content_type
        )


class FailOnceSucceededEventRepository:
    def __init__(self, delegate) -> None:
        self.delegate = delegate
        self.failed = False

    async def append(self, event: JobEvent) -> JobEvent:
        if event.event_type == "job.succeeded" and not self.failed:
            self.failed = True
            raise RuntimeError("injected event write failure")
        return await self.delegate.append(event)


async def create_queued_job():
    container = create_memory_container()
    request = CreateUploadRequest(
        filename="pages.png",
        size_bytes=len(PNG),
        content_type="image/png",
        sha256=hashlib.sha256(PNG).hexdigest(),
    )
    upload = await container.service.create_upload(request, owner_id="owner")
    await container.storage.put_bytes(upload.object_key, PNG, content_type="image/png")
    await container.service.complete_upload(upload.upload_id, owner_id="owner")
    created = await container.service.create_job(
        CreateJobRequest(upload_id=upload.upload_id),
        owner_id="owner",
        request_id="request",
        idempotency_key=None,
    )
    return container, created


@pytest.mark.asyncio
async def test_worker_retries_checkpoints_and_publishes_manifest_last() -> None:
    container, created = await create_queued_job()
    engine = FakeOCREngine(failures_before_success=3)
    delays: list[float] = []

    async def record_delay(delay: float) -> None:
        delays.append(delay)

    worker = OCRWorker(
        jobs=container.jobs,
        uploads=container.uploads,
        events=container.events,
        storage=container.storage,
        preprocessor=StaticDocumentPreprocessor(container.storage, [b"page-one"]),
        engine=engine,
        logger=InMemoryStructuredLogger(),
        max_page_retries=3,
        sleeper=record_delay,
    )
    message = JobWorkMessage(
        job_id=created.job_id, attempt=1, request_id="request"
    )

    result = await worker.process(message)

    assert result is not None and result.state is JobState.SUCCEEDED
    assert engine.calls == 4
    assert result.pages[0].processing_attempts == 4
    assert result.engine_name == "fake"
    assert result.engine_version == "1"
    assert result.model_name == "fake-local"
    assert delays == [1, 2, 4]
    assert result.pages[0].result_object_key
    assert result.artifacts[-1].kind is ArtifactKind.MANIFEST
    manifest = await container.storage.get_bytes(result.artifacts[-1].object_key)
    assert b'"schema_version":1' in manifest

    repeated = await worker.process(message)
    assert repeated is not None and repeated.state is JobState.SUCCEEDED
    assert engine.calls == 4


@pytest.mark.asyncio
async def test_page_retry_budget_and_backoff_survive_worker_restart() -> None:
    container, created = await create_queued_job()
    message = JobWorkMessage(
        job_id=created.job_id, attempt=1, request_id="request"
    )
    first_engine = FakeOCREngine(failures_before_success=99)
    first_delays: list[float] = []

    async def crash_after_second_delay(delay: float) -> None:
        first_delays.append(delay)
        if len(first_delays) == 2:
            raise asyncio.CancelledError

    first_worker = OCRWorker(
        jobs=container.jobs,
        uploads=container.uploads,
        events=container.events,
        storage=container.storage,
        preprocessor=StaticDocumentPreprocessor(container.storage, [b"page-one"]),
        engine=first_engine,
        logger=InMemoryStructuredLogger(),
        max_page_retries=3,
        sleeper=crash_after_second_delay,
    )

    with pytest.raises(asyncio.CancelledError):
        await first_worker.process(message)

    checkpoint = await container.jobs.get(created.job_id)
    assert checkpoint is not None
    assert checkpoint.state is JobState.RUNNING
    assert checkpoint.pages[0].processing_attempts == 2
    assert checkpoint.pages[0].error_reason == "engine_unavailable"
    assert first_delays == [1, 2]

    resumed_engine = FakeOCREngine(failures_before_success=99)
    resumed_delays: list[float] = []

    async def record_resumed_delay(delay: float) -> None:
        resumed_delays.append(delay)

    resumed_worker = OCRWorker(
        jobs=container.jobs,
        uploads=container.uploads,
        events=container.events,
        storage=container.storage,
        preprocessor=StaticDocumentPreprocessor(container.storage, [b"unused"]),
        engine=resumed_engine,
        logger=InMemoryStructuredLogger(),
        max_page_retries=3,
        sleeper=record_resumed_delay,
    )

    result = await resumed_worker.process(message)

    assert result is not None and result.state is JobState.FAILED
    assert resumed_engine.calls == 2
    assert result.pages[0].processing_attempts == 4
    assert resumed_delays == [4]


@pytest.mark.asyncio
async def test_cancel_cannot_be_overwritten_by_stale_page_checkpoint() -> None:
    container, created = await create_queued_job()
    storage = BlockingResultStorage(container.storage)
    worker = OCRWorker(
        jobs=container.jobs,
        uploads=container.uploads,
        events=container.events,
        storage=storage,
        preprocessor=StaticDocumentPreprocessor(storage, [b"page-one"]),
        engine=FakeOCREngine(),
        logger=InMemoryStructuredLogger(),
    )
    message = JobWorkMessage(
        job_id=created.job_id, attempt=1, request_id="request"
    )

    running = asyncio.create_task(worker.process(message))
    await storage.result_write_started.wait()
    requested = await container.service.cancel_job(
        created.job_id, owner_id="owner", request_id="cancel-request"
    )
    assert requested.status == JobState.CANCEL_REQUESTED
    storage.release_result_write.set()

    result = await running

    assert result is not None and result.state is JobState.CANCELLED
    persisted = await container.jobs.get(created.job_id)
    assert persisted is not None and persisted.state is JobState.CANCELLED


@pytest.mark.asyncio
async def test_state_and_terminal_event_roll_back_together_then_redeliver() -> None:
    container, created = await create_queued_job()
    flaky_events = FailOnceSucceededEventRepository(container.events)
    container.jobs.events = flaky_events
    worker = OCRWorker(
        jobs=container.jobs,
        uploads=container.uploads,
        events=flaky_events,
        storage=container.storage,
        preprocessor=StaticDocumentPreprocessor(container.storage, [b"page-one"]),
        engine=FakeOCREngine(),
        logger=InMemoryStructuredLogger(),
    )
    message = JobWorkMessage(
        job_id=created.job_id, attempt=1, request_id="request"
    )

    with pytest.raises(Exception, match="database operation failed"):
        await worker.process(message)
    persisted = await container.jobs.get(created.job_id)
    assert persisted is not None and persisted.state is JobState.ASSEMBLING

    repaired = await worker.process(message)
    repeated = await worker.process(message)

    assert repaired is not None and repaired.state is JobState.SUCCEEDED
    assert repeated is not None and repeated.state is JobState.SUCCEEDED
    events = await container.events.list_after(created.job_id, 0)
    assert [event.event_type for event in events].count("job.succeeded") == 1


@pytest.mark.asyncio
async def test_redelivery_repairs_a_preexisting_missing_terminal_event() -> None:
    container, created = await create_queued_job()
    job = await container.jobs.get(created.job_id)
    assert job is not None
    job.state = JobState.FAILED
    job.internal_code = 50001
    job.error_reason = "engine_unavailable"
    await container.jobs.save(job)
    worker = OCRWorker(
        jobs=container.jobs,
        uploads=container.uploads,
        events=container.events,
        storage=container.storage,
        preprocessor=StaticDocumentPreprocessor(container.storage, [b"unused"]),
        engine=FakeOCREngine(),
        logger=InMemoryStructuredLogger(),
    )

    repaired = await worker.process(
        JobWorkMessage(job_id=job.id, attempt=1, request_id="request")
    )
    repeated = await worker.process(
        JobWorkMessage(job_id=job.id, attempt=1, request_id="request")
    )

    assert repaired is not None and repaired.state is JobState.FAILED
    assert repeated is not None and repeated.state is JobState.FAILED
    events = await container.events.list_after(job.id, 0)
    failed = [event for event in events if event.event_type == "job.failed"]
    assert len(failed) == 1
    assert failed[0].payload["internal_code"] == 50001

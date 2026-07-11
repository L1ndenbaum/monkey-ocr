from __future__ import annotations

import hashlib

import httpx
import pytest
from uuid6 import uuid7

from src.config import Settings
from src.container import create_memory_container
from src.contexts.ocr.application.dto import CreateJobRequest, CreateUploadRequest
from src.contexts.ocr.application.exceptions import (
    DatabaseUnavailableError,
    EngineTimeoutError,
    EngineUnavailableError,
    QueueUnavailableError,
)
from src.contexts.ocr.application.ports import JobWorkMessage
from src.contexts.ocr.application.worker import OCRWorker
from src.contexts.ocr.domain.models import JobState
from src.infrastructure.api_keys import PostgresAPIKeyAuthenticator
from src.infrastructure.memory import InMemoryObjectStorage, InMemoryStructuredLogger
from src.infrastructure.messaging import KafkaJobPublisher, OutboxDispatcher
from src.infrastructure.preprocessor import StaticDocumentPreprocessor
from src.main import create_app
from src.shared.api import InternalStatusCode


PNG = b"\x89PNG\r\n\x1a\n" + b"dependency-test"


class UploadTargetFailureStorage(InMemoryObjectStorage):
    async def create_upload_target(self, *args, **kwargs):
        raise OSError("private storage endpoint details")


class PageReadFailureStorage(InMemoryObjectStorage):
    async def get_bytes(self, object_key: str) -> bytes:
        if object_key.startswith("jobs/"):
            raise OSError("private storage endpoint details")
        return await super().get_bytes(object_key)


class DatabaseFailureJobs:
    async def get(self, job_id):
        raise ConnectionError("private database endpoint details")


class DatabaseFailureAcquire:
    async def __aenter__(self):
        raise ConnectionError("private database endpoint details")

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class DatabaseFailurePool:
    def acquire(self):
        return DatabaseFailureAcquire()


class KafkaFailureProducer:
    async def send_and_wait(self, topic, value, *, key=None):
        raise ConnectionError("private broker endpoint details")


class DatabaseFailureOutbox:
    async def pending(self, *, limit=100):
        raise ConnectionError("private database endpoint details")


class FailingEngine:
    def __init__(self, error_type: type[Exception]) -> None:
        self.error_type = error_type

    async def recognize(self, **kwargs):
        raise self.error_type("private engine endpoint details")


@pytest.mark.asyncio
async def test_storage_availability_failure_uses_controlled_api_envelope() -> None:
    settings = Settings(environment="test")
    container = create_memory_container(settings)
    container.service.storage = UploadTargetFailureStorage()
    app = create_app(settings=settings, container=container)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/v1/uploads",
            json={
                "filename": "invoice.png",
                "size_bytes": len(PNG),
                "content_type": "image/png",
                "sha256": hashlib.sha256(PNG).hexdigest(),
            },
        )

    assert response.status_code == 200
    assert response.json()["internal_code"] == InternalStatusCode.STORAGE_UNAVAILABLE
    assert response.json()["error_reason"] == "storage_unavailable"
    assert "private" not in response.text


@pytest.mark.asyncio
async def test_database_availability_failure_uses_controlled_api_envelope() -> None:
    settings = Settings(environment="test")
    container = create_memory_container(settings)
    container.service.jobs = DatabaseFailureJobs()  # type: ignore[assignment]
    app = create_app(settings=settings, container=container)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.get(f"/v1/jobs/{uuid7()}")

    assert response.status_code == 200
    assert response.json()["internal_code"] == InternalStatusCode.DATABASE_UNAVAILABLE
    assert response.json()["error_reason"] == "database_unavailable"
    assert "private" not in response.text


@pytest.mark.asyncio
async def test_api_key_database_failure_is_typed_and_redacted() -> None:
    authenticator = PostgresAPIKeyAuthenticator(
        pool=DatabaseFailurePool(), pepper="test-pepper"
    )

    with pytest.raises(DatabaseUnavailableError) as caught:
        await authenticator.authenticate("mocr_prefix_secret")

    assert caught.value.internal_code is InternalStatusCode.DATABASE_UNAVAILABLE
    assert caught.value.error_reason == "database_unavailable"
    assert "private" not in str(caught.value)


@pytest.mark.asyncio
async def test_kafka_and_outbox_failures_are_typed_by_dependency() -> None:
    publisher = KafkaJobPublisher(producer=KafkaFailureProducer(), topic="monkeyocr.jobs")
    with pytest.raises(QueueUnavailableError) as queue_error:
        await publisher.publish(
            JobWorkMessage(job_id=uuid7(), attempt=1, request_id="request")
        )
    assert queue_error.value.internal_code is InternalStatusCode.QUEUE_UNAVAILABLE

    dispatcher = OutboxDispatcher(
        outbox=DatabaseFailureOutbox(),  # type: ignore[arg-type]
        publisher=publisher,
    )
    with pytest.raises(DatabaseUnavailableError) as database_error:
        await dispatcher.dispatch_once()
    assert database_error.value.internal_code is InternalStatusCode.DATABASE_UNAVAILABLE


async def _prepared_job(container):
    request = CreateUploadRequest(
        filename="invoice.png",
        size_bytes=len(PNG),
        content_type="image/png",
        sha256=hashlib.sha256(PNG).hexdigest(),
    )
    upload = await container.service.create_upload(request, owner_id="owner")
    await container.storage.put_bytes(upload.object_key, PNG, content_type="image/png")
    await container.service.complete_upload(upload.upload_id, owner_id="owner")
    return await container.service.create_job(
        CreateJobRequest(upload_id=upload.upload_id),
        owner_id="owner",
        request_id="request",
        idempotency_key=None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_type", "expected_code", "expected_reason"),
    [
        (
            EngineUnavailableError,
            InternalStatusCode.ENGINE_UNAVAILABLE,
            "engine_unavailable",
        ),
        (EngineTimeoutError, InternalStatusCode.ENGINE_TIMEOUT, "engine_timeout"),
    ],
)
async def test_worker_persists_engine_dependency_failure_metadata(
    error_type: type[Exception],
    expected_code: InternalStatusCode,
    expected_reason: str,
) -> None:
    container = create_memory_container()
    created = await _prepared_job(container)
    logger = InMemoryStructuredLogger()
    worker = OCRWorker(
        jobs=container.jobs,
        uploads=container.uploads,
        events=container.events,
        storage=container.storage,
        preprocessor=StaticDocumentPreprocessor(container.storage, [b"page"]),
        engine=FailingEngine(error_type),  # type: ignore[arg-type]
        logger=logger,
        max_page_retries=0,
    )

    result = await worker.process(
        JobWorkMessage(job_id=created.job_id, attempt=1, request_id="request")
    )

    assert result is not None and result.state is JobState.FAILED
    assert result.internal_code == expected_code
    assert result.error_reason == expected_reason
    assert result.pages[0].internal_code == expected_code
    events = await container.events.list_after(result.id, 0)
    assert events[-1].payload["internal_code"] == expected_code
    failure_log = next(record for record in logger.records if record["event"] == "ocr_job_failed")
    assert failure_log["internal_code"] == expected_code
    assert failure_log["error_reason"] == expected_reason
    assert "private" not in str(failure_log)


@pytest.mark.asyncio
async def test_worker_persists_storage_dependency_failure_metadata() -> None:
    container = create_memory_container()
    storage = PageReadFailureStorage()
    container.storage = storage
    container.service.storage = storage
    created = await _prepared_job(container)
    logger = InMemoryStructuredLogger()
    worker = OCRWorker(
        jobs=container.jobs,
        uploads=container.uploads,
        events=container.events,
        storage=storage,
        preprocessor=StaticDocumentPreprocessor(storage, [b"page"]),
        engine=FailingEngine(AssertionError),  # type: ignore[arg-type]
        logger=logger,
        max_page_retries=0,
    )

    result = await worker.process(
        JobWorkMessage(job_id=created.job_id, attempt=1, request_id="request")
    )

    assert result is not None and result.state is JobState.FAILED
    assert result.internal_code == InternalStatusCode.STORAGE_UNAVAILABLE
    assert result.error_reason == "storage_unavailable"
    failure_log = next(record for record in logger.records if record["event"] == "ocr_job_failed")
    assert failure_log["internal_code"] == InternalStatusCode.STORAGE_UNAVAILABLE


@pytest.mark.asyncio
async def test_worker_logs_and_rethrows_database_unavailability_for_redelivery() -> None:
    container = create_memory_container()
    logger = InMemoryStructuredLogger()
    worker = OCRWorker(
        jobs=DatabaseFailureJobs(),  # type: ignore[arg-type]
        uploads=container.uploads,
        events=container.events,
        storage=container.storage,
        preprocessor=container.preprocessor,
        engine=container.engine,
        logger=logger,
    )
    message = JobWorkMessage(job_id=uuid7(), attempt=1, request_id="request")

    with pytest.raises(DatabaseUnavailableError):
        await worker.process(message)

    failure_log = next(record for record in logger.records if record["event"] == "ocr_job_failed")
    assert failure_log["internal_code"] == InternalStatusCode.DATABASE_UNAVAILABLE
    assert failure_log["error_reason"] == "database_unavailable"
    assert "private" not in str(failure_log)

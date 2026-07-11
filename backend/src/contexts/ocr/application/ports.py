from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol
from uuid import UUID

from ..domain.models import Job, JobEvent, Upload


@dataclass(slots=True, frozen=True)
class UploadTarget:
    url: str
    method: str = "PUT"
    headers: dict[str, str] = field(default_factory=dict)
    upload_id: str | None = None
    part_size_bytes: int | None = None
    part_urls: tuple[tuple[int, str], ...] = ()


@dataclass(slots=True, frozen=True)
class ObjectInfo:
    object_key: str
    size_bytes: int
    sha256: str | None
    content_type: str


@dataclass(slots=True, frozen=True)
class StoredObject:
    object_key: str
    size_bytes: int
    sha256: str
    content_type: str


@dataclass(slots=True, frozen=True)
class FileValidationResult:
    detected_content_type: str


@dataclass(slots=True, frozen=True)
class PreparedPage:
    page_number: int
    object_key: str


@dataclass(slots=True, frozen=True)
class OCRResult:
    markdown: str
    structured: dict[str, Any]
    visualization: bytes | None = None
    visualization_content_type: str = "image/png"
    engine_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class JobWorkMessage:
    job_id: UUID
    attempt: int
    request_id: str
    schema_version: int = 1


@dataclass(slots=True)
class OutboxEvent:
    aggregate_id: UUID
    event_type: str
    payload: dict[str, Any]
    request_id: str
    id: UUID
    created_at: datetime
    published_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class RetentionCandidate:
    aggregate_kind: Literal["job", "upload"]
    aggregate_id: UUID
    claim_token: UUID
    object_keys: tuple[str, ...]
    multipart_upload_id: str | None = None


class UploadRepository(Protocol):
    async def add(self, upload: Upload) -> None: ...

    async def get(self, upload_id: UUID) -> Upload | None: ...

    async def save(self, upload: Upload) -> None: ...


class JobRepository(Protocol):
    async def add(self, job: Job) -> None: ...

    async def get(self, job_id: UUID) -> Job | None: ...

    async def save(self, job: Job) -> None: ...

    async def save_with_event(self, job: Job, event: JobEvent) -> JobEvent: ...

    async def find_by_idempotency_key(self, owner_id: str, key: str) -> Job | None: ...

    async def list(self, owner_id: str, *, offset: int, limit: int) -> tuple[list[Job], int]: ...

    async def add_with_outbox_and_event(
        self,
        job: Job,
        outbox_event: OutboxEvent,
        job_event: JobEvent,
        outbox: OutboxRepository,
    ) -> JobEvent: ...

    async def save_with_outbox_and_event(
        self,
        job: Job,
        outbox_event: OutboxEvent,
        job_event: JobEvent,
        outbox: OutboxRepository,
    ) -> JobEvent: ...


class JobEventRepository(Protocol):
    async def append(self, event: JobEvent) -> JobEvent: ...

    async def list_after(self, job_id: UUID, sequence: int) -> list[JobEvent]: ...

    async def wait_after(
        self, job_id: UUID, sequence: int, timeout_seconds: float
    ) -> list[JobEvent]: ...


class OutboxRepository(Protocol):
    async def add(self, event: OutboxEvent) -> None: ...

    async def pending(self, *, limit: int = 100) -> list[OutboxEvent]: ...

    async def mark_published(self, event_id: UUID) -> None: ...


class RetentionRepository(Protocol):
    async def claim_expired(
        self,
        *,
        now: datetime,
        limit: int,
        lease_seconds: int,
    ) -> list[RetentionCandidate]: ...

    async def complete(self, candidate: RetentionCandidate) -> bool: ...

    async def defer(
        self, candidate: RetentionCandidate, *, retry_at: datetime
    ) -> None: ...


class ObjectStorage(Protocol):
    async def create_upload_target(
        self,
        object_key: str,
        *,
        content_type: str,
        size_bytes: int,
        sha256: str,
    ) -> UploadTarget: ...

    async def stat(self, object_key: str) -> ObjectInfo | None: ...

    async def complete_upload(
        self,
        object_key: str,
        *,
        upload_id: str | None,
        parts: list[tuple[int, str]],
    ) -> None: ...

    async def get_bytes(self, object_key: str) -> bytes: ...

    async def put_bytes(
        self, object_key: str, data: bytes, *, content_type: str
    ) -> StoredObject: ...

    async def delete_object(self, object_key: str) -> None: ...

    async def abort_multipart_upload(
        self, object_key: str, upload_id: str
    ) -> None: ...

    async def create_download_url(self, object_key: str) -> str: ...


class FileValidator(Protocol):
    async def validate(self, upload: Upload, data: bytes) -> FileValidationResult: ...


class DocumentPreprocessor(Protocol):
    async def prepare(self, upload: Upload, job: Job) -> list[PreparedPage]: ...


class OCREngine(Protocol):
    async def recognize(
        self,
        *,
        image: bytes,
        page_number: int,
        options: dict[str, Any],
        request_id: str,
    ) -> OCRResult: ...


class QueuePublisher(Protocol):
    async def publish(self, message: JobWorkMessage) -> None: ...


class StructuredLogger(Protocol):
    async def info(self, event: str, **fields: Any) -> None: ...

    async def error(self, event: str, **fields: Any) -> None: ...

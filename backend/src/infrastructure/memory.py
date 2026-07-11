from __future__ import annotations

import asyncio
import copy
import hashlib
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from src.contexts.ocr.application.ports import (
    JobWorkMessage,
    ObjectInfo,
    OutboxEvent,
    StoredObject,
    UploadTarget,
)
from src.contexts.ocr.application.exceptions import (
    ConcurrentJobUpdateError,
    DuplicateIdempotencyKeyError,
)
from src.contexts.ocr.domain.models import Job, JobEvent, Upload


class InMemoryUploadRepository:
    def __init__(self) -> None:
        self._items: dict[UUID, Upload] = {}
        self._lock = asyncio.Lock()

    async def add(self, upload: Upload) -> None:
        async with self._lock:
            if upload.id in self._items:
                raise ValueError("duplicate upload")
            self._items[upload.id] = copy.deepcopy(upload)

    async def get(self, upload_id: UUID) -> Upload | None:
        async with self._lock:
            item = self._items.get(upload_id)
            return copy.deepcopy(item) if item else None

    async def save(self, upload: Upload) -> None:
        async with self._lock:
            if upload.id not in self._items:
                raise ValueError("upload not found")
            self._items[upload.id] = copy.deepcopy(upload)


class InMemoryJobRepository:
    def __init__(self, events: Any | None = None) -> None:
        self._items: dict[UUID, Job] = {}
        self._lock = asyncio.Lock()
        self.events = events

    async def add(self, job: Job) -> None:
        async with self._lock:
            if job.id in self._items:
                raise ValueError("duplicate job")
            if job.idempotency_key and any(
                item.owner_id == job.owner_id
                and item.idempotency_key == job.idempotency_key
                for item in self._items.values()
            ):
                raise DuplicateIdempotencyKeyError("duplicate idempotency key")
            self._items[job.id] = copy.deepcopy(job)

    async def get(self, job_id: UUID) -> Job | None:
        async with self._lock:
            item = self._items.get(job_id)
            return copy.deepcopy(item) if item else None

    async def save(self, job: Job) -> None:
        async with self._lock:
            stored = self._items.get(job.id)
            if stored is None:
                raise ValueError("job not found")
            if stored.revision != job.revision:
                raise ConcurrentJobUpdateError("job was updated concurrently")
            job.revision += 1
            self._items[job.id] = copy.deepcopy(job)

    async def save_with_event(self, job: Job, event: JobEvent) -> JobEvent:
        if self.events is None:
            raise RuntimeError("job event repository is not configured")
        async with self._lock:
            stored = self._items.get(job.id)
            if stored is None:
                raise ValueError("job not found")
            if stored.revision != job.revision:
                raise ConcurrentJobUpdateError("job was updated concurrently")
            previous = copy.deepcopy(stored)
            candidate = copy.deepcopy(job)
            candidate.revision += 1
            self._items[job.id] = candidate
            try:
                saved_event = await self.events.append(event)
            except Exception:
                self._items[job.id] = previous
                raise
            job.revision = candidate.revision
            return saved_event

    async def find_by_idempotency_key(self, owner_id: str, key: str) -> Job | None:
        async with self._lock:
            for item in self._items.values():
                if item.owner_id == owner_id and item.idempotency_key == key:
                    return copy.deepcopy(item)
        return None

    async def list(self, owner_id: str, *, offset: int, limit: int) -> tuple[list[Job], int]:
        async with self._lock:
            items = sorted(
                (item for item in self._items.values() if item.owner_id == owner_id),
                key=lambda item: item.created_at,
                reverse=True,
            )
            return copy.deepcopy(items[offset : offset + limit]), len(items)

    async def add_with_outbox_and_event(
        self,
        job: Job,
        outbox_event: OutboxEvent,
        job_event: JobEvent,
        outbox: Any,
    ) -> JobEvent:
        await self.add(job)
        await outbox.add(outbox_event)
        if self.events is None:
            raise RuntimeError("job event repository is not configured")
        return await self.events.append(job_event)

    async def save_with_outbox_and_event(
        self,
        job: Job,
        outbox_event: OutboxEvent,
        job_event: JobEvent,
        outbox: Any,
    ) -> JobEvent:
        saved_event = await self.save_with_event(job, job_event)
        await outbox.add(outbox_event)
        return saved_event


class InMemoryJobEventRepository:
    def __init__(self) -> None:
        self._events: dict[UUID, list[JobEvent]] = defaultdict(list)
        self._condition = asyncio.Condition()

    async def append(self, event: JobEvent) -> JobEvent:
        async with self._condition:
            if event.event_type in {"job.cancelled", "job.failed", "job.succeeded"}:
                attempt = event.payload.get("attempt")
                existing = next(
                    (
                        item
                        for item in self._events[event.job_id]
                        if item.event_type == event.event_type
                        and item.payload.get("attempt") == attempt
                    ),
                    None,
                )
                if existing is not None:
                    return copy.deepcopy(existing)
            sequence = len(self._events[event.job_id]) + 1
            stored = event.with_sequence(sequence)
            self._events[event.job_id].append(copy.deepcopy(stored))
            self._condition.notify_all()
            return copy.deepcopy(stored)

    async def list_after(self, job_id: UUID, sequence: int) -> list[JobEvent]:
        async with self._condition:
            return copy.deepcopy(
                [event for event in self._events[job_id] if event.sequence > sequence]
            )

    async def wait_after(
        self, job_id: UUID, sequence: int, timeout_seconds: float
    ) -> list[JobEvent]:
        async with self._condition:
            existing = [event for event in self._events[job_id] if event.sequence > sequence]
            if existing:
                return copy.deepcopy(existing)
            try:
                await asyncio.wait_for(
                    self._condition.wait_for(
                        lambda: any(
                            event.sequence > sequence for event in self._events[job_id]
                        )
                    ),
                    timeout_seconds,
                )
            except TimeoutError:
                return []
            return copy.deepcopy(
                [event for event in self._events[job_id] if event.sequence > sequence]
            )


class InMemoryOutboxRepository:
    def __init__(self) -> None:
        self._items: dict[UUID, OutboxEvent] = {}
        self._lock = asyncio.Lock()

    async def add(self, event: OutboxEvent) -> None:
        async with self._lock:
            self._items[event.id] = copy.deepcopy(event)

    async def pending(self, *, limit: int = 100) -> list[OutboxEvent]:
        async with self._lock:
            items = sorted(
                (item for item in self._items.values() if item.published_at is None),
                key=lambda item: item.created_at,
            )
            return copy.deepcopy(items[:limit])

    async def mark_published(self, event_id: UUID) -> None:
        async with self._lock:
            self._items[event_id].published_at = datetime.now(UTC)


class InMemoryObjectStorage:
    def __init__(self) -> None:
        self._objects: dict[str, tuple[bytes, str, str]] = {}
        self._lock = asyncio.Lock()

    async def create_upload_target(
        self,
        object_key: str,
        *,
        content_type: str,
        size_bytes: int,
        sha256: str,
    ) -> UploadTarget:
        return UploadTarget(
            url=f"memory://{object_key}",
            headers={
                "Content-Type": content_type,
                "X-Content-SHA256": sha256,
            },
        )

    async def stat(self, object_key: str) -> ObjectInfo | None:
        async with self._lock:
            item = self._objects.get(object_key)
            if item is None:
                return None
            data, content_type, digest = item
            return ObjectInfo(
                object_key=object_key,
                size_bytes=len(data),
                sha256=digest,
                content_type=content_type,
            )

    async def complete_upload(
        self,
        object_key: str,
        *,
        upload_id: str | None,
        parts: list[tuple[int, str]],
    ) -> None:
        return None

    async def get_bytes(self, object_key: str) -> bytes:
        async with self._lock:
            try:
                return bytes(self._objects[object_key][0])
            except KeyError as exc:
                raise FileNotFoundError(object_key) from exc

    async def put_bytes(
        self, object_key: str, data: bytes, *, content_type: str
    ) -> StoredObject:
        digest = hashlib.sha256(data).hexdigest()
        async with self._lock:
            self._objects[object_key] = (bytes(data), content_type, digest)
        return StoredObject(
            object_key=object_key,
            size_bytes=len(data),
            sha256=digest,
            content_type=content_type,
        )

    async def delete_object(self, object_key: str) -> None:
        async with self._lock:
            self._objects.pop(object_key, None)

    async def abort_multipart_upload(
        self, object_key: str, upload_id: str
    ) -> None:
        return None

    async def create_download_url(self, object_key: str) -> str:
        if await self.stat(object_key) is None:
            raise FileNotFoundError(object_key)
        return f"memory://{object_key}?download=1"


class InMemoryQueuePublisher:
    def __init__(self) -> None:
        self.messages: list[JobWorkMessage] = []

    async def publish(self, message: JobWorkMessage) -> None:
        self.messages.append(copy.deepcopy(message))


class InMemoryStructuredLogger:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    async def info(self, event: str, **fields: Any) -> None:
        self.records.append({"level": "info", "event": event, **fields})

    async def error(self, event: str, **fields: Any) -> None:
        self.records.append({"level": "error", "event": event, **fields})

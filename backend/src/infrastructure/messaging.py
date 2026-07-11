from __future__ import annotations

import json
from typing import Any, Protocol
from uuid import UUID

from src.contexts.ocr.application.exceptions import (
    DatabaseUnavailableError,
    DependencyError,
    QueueUnavailableError,
)
from src.contexts.ocr.application.ports import (
    JobWorkMessage,
    OutboxRepository,
    QueuePublisher,
)


class KafkaProducer(Protocol):
    async def send_and_wait(
        self, topic: str, value: bytes, *, key: bytes | None = None
    ) -> Any: ...


class KafkaJobPublisher:
    def __init__(self, *, producer: KafkaProducer, topic: str) -> None:
        self.producer = producer
        self.topic = topic

    async def publish(self, message: JobWorkMessage) -> None:
        payload = json.dumps(
            {
                "schema_version": message.schema_version,
                "job_id": str(message.job_id),
                "attempt": message.attempt,
                "request_id": message.request_id,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            await self.producer.send_and_wait(
                self.topic, value=payload, key=str(message.job_id).encode("ascii")
            )
        except DependencyError:
            raise
        except Exception as exc:
            raise QueueUnavailableError("Kafka publish failed") from exc


class OutboxDispatcher:
    def __init__(self, *, outbox: OutboxRepository, publisher: QueuePublisher) -> None:
        self.outbox = outbox
        self.publisher = publisher

    async def dispatch_once(self, *, limit: int = 100) -> int:
        published = 0
        try:
            events = await self.outbox.pending(limit=limit)
        except DependencyError:
            raise
        except Exception as exc:
            raise DatabaseUnavailableError("outbox read failed") from exc
        for event in events:
            if event.event_type != "ocr.job.requested.v1":
                continue
            await self.publisher.publish(
                JobWorkMessage(
                    job_id=UUID(str(event.payload["job_id"])),
                    attempt=int(event.payload["attempt"]),
                    request_id=str(event.payload["request_id"]),
                    schema_version=int(event.payload.get("schema_version", 1)),
                )
            )
            try:
                await self.outbox.mark_published(event.id)
            except DependencyError:
                raise
            except Exception as exc:
                raise DatabaseUnavailableError("outbox update failed") from exc
            published += 1
        return published


def decode_job_message(value: bytes) -> JobWorkMessage:
    payload = json.loads(value)
    if not isinstance(payload, dict):
        raise ValueError("job message must be an object")
    return JobWorkMessage(
        job_id=UUID(str(payload["job_id"])),
        attempt=int(payload["attempt"]),
        request_id=str(payload["request_id"]),
        schema_version=int(payload.get("schema_version", 1)),
    )

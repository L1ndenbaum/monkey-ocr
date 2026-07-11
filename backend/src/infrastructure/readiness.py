from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Protocol


SANDBOX_HEARTBEAT_FILENAME = ".heartbeat.json"


class PostgresPool(Protocol):
    async def fetchval(self, query: str, *args: object) -> Any: ...


class KafkaClusterMetadata(Protocol):
    def partitions_for_topic(self, topic: str) -> set[int] | None: ...


class KafkaClient(Protocol):
    async def fetch_all_metadata(self) -> KafkaClusterMetadata: ...


class KafkaMetadataProducer(Protocol):
    client: KafkaClient


class ReadableObjectStorage(Protocol):
    async def stat(self, object_key: str) -> object | None: ...


class HTTPResponse(Protocol):
    status_code: int


class HTTPClient(Protocol):
    async def get(self, url: str, **kwargs: Any) -> HTTPResponse: ...


class PostgresReadinessProbe:
    def __init__(self, pool: PostgresPool) -> None:
        self._pool = pool

    async def __call__(self) -> None:
        if await self._pool.fetchval("SELECT 1") != 1:
            raise RuntimeError("postgres readiness query failed")


class ObjectStorageReadinessProbe:
    """Uses a non-mutating stat to verify both the service and backing bucket."""

    _PROBE_KEY = ".monkeyocr-readiness-probe"

    def __init__(self, storage: ReadableObjectStorage) -> None:
        self._storage = storage

    async def __call__(self) -> None:
        await self._storage.stat(self._PROBE_KEY)


class KafkaReadinessProbe:
    def __init__(self, producer: KafkaMetadataProducer, topic: str) -> None:
        self._producer = producer
        self._topic = topic

    async def __call__(self) -> None:
        metadata = await self._producer.client.fetch_all_metadata()
        partitions = metadata.partitions_for_topic(self._topic)
        if not partitions:
            raise RuntimeError("Kafka topic metadata is unavailable")


class HTTPStatusReadinessProbe:
    def __init__(self, client: HTTPClient, url: str) -> None:
        self._client = client
        self._url = url

    async def __call__(self) -> None:
        response = await self._client.get(self._url)
        if response.status_code != 200:
            raise RuntimeError("dependency readiness endpoint is unavailable")


class SandboxHeartbeatReadinessProbe:
    def __init__(self, exchange_dir: str, *, max_age_seconds: float = 5.0) -> None:
        if max_age_seconds <= 0:
            raise ValueError("sandbox heartbeat max age must be positive")
        self._path = Path(exchange_dir) / SANDBOX_HEARTBEAT_FILENAME
        self._max_age_seconds = max_age_seconds

    async def __call__(self) -> None:
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        if payload.get("status") != "ok":
            raise RuntimeError("sandbox heartbeat is invalid")
        updated_at = float(payload["updated_at_unix"])
        age = time.time() - updated_at
        if age < -1.0 or age > self._max_age_seconds:
            raise RuntimeError("sandbox heartbeat is stale")


__all__ = [
    "HTTPStatusReadinessProbe",
    "KafkaReadinessProbe",
    "ObjectStorageReadinessProbe",
    "PostgresReadinessProbe",
    "SANDBOX_HEARTBEAT_FILENAME",
    "SandboxHeartbeatReadinessProbe",
]

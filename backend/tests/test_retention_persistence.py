from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from uuid6 import uuid7

from src.contexts.ocr.domain.models import Job, JobEvent, JobState
from src.infrastructure.persistence import (
    AsyncpgJobEventRepository,
    AsyncpgJobRepository,
    AsyncpgRetentionRepository,
)


class AsyncContext:
    def __init__(self, value: Any = None) -> None:
        self.value = value

    async def __aenter__(self) -> Any:
        return self.value or self

    async def __aexit__(self, *_: object) -> None:
        return None


class RetentionConnectionStub:
    def __init__(self) -> None:
        self.job_id = uuid7()
        self.upload_id = uuid7()
        self.queries: list[str] = []

    def transaction(self) -> AsyncContext:
        return AsyncContext()

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.queries.append(query)
        if "RETURNING job.id" in query:
            return [{"id": self.job_id, "retention_claim_token": args[2]}]
        if "array_agg" in query:
            return [
                {
                    "job_id": self.job_id,
                    "object_keys": ["jobs/id/page-1.json", "jobs/id/result.md"],
                }
            ]
        if "RETURNING upload.id" in query:
            return [
                {
                    "id": self.upload_id,
                    "retention_claim_token": args[2],
                    "object_key": "uploads/id/source",
                    "multipart_upload_id": "multipart-id",
                }
            ]
        raise AssertionError(f"unexpected query: {query}")

    async def fetchval(self, query: str, *_: Any) -> int:
        self.queries.append(query)
        return 1

    async def execute(self, query: str, *_: Any) -> str:
        self.queries.append(query)
        if "DELETE FROM ocr_jobs" in query:
            return "DELETE 1"
        return "DELETE 1"


class PoolStub:
    def __init__(self, connection: RetentionConnectionStub) -> None:
        self.connection = connection

    def acquire(self) -> AsyncContext:
        return AsyncContext(self.connection)


class JobSaveConnectionStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    async def execute(self, query: str, *args: Any) -> str:
        self.calls.append((query, args))
        return "UPDATE 1"

    async def fetchval(self, query: str, *args: Any) -> int:
        self.calls.append((query, args))
        return 1


class EventConnectionStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def transaction(self) -> AsyncContext:
        return AsyncContext()

    async def execute(self, query: str, *args: Any) -> str:
        self.calls.append((query, args))
        return "INSERT 0 1"

    async def fetchval(self, query: str, *args: Any) -> int | None:
        self.calls.append((query, args))
        if "SELECT sequence FROM job_events" in query:
            return None
        if "COALESCE(max(sequence),0)+1" in query:
            return 1
        raise AssertionError(f"unexpected query: {query}")


@pytest.mark.asyncio
async def test_retention_repository_claims_job_and_unreferenced_upload() -> None:
    connection = RetentionConnectionStub()
    repository = AsyncpgRetentionRepository(PoolStub(connection))

    candidates = await repository.claim_expired(
        now=datetime(2026, 7, 11, tzinfo=UTC),
        limit=2,
        lease_seconds=60,
    )

    assert [(item.aggregate_kind, item.aggregate_id) for item in candidates] == [
        ("job", connection.job_id),
        ("upload", connection.upload_id),
    ]
    assert candidates[0].object_keys == (
        "jobs/id/page-1.json",
        "jobs/id/result.md",
    )
    assert candidates[1].object_keys == ("uploads/id/source",)
    assert candidates[1].multipart_upload_id == "multipart-id"
    assert "status IN ('succeeded','failed','cancelled')" in connection.queries[0]
    assert "refs.object_key LIKE ('jobs/' || refs.job_id::text || '/%')" in connection.queries[1]
    assert "NOT EXISTS" in connection.queries[-1]


@pytest.mark.asyncio
async def test_retention_repository_deletes_outbox_with_claimed_job() -> None:
    connection = RetentionConnectionStub()
    repository = AsyncpgRetentionRepository(PoolStub(connection))
    candidate = (
        await repository.claim_expired(
            now=datetime(2026, 7, 11, tzinfo=UTC),
            limit=1,
            lease_seconds=60,
        )
    )[0]

    assert await repository.complete(candidate) is True
    assert any("DELETE FROM outbox_events" in query for query in connection.queries)
    assert any("DELETE FROM ocr_jobs" in query for query in connection.queries)


@pytest.mark.asyncio
async def test_terminal_job_retention_starts_at_completion() -> None:
    completed_at = datetime(2026, 7, 11, tzinfo=UTC)
    job = Job(owner_id=str(uuid7()), upload_id=uuid7(), request_id="request")
    job.state = JobState.FAILED
    job.completed_at = completed_at
    connection = JobSaveConnectionStub()
    repository = AsyncpgJobRepository(
        pool=None,
        topic="monkeyocr.events.jobs",
        retention_days=30,
    )

    await repository._save_job(connection, job)

    job_update_args = connection.calls[0][1]
    assert job_update_args[-2] == completed_at + timedelta(days=30)
    assert job.revision == 1


@pytest.mark.asyncio
async def test_job_event_persists_dependency_internal_code() -> None:
    connection = EventConnectionStub()
    repository = AsyncpgJobEventRepository(PoolStub(connection))
    event = JobEvent(
        job_id=uuid7(),
        event_type="job.failed",
        state=JobState.FAILED,
        progress=0.5,
        request_id="request",
        payload={"attempt": 1, "internal_code": 50002},
    )

    stored = await repository.append(event)

    insert = next(
        args
        for query, args in connection.calls
        if "INSERT INTO job_events" in query
    )
    assert insert[3] == 50002
    assert stored.sequence == 1

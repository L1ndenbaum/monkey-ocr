from __future__ import annotations

from datetime import UTC, datetime

import pytest
from uuid6 import uuid7

from src.contexts.ocr.application.ports import RetentionCandidate
from src.contexts.ocr.application.retention import RetentionCleanupService
from src.infrastructure.memory import InMemoryStructuredLogger


class RetentionRepositoryStub:
    def __init__(self, candidates: list[RetentionCandidate]) -> None:
        self.candidates = candidates
        self.completed: list[RetentionCandidate] = []
        self.deferred: list[RetentionCandidate] = []

    async def claim_expired(self, **_: object) -> list[RetentionCandidate]:
        return list(self.candidates)

    async def complete(self, candidate: RetentionCandidate) -> bool:
        self.completed.append(candidate)
        return True

    async def defer(self, candidate: RetentionCandidate, **_: object) -> None:
        self.deferred.append(candidate)


class DeleteStorageStub:
    def __init__(self, *, failure_key: str | None = None) -> None:
        self.failure_key = failure_key
        self.deleted: list[str] = []
        self.aborted: list[tuple[str, str]] = []

    async def delete_object(self, object_key: str) -> None:
        if object_key == self.failure_key:
            raise RuntimeError("storage unavailable")
        self.deleted.append(object_key)

    async def abort_multipart_upload(
        self, object_key: str, upload_id: str
    ) -> None:
        self.aborted.append((object_key, upload_id))


def candidate(*object_keys: str) -> RetentionCandidate:
    return RetentionCandidate(
        aggregate_kind="job",
        aggregate_id=uuid7(),
        claim_token=uuid7(),
        object_keys=object_keys,
    )


@pytest.mark.asyncio
async def test_retention_cleanup_deletes_unique_objects_before_database_row() -> None:
    expired = candidate("jobs/1/page.json", "jobs/1/page.json", "jobs/1/result.md")
    repository = RetentionRepositoryStub([expired])
    storage = DeleteStorageStub()
    logger = InMemoryStructuredLogger()
    service = RetentionCleanupService(
        repository=repository,
        storage=storage,  # type: ignore[arg-type]
        logger=logger,
        delete_concurrency=2,
    )

    result = await service.run_batch(
        limit=10,
        lease_seconds=60,
        now=datetime(2026, 7, 11, tzinfo=UTC),
    )

    assert result.claimed == 1
    assert result.completed == 1
    assert result.deleted_objects == 2
    assert repository.completed == [expired]
    assert repository.deferred == []
    assert sorted(storage.deleted) == ["jobs/1/page.json", "jobs/1/result.md"]


@pytest.mark.asyncio
async def test_retention_cleanup_defers_claim_when_object_deletion_fails() -> None:
    expired = candidate("jobs/1/page.json", "jobs/1/result.md")
    repository = RetentionRepositoryStub([expired])
    storage = DeleteStorageStub(failure_key="jobs/1/result.md")
    logger = InMemoryStructuredLogger()
    service = RetentionCleanupService(
        repository=repository,
        storage=storage,  # type: ignore[arg-type]
        logger=logger,
        retry_delay_seconds=5,
    )

    result = await service.run_batch(limit=10, lease_seconds=60)

    assert result.completed == 0
    assert result.deferred == 1
    assert repository.completed == []
    assert repository.deferred == [expired]
    assert logger.records[-1]["event"] == "retention_candidate_failed"
    assert "object_keys" not in logger.records[-1]


@pytest.mark.asyncio
async def test_retention_cleanup_aborts_expired_multipart_upload() -> None:
    expired = RetentionCandidate(
        aggregate_kind="upload",
        aggregate_id=uuid7(),
        claim_token=uuid7(),
        object_keys=("uploads/id/source",),
        multipart_upload_id="multipart-id",
    )
    repository = RetentionRepositoryStub([expired])
    storage = DeleteStorageStub()
    service = RetentionCleanupService(
        repository=repository,
        storage=storage,  # type: ignore[arg-type]
        logger=InMemoryStructuredLogger(),
    )

    result = await service.run_batch(limit=10, lease_seconds=60)

    assert result.completed == 1
    assert storage.aborted == [("uploads/id/source", "multipart-id")]
    assert storage.deleted == ["uploads/id/source"]

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .ports import (
    ObjectStorage,
    RetentionCandidate,
    RetentionRepository,
    StructuredLogger,
)


@dataclass(slots=True, frozen=True)
class RetentionBatchResult:
    claimed: int
    completed: int
    deferred: int
    deleted_objects: int


class RetentionCleanupService:
    """Deletes expired OCR data while keeping database claims recoverable."""

    def __init__(
        self,
        *,
        repository: RetentionRepository,
        storage: ObjectStorage,
        logger: StructuredLogger,
        delete_concurrency: int = 8,
        retry_delay_seconds: int = 30,
    ) -> None:
        if delete_concurrency < 1:
            raise ValueError("delete_concurrency must be positive")
        if retry_delay_seconds < 1:
            raise ValueError("retry_delay_seconds must be positive")
        self.repository = repository
        self.storage = storage
        self.logger = logger
        self.delete_concurrency = delete_concurrency
        self.retry_delay_seconds = retry_delay_seconds

    async def run_batch(
        self,
        *,
        limit: int,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> RetentionBatchResult:
        if limit < 1:
            raise ValueError("limit must be positive")
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        current_time = now or datetime.now(UTC)
        candidates = await self.repository.claim_expired(
            now=current_time,
            limit=limit,
            lease_seconds=lease_seconds,
        )
        completed = 0
        deferred = 0
        deleted_objects = 0

        for candidate in candidates:
            try:
                deleted_objects += await self._delete_objects(candidate)
                if await self.repository.complete(candidate):
                    completed += 1
                    await self.logger.info(
                        "retention_candidate_deleted",
                        aggregate_kind=candidate.aggregate_kind,
                        aggregate_id=str(candidate.aggregate_id),
                        object_count=len(candidate.object_keys),
                    )
                else:
                    deferred += 1
                    await self.logger.error(
                        "retention_candidate_claim_lost",
                        aggregate_kind=candidate.aggregate_kind,
                        aggregate_id=str(candidate.aggregate_id),
                    )
            except Exception as exc:
                deferred += 1
                retry_at = datetime.now(UTC) + timedelta(
                    seconds=self.retry_delay_seconds
                )
                try:
                    await self.repository.defer(candidate, retry_at=retry_at)
                except Exception as defer_exc:
                    await self.logger.error(
                        "retention_candidate_defer_failed",
                        aggregate_kind=candidate.aggregate_kind,
                        aggregate_id=str(candidate.aggregate_id),
                        error_type=type(defer_exc).__name__,
                    )
                await self.logger.error(
                    "retention_candidate_failed",
                    aggregate_kind=candidate.aggregate_kind,
                    aggregate_id=str(candidate.aggregate_id),
                    error_type=type(exc).__name__,
                )

        return RetentionBatchResult(
            claimed=len(candidates),
            completed=completed,
            deferred=deferred,
            deleted_objects=deleted_objects,
        )

    async def _delete_objects(self, candidate: RetentionCandidate) -> int:
        object_keys = tuple(dict.fromkeys(key for key in candidate.object_keys if key))
        if candidate.multipart_upload_id:
            if len(object_keys) != 1:
                raise ValueError("multipart upload cleanup requires one source object")
            await self.storage.abort_multipart_upload(
                object_keys[0], candidate.multipart_upload_id
            )
        semaphore = asyncio.Semaphore(self.delete_concurrency)

        async def delete_one(object_key: str) -> None:
            async with semaphore:
                await self.storage.delete_object(object_key)

        results = await asyncio.gather(
            *(delete_one(object_key) for object_key in object_keys),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException):
                raise result
        return len(object_keys)

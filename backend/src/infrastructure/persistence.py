from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from uuid6 import uuid7

from src.contexts.ocr.application.ports import OutboxEvent, RetentionCandidate
from src.contexts.ocr.application.exceptions import (
    ConcurrentJobUpdateError,
    DuplicateIdempotencyKeyError,
)
from src.contexts.ocr.domain.models import (
    Artifact,
    ArtifactKind,
    Job,
    JobEvent,
    JobState,
    Page,
    PageState,
    Upload,
    UploadState,
)


def _decode_json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


class AsyncpgUploadRepository:
    def __init__(self, pool: Any, *, upload_ttl_seconds: int = 3600) -> None:
        self.pool = pool
        self.upload_ttl_seconds = upload_ttl_seconds

    async def add(self, upload: Upload) -> None:
        async with self.pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO upload_sessions (
                    id, api_key_id, object_key, filename, declared_content_type,
                    expected_sha256, expected_size, multipart_upload_id, status,
                    expires_at, created_at, updated_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$11)
                """,
                upload.id,
                UUID(upload.owner_id),
                upload.object_key,
                upload.filename,
                upload.content_type,
                upload.sha256,
                upload.size_bytes,
                upload.multipart_upload_id,
                self._db_status(upload.state),
                upload.created_at + timedelta(seconds=self.upload_ttl_seconds),
                upload.created_at,
            )

    async def get(self, upload_id: UUID) -> Upload | None:
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT * FROM upload_sessions
                WHERE id=$1 AND retention_claim_token IS NULL
                """,
                upload_id,
            )
        return self._from_row(row) if row else None

    async def save(self, upload: Upload) -> None:
        async with self.pool.acquire() as connection:
            status = await connection.execute(
                """
                UPDATE upload_sessions SET
                    status=$2, detected_content_type=$3,
                    verified_sha256=CASE WHEN $2='completed' THEN expected_sha256 ELSE verified_sha256 END,
                    verified_size=CASE WHEN $2='completed' THEN expected_size ELSE verified_size END,
                    completed_at=$4, updated_at=$5
                WHERE id=$1 AND retention_claim_token IS NULL
                """,
                upload.id,
                self._db_status(upload.state),
                upload.detected_content_type,
                upload.completed_at,
                datetime.now(UTC),
            )
        if status != "UPDATE 1":
            raise RuntimeError("upload is unavailable for retention cleanup")

    @staticmethod
    def _db_status(state: UploadState) -> str:
        return "pending" if state is UploadState.UPLOADING else str(state)

    @staticmethod
    def _from_row(row: Any) -> Upload:
        status = "uploading" if row["status"] == "pending" else row["status"]
        return Upload(
            id=row["id"],
            owner_id=str(row["api_key_id"]),
            filename=row["filename"],
            size_bytes=row["expected_size"],
            content_type=row["declared_content_type"],
            sha256=row["expected_sha256"],
            object_key=row["object_key"],
            state=UploadState(status),
            created_at=row["created_at"],
            completed_at=row["completed_at"],
            detected_content_type=row["detected_content_type"],
            multipart_upload_id=row["multipart_upload_id"],
        )


class AsyncpgJobRepository:
    def __init__(self, pool: Any, *, topic: str, retention_days: int = 30) -> None:
        self.pool = pool
        self.topic = topic
        self.retention_days = retention_days

    async def add(self, job: Job) -> None:
        async with self.pool.acquire() as connection, connection.transaction():
            await self._insert_job(connection, job)

    async def add_with_outbox_and_event(
        self,
        job: Job,
        outbox_event: OutboxEvent,
        job_event: JobEvent,
        outbox: Any,
    ) -> JobEvent:
        try:
            async with self.pool.acquire() as connection, connection.transaction():
                await self._insert_job(connection, job)
                await self._insert_outbox(connection, outbox_event)
                return await AsyncpgJobEventRepository.append_with_connection(
                    connection, job_event
                )
        except Exception as exc:
            if (
                getattr(exc, "sqlstate", None) == "23505"
                and getattr(exc, "constraint_name", None)
                == "uq_ocr_jobs_api_key_idempotency"
            ):
                raise DuplicateIdempotencyKeyError(
                    "duplicate idempotency key"
                ) from exc
            raise

    async def get(self, job_id: UUID) -> Job | None:
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT j.*, a.started_at AS attempt_started_at,
                       a.engine_name AS attempt_engine_name,
                       a.engine_version AS attempt_engine_version,
                       a.model_name AS attempt_model_name
                FROM ocr_jobs j
                LEFT JOIN ocr_job_attempts a
                  ON a.job_id=j.id AND a.attempt=j.current_attempt
                WHERE j.id=$1 AND j.retention_claim_token IS NULL
                """,
                job_id,
            )
            if row is None:
                return None
            pages = await connection.fetch(
                """
                SELECT * FROM ocr_job_pages
                WHERE job_id=$1 AND attempt=$2 ORDER BY page_number
                """,
                job_id,
                row["current_attempt"],
            )
            artifacts = await connection.fetch(
                """
                SELECT * FROM ocr_artifacts
                WHERE job_id=$1 AND attempt=$2 ORDER BY page_number NULLS FIRST, kind
                """,
                job_id,
                row["current_attempt"],
            )
        return self._from_rows(row, pages, artifacts)

    async def save(self, job: Job) -> None:
        async with self.pool.acquire() as connection, connection.transaction():
            await self._save_job(connection, job)

    async def save_with_event(self, job: Job, event: JobEvent) -> JobEvent:
        async with self.pool.acquire() as connection, connection.transaction():
            await self._save_job(connection, job)
            return await AsyncpgJobEventRepository.append_with_connection(
                connection, event
            )

    async def save_with_outbox_and_event(
        self,
        job: Job,
        outbox_event: OutboxEvent,
        job_event: JobEvent,
        outbox: Any,
    ) -> JobEvent:
        async with self.pool.acquire() as connection, connection.transaction():
            await self._save_job(connection, job)
            await self._insert_outbox(connection, outbox_event)
            return await AsyncpgJobEventRepository.append_with_connection(
                connection, job_event
            )

    async def find_by_idempotency_key(self, owner_id: str, key: str) -> Job | None:
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT id FROM ocr_jobs WHERE api_key_id=$1 AND idempotency_key=$2",
                UUID(owner_id),
                key,
            )
        return await self.get(row["id"]) if row else None

    async def list(self, owner_id: str, *, offset: int, limit: int) -> tuple[list[Job], int]:
        async with self.pool.acquire() as connection:
            ids = await connection.fetch(
                """
                SELECT id FROM ocr_jobs
                WHERE api_key_id=$1 AND retention_claim_token IS NULL
                ORDER BY created_at DESC OFFSET $2 LIMIT $3
                """,
                UUID(owner_id),
                offset,
                limit,
            )
            total = await connection.fetchval(
                """
                SELECT count(*) FROM ocr_jobs
                WHERE api_key_id=$1 AND retention_claim_token IS NULL
                """,
                UUID(owner_id),
            )
        jobs = [job for row in ids if (job := await self.get(row["id"])) is not None]
        return jobs, int(total)

    async def _insert_job(self, connection: Any, job: Job) -> None:
        await connection.execute(
            """
            INSERT INTO ocr_jobs (
                id, api_key_id, upload_id, idempotency_key, request_id, status,
                current_attempt, total_pages, completed_pages, progress_percent,
                options, expires_at, last_error_reason, created_at, updated_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb,$12,$13,$14,$14)
            """,
            job.id,
            UUID(job.owner_id),
            job.upload_id,
            job.idempotency_key,
            job.request_id,
            str(job.state),
            job.attempt,
            job.total_pages or None,
            job.completed_pages,
            Decimal(str(job.progress * 100)),
            _json(job.options),
            job.created_at + timedelta(days=self.retention_days),
            job.error_reason,
            job.created_at,
        )
        await self._upsert_attempt(connection, job)

    async def _save_job(self, connection: Any, job: Job) -> None:
        cancel_requested_at = (
            datetime.now(UTC)
            if job.state in {JobState.CANCEL_REQUESTED, JobState.CANCELLED}
            else None
        )
        revision = await connection.fetchval(
            """
            UPDATE ocr_jobs SET
                request_id=$2, status=$3, current_attempt=$4, total_pages=$5,
                completed_pages=$6, progress_percent=$7, options=$8::jsonb,
                cancel_requested_at=COALESCE(cancel_requested_at,$9), finished_at=$10,
                last_internal_code=$11, last_error_reason=$12, updated_at=$13,
                expires_at=$14, revision=revision+1
            WHERE id=$1 AND retention_claim_token IS NULL AND revision=$15
            RETURNING revision
            """,
            job.id,
            job.request_id,
            str(job.state),
            job.attempt,
            job.total_pages or None,
            job.completed_pages,
            Decimal(str(job.progress * 100)),
            _json(job.options),
            cancel_requested_at,
            job.completed_at,
            job.internal_code,
            job.error_reason,
            job.updated_at,
            (job.completed_at or job.created_at) + timedelta(days=self.retention_days),
            job.revision,
        )
        if revision is None:
            raise ConcurrentJobUpdateError("job was updated concurrently or retained")
        job.revision = int(revision)
        await self._upsert_attempt(connection, job)
        for page in job.pages:
            await connection.execute(
                """
                INSERT INTO ocr_job_pages (
                    job_id, attempt, page_number, status, retry_count,
                    source_object_key, result_object_key, visualization_object_key,
                    result_sha256, last_internal_code, last_error_reason
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                ON CONFLICT (job_id,attempt,page_number) DO UPDATE SET
                    status=EXCLUDED.status, retry_count=EXCLUDED.retry_count,
                    source_object_key=EXCLUDED.source_object_key,
                    result_object_key=EXCLUDED.result_object_key,
                    visualization_object_key=EXCLUDED.visualization_object_key,
                    result_sha256=EXCLUDED.result_sha256,
                    last_internal_code=EXCLUDED.last_internal_code,
                    last_error_reason=EXCLUDED.last_error_reason,
                    updated_at=now()
                """,
                job.id,
                job.attempt,
                page.page_number,
                str(page.state),
                page.processing_attempts,
                page.input_object_key,
                page.result_object_key,
                page.visualization_object_key,
                page.result_sha256,
                page.internal_code,
                page.error_reason,
            )
        if job.artifacts:
            await connection.execute(
                "DELETE FROM ocr_artifacts WHERE job_id=$1 AND attempt=$2",
                job.id,
                job.attempt,
            )
            for artifact in job.artifacts:
                await connection.execute(
                    """
                    INSERT INTO ocr_artifacts (
                        job_id,attempt,page_number,kind,object_key,content_type,size_bytes,sha256
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                    """,
                    job.id,
                    job.attempt,
                    artifact.page_number,
                    str(artifact.kind),
                    artifact.object_key,
                    artifact.content_type,
                    artifact.size_bytes,
                    artifact.sha256,
                )

    async def _upsert_attempt(self, connection: Any, job: Job) -> None:
        await connection.execute(
            """
            INSERT INTO ocr_job_attempts (
                job_id,attempt,status,started_at,finished_at,
                engine_name,engine_version,model_name
            )
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
            ON CONFLICT (job_id,attempt) DO UPDATE SET
                status=EXCLUDED.status,
                started_at=COALESCE(ocr_job_attempts.started_at,EXCLUDED.started_at),
                finished_at=EXCLUDED.finished_at,
                engine_name=COALESCE(EXCLUDED.engine_name,ocr_job_attempts.engine_name),
                engine_version=COALESCE(EXCLUDED.engine_version,ocr_job_attempts.engine_version),
                model_name=COALESCE(EXCLUDED.model_name,ocr_job_attempts.model_name),
                updated_at=now()
            """,
            job.id,
            job.attempt,
            str(job.state),
            job.started_at,
            job.completed_at,
            job.engine_name,
            job.engine_version,
            job.model_name,
        )

    async def _insert_outbox(self, connection: Any, event: OutboxEvent) -> None:
        await connection.execute(
            """
            INSERT INTO outbox_events (
                id,aggregate_type,aggregate_id,event_type,topic,partition_key,
                schema_version,payload,created_at
            ) VALUES ($1,'ocr_job',$2,$3,$4,$5,1,$6::jsonb,$7)
            """,
            event.id,
            event.aggregate_id,
            event.event_type,
            self.topic,
            str(event.aggregate_id),
            _json(event.payload),
            event.created_at,
        )

    @staticmethod
    def _from_rows(row: Any, pages: list[Any], artifacts: list[Any]) -> Job:
        return Job(
            id=row["id"],
            owner_id=str(row["api_key_id"]),
            upload_id=row["upload_id"],
            request_id=row["request_id"],
            options=_decode_json(row["options"]) or {},
            state=JobState(row["status"]),
            attempt=row["current_attempt"],
            revision=row["revision"],
            pages=[
                Page(
                    page_number=item["page_number"],
                    input_object_key=item["source_object_key"],
                    state=PageState(item["status"]),
                    processing_attempts=item["retry_count"],
                    result_object_key=item["result_object_key"],
                    result_sha256=item["result_sha256"],
                    visualization_object_key=item["visualization_object_key"],
                    internal_code=item["last_internal_code"],
                    error_reason=item["last_error_reason"],
                )
                for item in pages
            ],
            artifacts=[
                Artifact(
                    kind=ArtifactKind(item["kind"]),
                    object_key=item["object_key"],
                    sha256=item["sha256"],
                    size_bytes=item["size_bytes"],
                    content_type=item["content_type"],
                    page_number=item["page_number"],
                )
                for item in artifacts
            ],
            idempotency_key=row["idempotency_key"],
            engine_name=row["attempt_engine_name"],
            engine_version=row["attempt_engine_version"],
            model_name=row["attempt_model_name"],
            internal_code=row["last_internal_code"],
            error_reason=row["last_error_reason"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            started_at=row["attempt_started_at"],
            completed_at=row["finished_at"],
        )


class AsyncpgRetentionRepository:
    """Claims expired rows before external objects are removed.

    A claim remains attached to the row after a failed or interrupted deletion,
    keeping partially deleted jobs out of public reads. Once its lease expires,
    another cleanup process can safely reclaim it because object deletion is
    idempotent.
    """

    def __init__(self, pool: Any) -> None:
        self.pool = pool

    async def claim_expired(
        self,
        *,
        now: datetime,
        limit: int,
        lease_seconds: int,
    ) -> list[RetentionCandidate]:
        if limit < 1:
            return []
        lease_expires_at = now + timedelta(seconds=lease_seconds)
        candidates: list[RetentionCandidate] = []

        async with self.pool.acquire() as connection, connection.transaction():
            job_claim_token = uuid7()
            job_rows = await connection.fetch(
                """
                WITH candidates AS (
                    SELECT id
                    FROM ocr_jobs
                    WHERE status IN ('succeeded','failed','cancelled')
                      AND expires_at <= $1
                      AND (
                          retention_claim_token IS NULL
                          OR retention_lease_expires_at <= $1
                      )
                    ORDER BY expires_at, id
                    FOR UPDATE SKIP LOCKED
                    LIMIT $2
                )
                UPDATE ocr_jobs AS job
                SET retention_claim_token=$3,
                    retention_lease_expires_at=$4,
                    updated_at=now()
                FROM candidates
                WHERE job.id=candidates.id
                RETURNING job.id, job.retention_claim_token
                """,
                now,
                limit,
                job_claim_token,
                lease_expires_at,
            )
            job_ids = [row["id"] for row in job_rows]
            object_keys_by_job: dict[UUID, tuple[str, ...]] = {}
            if job_ids:
                object_rows = await connection.fetch(
                    """
                    SELECT refs.job_id,
                           array_agg(refs.object_key ORDER BY refs.object_key) AS object_keys
                    FROM (
                        SELECT job_id, source_object_key AS object_key
                        FROM ocr_job_pages WHERE job_id=ANY($1::uuid[])
                        UNION
                        SELECT job_id, result_object_key AS object_key
                        FROM ocr_job_pages WHERE job_id=ANY($1::uuid[])
                        UNION
                        SELECT job_id, visualization_object_key AS object_key
                        FROM ocr_job_pages WHERE job_id=ANY($1::uuid[])
                        UNION
                        SELECT job_id, object_key
                        FROM ocr_artifacts WHERE job_id=ANY($1::uuid[])
                    ) AS refs
                    WHERE refs.object_key IS NOT NULL
                      AND refs.object_key <> ''
                      AND refs.object_key LIKE ('jobs/' || refs.job_id::text || '/%')
                    GROUP BY refs.job_id
                    """,
                    job_ids,
                )
                object_keys_by_job = {
                    row["job_id"]: tuple(row["object_keys"] or ())
                    for row in object_rows
                }
            candidates.extend(
                RetentionCandidate(
                    aggregate_kind="job",
                    aggregate_id=row["id"],
                    claim_token=row["retention_claim_token"],
                    object_keys=object_keys_by_job.get(row["id"], ()),
                )
                for row in job_rows
            )

            remaining = limit - len(job_rows)
            if remaining > 0:
                upload_claim_token = uuid7()
                upload_rows = await connection.fetch(
                    """
                    WITH candidates AS (
                        SELECT upload.id
                        FROM upload_sessions AS upload
                        WHERE upload.expires_at <= $1
                          AND NOT EXISTS (
                              SELECT 1 FROM ocr_jobs AS job
                              WHERE job.upload_id=upload.id
                          )
                          AND (
                              upload.retention_claim_token IS NULL
                              OR upload.retention_lease_expires_at <= $1
                          )
                        ORDER BY upload.expires_at, upload.id
                        FOR UPDATE SKIP LOCKED
                        LIMIT $2
                    )
                    UPDATE upload_sessions AS upload
                    SET retention_claim_token=$3,
                        retention_lease_expires_at=$4,
                        updated_at=now()
                    FROM candidates
                    WHERE upload.id=candidates.id
                    RETURNING upload.id,
                              upload.retention_claim_token,
                              upload.object_key,
                              CASE WHEN upload.status='pending'
                                   THEN upload.multipart_upload_id
                                   ELSE NULL
                              END AS multipart_upload_id
                    """,
                    now,
                    remaining,
                    upload_claim_token,
                    lease_expires_at,
                )
                candidates.extend(
                    RetentionCandidate(
                        aggregate_kind="upload",
                        aggregate_id=row["id"],
                        claim_token=row["retention_claim_token"],
                        object_keys=(row["object_key"],),
                        multipart_upload_id=row["multipart_upload_id"],
                    )
                    for row in upload_rows
                )

        return candidates

    async def complete(self, candidate: RetentionCandidate) -> bool:
        async with self.pool.acquire() as connection, connection.transaction():
            if candidate.aggregate_kind == "job":
                claimed = await connection.fetchval(
                    """
                    SELECT 1 FROM ocr_jobs
                    WHERE id=$1 AND retention_claim_token=$2
                    FOR UPDATE
                    """,
                    candidate.aggregate_id,
                    candidate.claim_token,
                )
                if not claimed:
                    return False
                await connection.execute(
                    """
                    DELETE FROM outbox_events
                    WHERE aggregate_type='ocr_job' AND aggregate_id=$1
                    """,
                    candidate.aggregate_id,
                )
                status = await connection.execute(
                    """
                    DELETE FROM ocr_jobs
                    WHERE id=$1 AND retention_claim_token=$2
                    """,
                    candidate.aggregate_id,
                    candidate.claim_token,
                )
            else:
                status = await connection.execute(
                    """
                    DELETE FROM upload_sessions AS upload
                    WHERE upload.id=$1
                      AND upload.retention_claim_token=$2
                      AND NOT EXISTS (
                          SELECT 1 FROM ocr_jobs AS job
                          WHERE job.upload_id=upload.id
                      )
                    """,
                    candidate.aggregate_id,
                    candidate.claim_token,
                )
        return status == "DELETE 1"

    async def defer(
        self, candidate: RetentionCandidate, *, retry_at: datetime
    ) -> None:
        table = "ocr_jobs" if candidate.aggregate_kind == "job" else "upload_sessions"
        async with self.pool.acquire() as connection:
            await connection.execute(
                f"""
                UPDATE {table}
                SET retention_lease_expires_at=$3, updated_at=now()
                WHERE id=$1 AND retention_claim_token=$2
                """,
                candidate.aggregate_id,
                candidate.claim_token,
                retry_at,
            )


class AsyncpgOutboxRepository:
    def __init__(self, pool: Any, *, topic: str) -> None:
        self.pool = pool
        self.topic = topic

    async def add(self, event: OutboxEvent) -> None:
        async with self.pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO outbox_events (
                    id,aggregate_type,aggregate_id,event_type,topic,partition_key,
                    schema_version,payload,created_at
                ) VALUES ($1,'ocr_job',$2,$3,$4,$5,1,$6::jsonb,$7)
                """,
                event.id,
                event.aggregate_id,
                event.event_type,
                self.topic,
                str(event.aggregate_id),
                _json(event.payload),
                event.created_at,
            )

    async def pending(self, *, limit: int = 100) -> list[OutboxEvent]:
        async with self.pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT * FROM outbox_events WHERE published_at IS NULL
                ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT $1
                """,
                limit,
            )
        return [
            OutboxEvent(
                id=row["id"],
                aggregate_id=row["aggregate_id"],
                event_type=row["event_type"],
                payload=_decode_json(row["payload"]),
                request_id=str(_decode_json(row["payload"]).get("request_id", "")),
                created_at=row["created_at"],
                published_at=row["published_at"],
            )
            for row in rows
        ]

    async def mark_published(self, event_id: UUID) -> None:
        async with self.pool.acquire() as connection:
            await connection.execute(
                "UPDATE outbox_events SET published_at=now(), publish_attempts=publish_attempts+1 WHERE id=$1",
                event_id,
            )


class AsyncpgJobEventRepository:
    def __init__(self, pool: Any) -> None:
        self.pool = pool

    async def append(self, event: JobEvent) -> JobEvent:
        async with self.pool.acquire() as connection, connection.transaction():
            return await self.append_with_connection(connection, event)

    @staticmethod
    async def append_with_connection(connection: Any, event: JobEvent) -> JobEvent:
        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1,0))", str(event.job_id)
        )
        if event.event_type in {"job.cancelled", "job.failed", "job.succeeded"}:
            existing = await connection.fetchval(
                """
                SELECT sequence FROM job_events
                WHERE job_id=$1 AND event_type=$2
                  AND payload->'data'->>'attempt'=$3
                LIMIT 1
                """,
                event.job_id,
                event.event_type,
                str(event.payload.get("attempt", "")),
            )
            if existing is not None:
                return event.with_sequence(int(existing))
        sequence = await connection.fetchval(
            "SELECT COALESCE(max(sequence),0)+1 FROM job_events WHERE job_id=$1",
            event.job_id,
        )
        payload = {
            "state": str(event.state),
            "progress": event.progress,
            "request_id": event.request_id,
            "data": event.payload,
        }
        default_internal_code = 30004 if event.state is JobState.FAILED else 0
        try:
            internal_code = int(
                event.payload.get("internal_code", default_internal_code)
            )
        except (TypeError, ValueError):
            internal_code = default_internal_code
        await connection.execute(
            """
            INSERT INTO job_events (job_id,sequence,event_type,internal_code,payload,created_at)
            VALUES ($1,$2,$3,$4,$5::jsonb,$6)
            """,
            event.job_id,
            sequence,
            event.event_type,
            internal_code,
            _json(payload),
            event.occurred_at,
        )
        return event.with_sequence(int(sequence))

    async def list_after(self, job_id: UUID, sequence: int) -> list[JobEvent]:
        async with self.pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT * FROM job_events WHERE job_id=$1 AND sequence>$2
                ORDER BY sequence LIMIT 100
                """,
                job_id,
                sequence,
            )
        return [self._from_row(row) for row in rows]

    async def wait_after(
        self, job_id: UUID, sequence: int, timeout_seconds: float
    ) -> list[JobEvent]:
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            events = await self.list_after(job_id, sequence)
            if events:
                return events
            await asyncio.sleep(min(0.25, max(0, deadline - asyncio.get_running_loop().time())))
        return []

    @staticmethod
    def _from_row(row: Any) -> JobEvent:
        payload = _decode_json(row["payload"])
        return JobEvent(
            job_id=row["job_id"],
            sequence=row["sequence"],
            event_type=row["event_type"],
            state=JobState(payload["state"]),
            progress=float(payload["progress"]),
            request_id=str(payload["request_id"]),
            payload=payload.get("data") or {},
            occurred_at=row["created_at"],
        )

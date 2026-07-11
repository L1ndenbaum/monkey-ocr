from __future__ import annotations

import hashlib
from collections.abc import Awaitable
from pathlib import PurePath
from typing import TypeVar
from uuid import UUID

from uuid6 import uuid7

from src.shared.api import InternalStatusCode
from src.shared.errors import BusinessError

from ..domain.models import Job, JobEvent, JobState, Upload, UploadState, utc_now
from .exceptions import (
    ConcurrentJobUpdateError,
    DatabaseUnavailableError,
    DependencyError,
    DuplicateIdempotencyKeyError,
    StorageUnavailableError,
)
from .dto import (
    ArtifactDTO,
    ArtifactListDTO,
    CompleteUploadDTO,
    CreateJobRequest,
    CreateUploadRequest,
    JobDTO,
    JobListDTO,
    UploadPartDTO,
    UploadDTO,
)
from .ports import (
    FileValidator,
    JobRepository,
    ObjectStorage,
    OutboxEvent,
    OutboxRepository,
    UploadRepository,
)


T = TypeVar("T")


class OCRApplicationService:
    def __init__(
        self,
        *,
        uploads: UploadRepository,
        jobs: JobRepository,
        outbox: OutboxRepository,
        storage: ObjectStorage,
        validator: FileValidator,
        max_upload_bytes: int = 100 * 1024 * 1024,
    ) -> None:
        self.uploads = uploads
        self.jobs = jobs
        self.outbox = outbox
        self.storage = storage
        self.validator = validator
        self.max_upload_bytes = max_upload_bytes

    async def create_upload(
        self, request: CreateUploadRequest, *, owner_id: str
    ) -> UploadDTO:
        if request.size_bytes > self.max_upload_bytes:
            raise BusinessError(
                InternalStatusCode.UPLOAD_FILE_TOO_LARGE,
                "文件超过允许的大小",
                "upload_file_too_large",
                data={"max_size_bytes": self.max_upload_bytes},
            )
        if request.content_type not in {
            "application/pdf",
            "image/jpeg",
            "image/png",
            "image/webp",
            "image/bmp",
            "image/tiff",
        }:
            raise BusinessError(
                InternalStatusCode.UPLOAD_UNSUPPORTED_FILE_TYPE,
                "仅支持 PDF 和静态图片",
                "upload_unsupported_file_type",
            )

        safe_filename = PurePath(request.filename).name
        upload_id = uuid7()
        object_key = f"uploads/{upload_id}/source"
        upload = Upload(
            id=upload_id,
            owner_id=owner_id,
            filename=safe_filename,
            size_bytes=request.size_bytes,
            content_type=request.content_type,
            sha256=request.sha256,
            object_key=object_key,
        )
        target = await self._storage(
            self.storage.create_upload_target(
                object_key,
                content_type=request.content_type,
                size_bytes=request.size_bytes,
                sha256=request.sha256,
            )
        )
        upload.multipart_upload_id = target.upload_id
        await self._database(self.uploads.add(upload))
        return UploadDTO(
            upload_id=upload.id,
            object_key=upload.object_key,
            upload_url=target.url,
            upload_method=target.method,
            upload_headers=target.headers,
            multipart_upload_id=target.upload_id,
            part_size_bytes=target.part_size_bytes,
            parts=[
                UploadPartDTO(part_number=number, upload_url=url)
                for number, url in target.part_urls
            ],
            status=upload.state,
        )

    async def complete_upload(
        self,
        upload_id: UUID,
        *,
        owner_id: str,
        provided_sha256: str | None = None,
        multipart_upload_id: str | None = None,
        parts: list[tuple[int, str]] | None = None,
    ) -> CompleteUploadDTO:
        upload = await self._owned_upload(upload_id, owner_id)
        if provided_sha256 is not None and provided_sha256 != upload.sha256:
            raise BusinessError(
                InternalStatusCode.UPLOAD_HASH_MISMATCH,
                "客户端确认哈希与上传会话不一致",
                "completion_hash_mismatch",
            )
        if upload.multipart_upload_id and multipart_upload_id != upload.multipart_upload_id:
            raise BusinessError(
                InternalStatusCode.COMMON_STATE_CONFLICT,
                "多段上传会话标识不匹配",
                "multipart_upload_id_mismatch",
            )
        if upload.state is UploadState.COMPLETED:
            return CompleteUploadDTO(
                upload_id=upload.id,
                status=upload.state,
                detected_content_type=upload.detected_content_type or upload.content_type,
            )
        if upload.state is not UploadState.UPLOADING:
            raise BusinessError(
                InternalStatusCode.COMMON_STATE_CONFLICT,
                "上传会话状态不允许完成",
                "upload_state_conflict",
            )

        await self._storage(
            self.storage.complete_upload(
                upload.object_key,
                upload_id=upload.multipart_upload_id,
                parts=parts or [],
            )
        )
        info = await self._storage(self.storage.stat(upload.object_key))
        if info is None:
            raise BusinessError(
                InternalStatusCode.UPLOAD_NOT_COMPLETED,
                "尚未找到已上传对象",
                "upload_object_missing",
            )
        if info.size_bytes != upload.size_bytes or (info.sha256 and info.sha256 != upload.sha256):
            upload.reject()
            await self._database(self.uploads.save(upload))
            raise BusinessError(
                InternalStatusCode.UPLOAD_HASH_MISMATCH,
                "上传文件大小或哈希不匹配",
                "upload_hash_mismatch",
            )

        try:
            data = await self._storage(self.storage.get_bytes(upload.object_key))
        except FileNotFoundError as exc:
            raise BusinessError(
                InternalStatusCode.UPLOAD_NOT_COMPLETED,
                "尚未找到已上传对象",
                "upload_object_missing",
            ) from exc
        if hashlib.sha256(data).hexdigest() != upload.sha256:
            upload.reject()
            await self._database(self.uploads.save(upload))
            raise BusinessError(
                InternalStatusCode.UPLOAD_HASH_MISMATCH,
                "上传文件哈希校验失败",
                "upload_hash_mismatch",
            )
        validation = await self.validator.validate(upload, data)
        upload.complete(validation.detected_content_type)
        await self._database(self.uploads.save(upload))
        return CompleteUploadDTO(
            upload_id=upload.id,
            status=upload.state,
            detected_content_type=validation.detected_content_type,
        )

    async def create_job(
        self,
        request: CreateJobRequest,
        *,
        owner_id: str,
        request_id: str,
        idempotency_key: str | None,
    ) -> JobDTO:
        upload = await self._owned_upload(request.upload_id, owner_id)
        if upload.state is not UploadState.COMPLETED:
            raise BusinessError(
                InternalStatusCode.UPLOAD_NOT_COMPLETED,
                "上传尚未完成或未通过校验",
                "upload_not_completed",
            )
        if idempotency_key:
            existing = await self._database(
                self.jobs.find_by_idempotency_key(owner_id, idempotency_key)
            )
            if existing:
                if existing.upload_id != upload.id or existing.options != request.options:
                    raise BusinessError(
                        InternalStatusCode.COMMON_IDEMPOTENCY_CONFLICT,
                        "幂等键已用于其他请求",
                        "idempotency_conflict",
                    )
                return await self._to_job_dto(existing)

        job = Job(
            owner_id=owner_id,
            upload_id=upload.id,
            request_id=request_id,
            options=request.options,
            idempotency_key=idempotency_key,
        )
        outbox_event = OutboxEvent(
            id=uuid7(),
            aggregate_id=job.id,
            event_type="ocr.job.requested.v1",
            payload={
                "schema_version": 1,
                "job_id": str(job.id),
                "attempt": job.attempt,
                "request_id": request_id,
            },
            request_id=request_id,
            created_at=utc_now(),
        )
        try:
            await self._database(
                self.jobs.add_with_outbox_and_event(
                    job,
                    outbox_event,
                    self._job_event(job, "job.queued"),
                    self.outbox,
                )
            )
        except DuplicateIdempotencyKeyError:
            if not idempotency_key:
                raise
            existing = await self._database(
                self.jobs.find_by_idempotency_key(owner_id, idempotency_key)
            )
            if existing is None:
                raise DatabaseUnavailableError(
                    "idempotent job was committed but cannot be reloaded"
                )
            if existing.upload_id != upload.id or existing.options != request.options:
                raise BusinessError(
                    InternalStatusCode.COMMON_IDEMPOTENCY_CONFLICT,
                    "幂等键已用于其他请求",
                    "idempotency_conflict",
                )
            return await self._to_job_dto(existing)
        return await self._to_job_dto(job)

    async def get_job(self, job_id: UUID, *, owner_id: str) -> JobDTO:
        return await self._to_job_dto(await self._owned_job(job_id, owner_id))

    async def get_job_domain(self, job_id: UUID, *, owner_id: str) -> Job:
        return await self._owned_job(job_id, owner_id)

    async def list_jobs(
        self, *, owner_id: str, page: int, page_size: int
    ) -> JobListDTO:
        jobs, total = await self._database(
            self.jobs.list(owner_id, offset=(page - 1) * page_size, limit=page_size)
        )
        return JobListDTO(
            items=[await self._to_job_dto(job) for job in jobs],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def cancel_job(
        self, job_id: UUID, *, owner_id: str, request_id: str
    ) -> JobDTO:
        for save_attempt in range(3):
            job = await self._owned_job(job_id, owner_id)
            if job.state in {JobState.CANCELLED, JobState.SUCCEEDED}:
                raise BusinessError(
                    InternalStatusCode.JOB_NOT_CANCELLABLE,
                    "当前任务状态不允许取消",
                    "job_not_cancellable",
                )
            if job.state is JobState.CANCEL_REQUESTED:
                return await self._to_job_dto(job)
            try:
                previous = job.state
                job.request_id = request_id
                job.request_cancel()
                if previous in {JobState.QUEUED, JobState.RETRYING}:
                    job.cancel()
                await self._save_and_emit(
                    job,
                    "job.cancelled"
                    if job.state is JobState.CANCELLED
                    else "job.cancel_requested",
                )
            except ConcurrentJobUpdateError as exc:
                if save_attempt < 2:
                    continue
                raise DatabaseUnavailableError(
                    "job cancellation was updated concurrently"
                ) from exc
            except ValueError as exc:
                raise BusinessError(
                    InternalStatusCode.JOB_NOT_CANCELLABLE,
                    "当前任务状态不允许取消",
                    "job_not_cancellable",
                ) from exc
            return await self._to_job_dto(job)
        raise AssertionError("unreachable")

    async def retry_job(
        self, job_id: UUID, *, owner_id: str, request_id: str
    ) -> JobDTO:
        for save_attempt in range(3):
            job = await self._owned_job(job_id, owner_id)
            try:
                job.retry(request_id)
            except ValueError as exc:
                if job.state is JobState.RETRYING and save_attempt > 0:
                    return await self._to_job_dto(job)
                raise BusinessError(
                    InternalStatusCode.JOB_NOT_RETRYABLE,
                    "仅失败或已取消任务可以重试",
                    "job_not_retryable",
                ) from exc
            outbox_event = OutboxEvent(
                id=uuid7(),
                aggregate_id=job.id,
                event_type="ocr.job.requested.v1",
                payload={
                    "schema_version": 1,
                    "job_id": str(job.id),
                    "attempt": job.attempt,
                    "request_id": request_id,
                },
                request_id=request_id,
                created_at=utc_now(),
            )
            try:
                await self._database(
                    self.jobs.save_with_outbox_and_event(
                        job,
                        outbox_event,
                        self._job_event(job, "job.retrying"),
                        self.outbox,
                    )
                )
            except ConcurrentJobUpdateError as exc:
                if save_attempt < 2:
                    continue
                raise DatabaseUnavailableError(
                    "job retry was updated concurrently"
                ) from exc
            return await self._to_job_dto(job)
        raise AssertionError("unreachable")

    async def list_artifacts(self, job_id: UUID, *, owner_id: str) -> ArtifactListDTO:
        job = await self._owned_job(job_id, owner_id)
        if job.state is not JobState.SUCCEEDED:
            raise BusinessError(
                InternalStatusCode.JOB_RESULT_NOT_READY,
                "任务结果尚未就绪",
                "job_result_not_ready",
            )
        items: list[ArtifactDTO] = []
        for artifact in job.artifacts:
            try:
                download_url = await self._storage(
                    self.storage.create_download_url(artifact.object_key)
                )
            except FileNotFoundError as exc:
                raise BusinessError(
                    InternalStatusCode.JOB_RESULT_NOT_READY,
                    "任务结果对象暂不可用",
                    "job_artifact_missing",
                ) from exc
            items.append(ArtifactDTO.from_domain(artifact, download_url))
        return ArtifactListDTO(items=items)

    async def _owned_upload(self, upload_id: UUID, owner_id: str) -> Upload:
        upload = await self._database(self.uploads.get(upload_id))
        if upload is None:
            raise BusinessError(
                InternalStatusCode.UPLOAD_NOT_FOUND,
                "上传会话不存在",
                "upload_not_found",
            )
        if upload.owner_id != owner_id:
            raise BusinessError(
                InternalStatusCode.USER_UNAUTHORIZED,
                "无权访问该上传会话",
                "user_unauthorized",
            )
        return upload

    async def _owned_job(self, job_id: UUID, owner_id: str) -> Job:
        job = await self._database(self.jobs.get(job_id))
        if job is None:
            raise BusinessError(
                InternalStatusCode.JOB_NOT_FOUND,
                "任务不存在",
                "job_not_found",
            )
        if job.owner_id != owner_id:
            raise BusinessError(
                InternalStatusCode.USER_UNAUTHORIZED,
                "无权访问该任务",
                "user_unauthorized",
            )
        return job

    async def _to_job_dto(self, job: Job) -> JobDTO:
        upload = await self._database(self.uploads.get(job.upload_id))
        return JobDTO.from_domain(job, filename=upload.filename if upload else "")

    async def _save_and_emit(
        self, job: Job, event_type: str, **payload: object
    ) -> JobEvent:
        return await self._database(
            self.jobs.save_with_event(
                job, self._job_event(job, event_type, **payload)
            )
        )

    @staticmethod
    def _job_event(job: Job, event_type: str, **payload: object) -> JobEvent:
        return JobEvent(
            job_id=job.id,
            event_type=event_type,
            state=job.state,
            progress=job.progress,
            request_id=job.request_id,
            payload={"attempt": job.attempt, **payload},
        )

    @staticmethod
    async def _database(operation: Awaitable[T]) -> T:
        try:
            return await operation
        except (
            BusinessError,
            ConcurrentJobUpdateError,
            DependencyError,
            DuplicateIdempotencyKeyError,
        ):
            raise
        except Exception as exc:
            raise DatabaseUnavailableError("database operation failed") from exc

    @staticmethod
    async def _storage(operation: Awaitable[T]) -> T:
        try:
            return await operation
        except (BusinessError, DependencyError, FileNotFoundError):
            raise
        except Exception as exc:
            raise StorageUnavailableError("object storage operation failed") from exc

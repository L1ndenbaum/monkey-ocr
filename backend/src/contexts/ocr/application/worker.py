from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, TypeVar

from src.shared.api import InternalStatusCode

from ..domain.models import Artifact, ArtifactKind, Job, JobEvent, JobState, Page, PageState
from .exceptions import (
    ConcurrentJobUpdateError,
    DatabaseUnavailableError,
    DependencyError,
    StorageUnavailableError,
    TransientEngineError,
)
from .ports import (
    DocumentPreprocessor,
    JobEventRepository,
    JobRepository,
    JobWorkMessage,
    OCREngine,
    ObjectStorage,
    StructuredLogger,
    UploadRepository,
)


T = TypeVar("T")


async def _noop_sleep(_: float) -> None:
    await asyncio.sleep(0)


class OCRWorker:
    """Idempotent, page-checkpointed OCR job consumer."""

    def __init__(
        self,
        *,
        jobs: JobRepository,
        uploads: UploadRepository,
        events: JobEventRepository,
        storage: ObjectStorage,
        preprocessor: DocumentPreprocessor,
        engine: OCREngine,
        logger: StructuredLogger,
        max_page_retries: int = 3,
        retry_base_seconds: float = 1.0,
        sleeper: Callable[[float], Awaitable[None]] = _noop_sleep,
    ) -> None:
        if max_page_retries < 0:
            raise ValueError("max_page_retries must not be negative")
        self.jobs = jobs
        self.uploads = uploads
        self.events = events
        self.storage = storage
        self.preprocessor = preprocessor
        self.engine = engine
        self.logger = logger
        self.max_page_retries = max_page_retries
        self.retry_base_seconds = retry_base_seconds
        self.sleeper = sleeper

    async def process(self, message: JobWorkMessage) -> Job | None:
        if message.schema_version != 1:
            await self.logger.error(
                "ocr_job_schema_unsupported",
                job_id=str(message.job_id),
                schema_version=message.schema_version,
                request_id=message.request_id,
            )
            return None

        try:
            job = await self._database(self.jobs.get(message.job_id))
            if job is None:
                await self.logger.error(
                    "ocr_job_missing",
                    job_id=str(message.job_id),
                    request_id=message.request_id,
                )
                return None
            if job.attempt != message.attempt:
                return job
            if job.terminal:
                await self._repair_terminal_event(job)
                return job

            upload = await self._database(self.uploads.get(job.upload_id))
            if upload is None:
                return await self._fail(job, "upload_not_found")

            if job.state in {JobState.QUEUED, JobState.RETRYING}:
                job.begin_preprocessing()
                await self._save_and_emit(job, "job.preprocessing")

            if not job.pages:
                if job.state is not JobState.PREPROCESSING:
                    raise RuntimeError("job checkpoint has no prepared pages")
                prepared = await self.preprocessor.prepare(upload, job)
                job.set_pages(
                    [
                        Page(page_number=page.page_number, input_object_key=page.object_key)
                        for page in sorted(prepared, key=lambda item: item.page_number)
                    ]
                )
                await self._save_and_emit(
                    job, "job.pages_prepared", total_pages=job.total_pages
                )

            refreshed = await self._cancel_if_requested(job)
            if refreshed is not None:
                return refreshed
            if job.state is JobState.PREPROCESSING:
                job.begin_running()
                await self._save_and_emit(job, "job.running")
            elif job.state is JobState.ASSEMBLING:
                artifacts = await self._assemble(job, upload)
                refreshed = await self._cancel_if_requested(job)
                if refreshed is not None:
                    return refreshed
                job = await self._database(self.jobs.get(job.id)) or job
                job.succeed(artifacts)
                await self._save_and_emit(
                    job, "job.succeeded", artifact_count=len(artifacts)
                )
                return job
            elif job.state is not JobState.RUNNING:
                raise RuntimeError(f"cannot recover job from {job.state}")

            for page_index, page in enumerate(job.pages):
                if page.state is PageState.SUCCEEDED:
                    continue
                refreshed = await self._cancel_if_requested(job)
                if refreshed is not None:
                    return refreshed
                job = await self._database(self.jobs.get(job.id)) or job
                page = job.pages[page_index]
                completed = await self._process_page(job, page_index, page)
                if completed.state in {JobState.FAILED, JobState.CANCELLED}:
                    return completed
                job = completed

            job.begin_assembling()
            await self._save_and_emit(job, "job.assembling")
            artifacts = await self._assemble(job, upload)
            refreshed = await self._cancel_if_requested(job)
            if refreshed is not None:
                return refreshed
            job = await self._database(self.jobs.get(job.id)) or job
            job.succeed(artifacts)
            await self._save_and_emit(
                job, "job.succeeded", artifact_count=len(artifacts)
            )
            await self.logger.info(
                "ocr_job_succeeded",
                job_id=str(job.id),
                attempt=job.attempt,
                request_id=job.request_id,
                total_pages=job.total_pages,
            )
            return job
        except ConcurrentJobUpdateError as exc:
            latest = await self._database(self.jobs.get(message.job_id))
            if latest is None:
                return None
            if latest.state is JobState.CANCEL_REQUESTED:
                latest.cancel()
                await self._save_and_emit(latest, "job.cancelled")
                return latest
            if latest.terminal or latest.attempt != message.attempt:
                return latest
            raise DatabaseUnavailableError(
                "job was updated concurrently"
            ) from exc
        except Exception as exc:
            internal_code = self._internal_code(exc)
            reason = self._reason(exc)
            await self.logger.error(
                "ocr_job_failed",
                job_id=str(message.job_id),
                attempt=message.attempt,
                request_id=message.request_id,
                internal_code=int(internal_code),
                internal_status_name=internal_code.name,
                error_reason=reason,
                error_type=type(exc).__name__,
            )
            if isinstance(exc, DatabaseUnavailableError):
                raise
            latest = await self._database(self.jobs.get(job.id)) or job
            if latest.state is JobState.CANCEL_REQUESTED:
                latest.cancel()
                await self._save_and_emit(latest, "job.cancelled")
                return latest
            if latest.terminal:
                return latest
            return await self._fail(latest, reason, internal_code=internal_code)

    async def _process_page(self, job: Job, page_index: int, page: Page) -> Job:
        image = await self._storage(self.storage.get_bytes(page.input_object_key))
        last_error: Exception | None = None
        max_attempts = self.max_page_retries + 1

        while True:
            latest = await self._database(self.jobs.get(job.id)) or job
            if latest.state is JobState.CANCEL_REQUESTED:
                latest.cancel()
                await self._save_and_emit(latest, "job.cancelled")
                return latest

            job = latest
            page = job.pages[page_index]
            if page.processing_attempts >= max_attempts:
                break
            page.start()
            await self._save_and_emit(
                job,
                "page.running",
                page_number=page.page_number,
                processing_attempt=page.processing_attempts,
            )
            try:
                result = await self.engine.recognize(
                    image=image,
                    page_number=page.page_number,
                    options=job.options,
                    request_id=job.request_id,
                )
                latest = await self._database(self.jobs.get(job.id)) or job
                if latest.state is JobState.CANCEL_REQUESTED:
                    latest.cancel()
                    await self._save_and_emit(latest, "job.cancelled")
                    return latest
                page = latest.pages[page_index]
                latest.engine_name = self._metadata_text(
                    result.engine_metadata.get("engine"), 80
                )
                latest.engine_version = self._metadata_text(
                    result.engine_metadata.get("version"), 80
                )
                latest.model_name = self._metadata_text(
                    result.engine_metadata.get("model"), 160
                )
                visualization_key: str | None = None
                if result.visualization is not None:
                    visualization_extension = {
                        "image/jpeg": "jpg",
                        "image/png": "png",
                        "image/webp": "webp",
                    }.get(result.visualization_content_type, "bin")
                    visualization_key = (
                        f"jobs/{job.id}/attempts/{job.attempt}/pages/"
                        f"{page.page_number:06d}.visualization.{visualization_extension}"
                    )
                    await self._storage(
                        self.storage.put_bytes(
                            visualization_key,
                            result.visualization,
                            content_type=result.visualization_content_type,
                        )
                    )
                result_payload = json.dumps(
                    {
                        "schema_version": 1,
                        "page_number": page.page_number,
                        "markdown": result.markdown,
                        "structured": result.structured,
                        "engine_metadata": result.engine_metadata,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                result_key = (
                    f"jobs/{job.id}/attempts/{job.attempt}/pages/"
                    f"{page.page_number:06d}.json"
                )
                result_object = await self._storage(
                    self.storage.put_bytes(
                        result_key, result_payload, content_type="application/json"
                    )
                )
                page.succeed(
                    markdown=result.markdown,
                    structured={
                        **result.structured,
                        "engine_metadata": result.engine_metadata,
                    },
                    result_object_key=result_object.object_key,
                    result_sha256=result_object.sha256,
                    visualization_object_key=visualization_key,
                )
                await self._save_and_emit(
                    latest,
                    "page.succeeded",
                    page_number=page.page_number,
                    completed_pages=latest.completed_pages,
                    total_pages=latest.total_pages,
                )
                if latest.state is JobState.CANCEL_REQUESTED:
                    latest.cancel()
                    await self._save_and_emit(latest, "job.cancelled")
                return latest
            except Exception as exc:
                if isinstance(exc, (ConcurrentJobUpdateError, DatabaseUnavailableError)):
                    raise
                last_error = exc
                reason = self._reason(exc)
                internal_code = self._internal_code(exc)
                page.internal_code = int(internal_code)
                page.error_reason = reason
                is_retryable = isinstance(exc, TransientEngineError)
                if not is_retryable or page.processing_attempts >= max_attempts:
                    break
                await self._save_and_emit(
                    job,
                    "page.retry_scheduled",
                    page_number=page.page_number,
                    processing_attempt=page.processing_attempts,
                    retry_number=page.processing_attempts,
                    internal_code=int(internal_code),
                    error_reason=reason,
                )
                await self.sleeper(
                    self.retry_base_seconds * (2 ** (page.processing_attempts - 1))
                )

        latest = await self._database(self.jobs.get(job.id)) or job
        page = latest.pages[page_index]
        reason = (
            self._reason(last_error)
            if last_error is not None
            else page.error_reason or "engine_retry_budget_exhausted"
        )
        internal_code = self._internal_code(
            last_error or RuntimeError("engine retry budget exhausted")
        )
        page.fail(reason, internal_code=int(internal_code))
        await self._save_and_emit(
            latest,
            "page.failed",
            page_number=page.page_number,
            internal_code=int(internal_code),
            error_reason=reason,
        )
        await self.logger.error(
            "ocr_job_failed",
            job_id=str(latest.id),
            attempt=latest.attempt,
            request_id=latest.request_id,
            page_number=page.page_number,
            internal_code=int(internal_code),
            internal_status_name=internal_code.name,
            error_reason=reason,
            error_type=type(last_error).__name__ if last_error else "RuntimeError",
        )
        return await self._fail(latest, reason, internal_code=internal_code)

    async def _assemble(self, job: Job, upload: Any) -> list[Artifact]:
        prefix = f"jobs/{job.id}/attempts/{job.attempt}"
        page_results = [await self._load_page_result(page) for page in job.pages]
        markdown = "\n\n".join(result["markdown"] for result in page_results).encode("utf-8")
        structured = {
            "job_id": str(job.id),
            "attempt": job.attempt,
            "pages": [
                {
                    "page_number": page.page_number,
                    "markdown": result["markdown"],
                    "blocks": result["structured"],
                }
                for page, result in zip(job.pages, page_results, strict=True)
            ],
        }
        structured_bytes = json.dumps(
            structured, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        markdown_object = await self._storage(
            self.storage.put_bytes(
                f"{prefix}/document.md",
                markdown,
                content_type="text/markdown; charset=utf-8",
            )
        )
        json_object = await self._storage(
            self.storage.put_bytes(
                f"{prefix}/document.json",
                structured_bytes,
                content_type="application/json",
            )
        )
        artifacts = [
            self._artifact(ArtifactKind.MARKDOWN, markdown_object),
            self._artifact(ArtifactKind.JSON, json_object),
        ]

        for page in job.pages:
            page_info = await self._storage(self.storage.stat(page.input_object_key))
            if page_info:
                page_sha256 = page_info.sha256 or hashlib.sha256(
                    await self._storage(self.storage.get_bytes(page.input_object_key))
                ).hexdigest()
                artifacts.append(
                    Artifact(
                        kind=ArtifactKind.PAGE_IMAGE,
                        object_key=page_info.object_key,
                        sha256=page_sha256,
                        size_bytes=page_info.size_bytes,
                        content_type=page_info.content_type,
                        page_number=page.page_number,
                    )
                )
            if page.visualization_object_key:
                visual_info = await self._storage(
                    self.storage.stat(page.visualization_object_key)
                )
                if visual_info:
                    visual_sha256 = visual_info.sha256 or hashlib.sha256(
                        await self._storage(
                            self.storage.get_bytes(page.visualization_object_key)
                        )
                    ).hexdigest()
                    artifacts.append(
                        Artifact(
                            kind=ArtifactKind.VISUALIZATION,
                            object_key=visual_info.object_key,
                            sha256=visual_sha256,
                            size_bytes=visual_info.size_bytes,
                            content_type=visual_info.content_type,
                            page_number=page.page_number,
                        )
                    )

        manifest = {
            "schema_version": 1,
            "job_id": str(job.id),
            "upload_id": str(job.upload_id),
            "attempt": job.attempt,
            "page_count": job.total_pages,
            "generated_at": datetime.now(UTC).isoformat(),
            "input": {
                "sha256": upload.sha256,
                "size_bytes": upload.size_bytes,
                "content_type": upload.detected_content_type or upload.content_type,
            },
            "engines": [
                result.get("engine_metadata", {}) for result in page_results
            ],
            "artifacts": [
                {
                    "kind": artifact.kind,
                    "object_key": artifact.object_key,
                    "sha256": artifact.sha256,
                    "size_bytes": artifact.size_bytes,
                    "content_type": artifact.content_type,
                    "page_number": artifact.page_number,
                }
                for artifact in artifacts
            ],
        }
        manifest_bytes = json.dumps(
            manifest, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        manifest_object = await self._storage(
            self.storage.put_bytes(
                f"{prefix}/manifest.json",
                manifest_bytes,
                content_type="application/json",
            )
        )
        artifacts.append(self._artifact(ArtifactKind.MANIFEST, manifest_object))
        return artifacts

    async def _load_page_result(self, page: Page) -> dict[str, Any]:
        if page.result_object_key:
            payload = json.loads(
                await self._storage(self.storage.get_bytes(page.result_object_key))
            )
            if isinstance(payload, dict):
                markdown = payload.get("markdown")
                structured = payload.get("structured")
                if isinstance(markdown, str) and isinstance(structured, dict):
                    return {
                        "markdown": markdown,
                        "structured": structured,
                        "engine_metadata": payload.get("engine_metadata") or {},
                    }
        if page.markdown is not None and page.structured is not None:
            return {
                "markdown": page.markdown,
                "structured": page.structured,
                "engine_metadata": page.structured.get("engine_metadata", {}),
            }
        raise RuntimeError(f"page {page.page_number} checkpoint is missing")

    @staticmethod
    def _artifact(kind: ArtifactKind, stored: Any) -> Artifact:
        return Artifact(
            kind=kind,
            object_key=stored.object_key,
            sha256=stored.sha256,
            size_bytes=stored.size_bytes,
            content_type=stored.content_type,
        )

    async def _cancel_if_requested(self, job: Job) -> Job | None:
        latest = await self._database(self.jobs.get(job.id))
        if latest and latest.state is JobState.CANCEL_REQUESTED:
            latest.cancel()
            await self._save_and_emit(latest, "job.cancelled")
            return latest
        return None

    async def _fail(
        self,
        job: Job,
        reason: str,
        *,
        internal_code: InternalStatusCode = InternalStatusCode.JOB_PROCESSING_FAILED,
    ) -> Job:
        if job.state is JobState.CANCEL_REQUESTED:
            job.cancel()
            event_type = "job.cancelled"
        else:
            job.fail(reason, internal_code=int(internal_code))
            event_type = "job.failed"
        await self._save_and_emit(
            job,
            event_type,
            internal_code=int(internal_code) if event_type == "job.failed" else 0,
            error_reason=reason,
        )
        return job

    async def _save_and_emit(
        self, job: Job, event_type: str, **payload: object
    ) -> JobEvent:
        return await self._database(
            self.jobs.save_with_event(
                job, self._job_event(job, event_type, **payload)
            )
        )

    async def _emit(self, job: Job, event_type: str, **payload: object) -> JobEvent:
        return await self._database(
            self.events.append(self._job_event(job, event_type, **payload))
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

    async def _repair_terminal_event(self, job: Job) -> JobEvent:
        event_type = {
            JobState.CANCELLED: "job.cancelled",
            JobState.FAILED: "job.failed",
            JobState.SUCCEEDED: "job.succeeded",
        }[job.state]
        payload: dict[str, object] = {}
        if job.state is JobState.FAILED:
            payload = {
                "internal_code": job.internal_code,
                "error_reason": job.error_reason or "job_processing_failed",
            }
        elif job.state is JobState.SUCCEEDED:
            payload = {"artifact_count": len(job.artifacts)}
        return await self._emit(job, event_type, **payload)

    @staticmethod
    def _reason(exc: Exception) -> str:
        if isinstance(exc, DependencyError):
            return exc.error_reason
        name = type(exc).__name__
        chars: list[str] = []
        for index, char in enumerate(name):
            if char.isupper() and index:
                chars.append("_")
            chars.append(char.lower())
        return "".join(chars).removesuffix("_error")

    @staticmethod
    def _internal_code(exc: Exception) -> InternalStatusCode:
        if isinstance(exc, DependencyError):
            return exc.internal_code
        return InternalStatusCode.JOB_PROCESSING_FAILED

    @staticmethod
    def _metadata_text(value: object, max_length: int) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized[:max_length] if normalized else None

    @staticmethod
    async def _database(operation: Awaitable[T]) -> T:
        try:
            return await operation
        except (ConcurrentJobUpdateError, DependencyError):
            raise
        except Exception as exc:
            raise DatabaseUnavailableError("database operation failed") from exc

    @staticmethod
    async def _storage(operation: Awaitable[T]) -> T:
        try:
            return await operation
        except (DependencyError, FileNotFoundError):
            raise
        except Exception as exc:
            raise StorageUnavailableError("object storage operation failed") from exc

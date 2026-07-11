from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from uuid6 import uuid7


def utc_now() -> datetime:
    return datetime.now(UTC)


class UploadState(StrEnum):
    UPLOADING = "uploading"
    COMPLETED = "completed"
    REJECTED = "rejected"


class JobState(StrEnum):
    QUEUED = "queued"
    PREPROCESSING = "preprocessing"
    RUNNING = "running"
    ASSEMBLING = "assembling"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class PageState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ArtifactKind(StrEnum):
    MARKDOWN = "markdown"
    JSON = "json"
    PAGE_IMAGE = "page_image"
    VISUALIZATION = "visualization"
    MANIFEST = "manifest"


@dataclass(slots=True)
class Upload:
    owner_id: str
    filename: str
    size_bytes: int
    content_type: str
    sha256: str
    object_key: str
    id: UUID = field(default_factory=uuid7)
    state: UploadState = UploadState.UPLOADING
    created_at: datetime = field(default_factory=utc_now)
    completed_at: datetime | None = None
    detected_content_type: str | None = None
    multipart_upload_id: str | None = None

    def complete(self, detected_content_type: str) -> None:
        if self.state is not UploadState.UPLOADING:
            raise ValueError("upload is not awaiting completion")
        self.state = UploadState.COMPLETED
        self.detected_content_type = detected_content_type
        self.completed_at = utc_now()

    def reject(self) -> None:
        self.state = UploadState.REJECTED


@dataclass(slots=True)
class Page:
    page_number: int
    input_object_key: str
    state: PageState = PageState.PENDING
    processing_attempts: int = 0
    markdown: str | None = None
    structured: dict[str, Any] | None = None
    result_object_key: str | None = None
    result_sha256: str | None = None
    visualization_object_key: str | None = None
    internal_code: int = 0
    error_reason: str | None = None

    def start(self) -> None:
        if self.state is PageState.SUCCEEDED:
            return
        self.state = PageState.RUNNING
        self.processing_attempts += 1
        self.internal_code = 0
        self.error_reason = None

    def succeed(
        self,
        *,
        markdown: str,
        structured: dict[str, Any],
        result_object_key: str,
        result_sha256: str,
        visualization_object_key: str | None,
    ) -> None:
        self.state = PageState.SUCCEEDED
        self.markdown = markdown
        self.structured = structured
        self.result_object_key = result_object_key
        self.result_sha256 = result_sha256
        self.visualization_object_key = visualization_object_key
        self.internal_code = 0
        self.error_reason = None

    def fail(self, reason: str, *, internal_code: int = 30004) -> None:
        self.state = PageState.FAILED
        self.internal_code = internal_code
        self.error_reason = reason

    def prepare_retry(self) -> None:
        if self.state is not PageState.SUCCEEDED:
            self.state = PageState.PENDING
            self.processing_attempts = 0
            self.error_reason = None
            self.markdown = None
            self.structured = None
            self.result_object_key = None
            self.result_sha256 = None
            self.visualization_object_key = None
            self.internal_code = 0


@dataclass(slots=True, frozen=True)
class Artifact:
    kind: ArtifactKind
    object_key: str
    sha256: str
    size_bytes: int
    content_type: str
    page_number: int | None = None


@dataclass(slots=True)
class Job:
    owner_id: str
    upload_id: UUID
    request_id: str
    options: dict[str, Any] = field(default_factory=dict)
    id: UUID = field(default_factory=uuid7)
    state: JobState = JobState.QUEUED
    attempt: int = 1
    revision: int = 0
    pages: list[Page] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    idempotency_key: str | None = None
    engine_name: str | None = None
    engine_version: str | None = None
    model_name: str | None = None
    internal_code: int = 0
    error_reason: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def total_pages(self) -> int:
        return len(self.pages)

    @property
    def completed_pages(self) -> int:
        return sum(page.state is PageState.SUCCEEDED for page in self.pages)

    @property
    def progress(self) -> float:
        if not self.pages:
            return 0.0
        return round(self.completed_pages / len(self.pages), 4)

    @property
    def terminal(self) -> bool:
        return self.state in {JobState.CANCELLED, JobState.SUCCEEDED, JobState.FAILED}

    def _transition(self, target: JobState, allowed: set[JobState]) -> None:
        if self.state not in allowed:
            raise ValueError(f"cannot transition job from {self.state} to {target}")
        self.state = target
        self.updated_at = utc_now()

    def begin_preprocessing(self) -> None:
        self._transition(JobState.PREPROCESSING, {JobState.QUEUED, JobState.RETRYING})
        self.started_at = self.started_at or utc_now()

    def set_pages(self, pages: list[Page]) -> None:
        if self.state is not JobState.PREPROCESSING:
            raise ValueError("pages may only be prepared while preprocessing")
        if not pages:
            raise ValueError("document must contain at least one page")
        self.pages = pages
        self.updated_at = utc_now()

    def begin_running(self) -> None:
        self._transition(JobState.RUNNING, {JobState.PREPROCESSING})

    def request_cancel(self) -> None:
        self._transition(
            JobState.CANCEL_REQUESTED,
            {
                JobState.QUEUED,
                JobState.PREPROCESSING,
                JobState.RUNNING,
                JobState.ASSEMBLING,
                JobState.RETRYING,
            },
        )

    def cancel(self) -> None:
        self._transition(JobState.CANCELLED, {JobState.CANCEL_REQUESTED})
        self.completed_at = utc_now()

    def begin_assembling(self) -> None:
        self._transition(JobState.ASSEMBLING, {JobState.RUNNING})

    def succeed(self, artifacts: list[Artifact]) -> None:
        if not self.pages or any(page.state is not PageState.SUCCEEDED for page in self.pages):
            raise ValueError("all pages must be complete before job success")
        self._transition(JobState.SUCCEEDED, {JobState.ASSEMBLING})
        self.artifacts = artifacts
        self.completed_at = utc_now()
        self.internal_code = 0
        self.error_reason = None

    def fail(self, reason: str, *, internal_code: int = 30004) -> None:
        self._transition(
            JobState.FAILED,
            {
                JobState.QUEUED,
                JobState.PREPROCESSING,
                JobState.RUNNING,
                JobState.ASSEMBLING,
                JobState.RETRYING,
                JobState.CANCEL_REQUESTED,
            },
        )
        self.internal_code = internal_code
        self.error_reason = reason
        self.completed_at = utc_now()

    def retry(self, request_id: str) -> None:
        self._transition(JobState.RETRYING, {JobState.FAILED, JobState.CANCELLED})
        self.attempt += 1
        self.request_id = request_id
        self.internal_code = 0
        self.error_reason = None
        self.started_at = None
        self.completed_at = None
        self.artifacts = []
        for page in self.pages:
            page.prepare_retry()


@dataclass(slots=True, frozen=True)
class JobEvent:
    job_id: UUID
    event_type: str
    state: JobState
    progress: float
    request_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    sequence: int = 0
    occurred_at: datetime = field(default_factory=utc_now)

    def with_sequence(self, sequence: int) -> JobEvent:
        return replace(self, sequence=sequence)

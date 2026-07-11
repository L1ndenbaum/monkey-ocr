from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..domain.models import Artifact, Job, JobEvent, Upload


class CreateUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0)
    content_type: str = Field(min_length=1, max_length=128)
    sha256: str

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        normalized = value.lower()
        if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
            raise ValueError("sha256 must be 64 lowercase hexadecimal characters")
        return normalized


class UploadPartDTO(BaseModel):
    part_number: int
    upload_url: str


class UploadDTO(BaseModel):
    upload_id: UUID
    object_key: str
    upload_url: str | None = None
    upload_method: str = "PUT"
    upload_headers: dict[str, str] = Field(default_factory=dict)
    multipart_upload_id: str | None = None
    part_size_bytes: int | None = None
    parts: list[UploadPartDTO] = Field(default_factory=list)
    status: str
    expires_in_seconds: int = 900


class CompleteUploadPart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    part_number: int = Field(ge=1)
    etag: str = Field(min_length=1, max_length=256)


class CompleteUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sha256: str | None = None
    multipart_upload_id: str | None = None
    parts: list[CompleteUploadPart] = Field(default_factory=list)

    @field_validator("sha256")
    @classmethod
    def validate_optional_sha256(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.lower()
        if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
            raise ValueError("sha256 must be 64 lowercase hexadecimal characters")
        return normalized


class CompleteUploadDTO(BaseModel):
    upload_id: UUID
    status: str
    detected_content_type: str


class CreateJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upload_id: UUID
    options: dict[str, Any] = Field(default_factory=dict)


class PageDTO(BaseModel):
    page_number: int
    status: str
    processing_attempts: int
    internal_code: int
    error_reason: str | None


class JobDTO(BaseModel):
    job_id: UUID
    upload_id: UUID
    filename: str
    status: str
    attempt: int
    progress: float
    completed_pages: int
    total_pages: int
    pages: list[PageDTO]
    options: dict[str, Any]
    engine_name: str | None
    engine_version: str | None
    model_name: str | None
    internal_code: int
    error_reason: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    @classmethod
    def from_domain(cls, job: Job, *, filename: str = "") -> JobDTO:
        return cls(
            job_id=job.id,
            upload_id=job.upload_id,
            filename=filename,
            status=job.state,
            attempt=job.attempt,
            progress=job.progress,
            completed_pages=job.completed_pages,
            total_pages=job.total_pages,
            pages=[
                PageDTO(
                    page_number=page.page_number,
                    status=page.state,
                    processing_attempts=page.processing_attempts,
                    internal_code=page.internal_code,
                    error_reason=page.error_reason,
                )
                for page in job.pages
            ],
            options=job.options,
            engine_name=job.engine_name,
            engine_version=job.engine_version,
            model_name=job.model_name,
            internal_code=job.internal_code,
            error_reason=job.error_reason,
            created_at=job.created_at,
            updated_at=job.updated_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
        )


class JobListDTO(BaseModel):
    items: list[JobDTO]
    total: int
    page: int
    page_size: int


class ArtifactDTO(BaseModel):
    kind: str
    object_key: str
    download_url: str
    sha256: str
    size_bytes: int
    content_type: str
    page_number: int | None

    @classmethod
    def from_domain(cls, artifact: Artifact, download_url: str) -> ArtifactDTO:
        return cls(
            kind=artifact.kind,
            object_key=artifact.object_key,
            download_url=download_url,
            sha256=artifact.sha256,
            size_bytes=artifact.size_bytes,
            content_type=artifact.content_type,
            page_number=artifact.page_number,
        )


class ArtifactListDTO(BaseModel):
    items: list[ArtifactDTO]


class JobEventDTO(BaseModel):
    event_id: int
    job_id: UUID
    event_type: str
    status: str
    progress: float
    payload: dict[str, Any]
    occurred_at: datetime

    @classmethod
    def from_domain(cls, event: JobEvent) -> JobEventDTO:
        return cls(
            event_id=event.sequence,
            job_id=event.job_id,
            event_type=event.event_type,
            status=event.state,
            progress=event.progress,
            payload=event.payload,
            occurred_at=event.occurred_at,
        )


class HealthDTO(BaseModel):
    status: str
    checks: dict[str, str] = Field(default_factory=dict)


def upload_from_request(request: CreateUploadRequest, owner_id: str, object_key: str) -> Upload:
    return Upload(
        owner_id=owner_id,
        filename=request.filename,
        size_bytes=request.size_bytes,
        content_type=request.content_type,
        sha256=request.sha256,
        object_key=object_key,
    )

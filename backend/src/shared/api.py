from __future__ import annotations

from datetime import UTC, datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.shared.internal_status_codes import InternalStatusCode

T = TypeVar("T")


class ApiEnvelope(BaseModel, Generic[T]):
    """The only JSON response shape exposed by backend HTTP interfaces."""

    model_config = ConfigDict(extra="forbid")

    internal_code: InternalStatusCode
    message: str = Field(min_length=1)
    data: T | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    request_id: str = Field(min_length=1)
    error_reason: str | None = None

    @model_validator(mode="after")
    def validate_success_failure_semantics(self) -> ApiEnvelope[T]:
        if self.internal_code is InternalStatusCode.SUCCESS:
            if self.error_reason is not None:
                raise ValueError("successful envelope cannot have error_reason")
        elif not self.error_reason:
            raise ValueError("failed envelope requires error_reason")
        return self

    @classmethod
    def success(cls, data: T, *, request_id: str, message: str = "操作成功") -> ApiEnvelope[T]:
        return cls(
            internal_code=InternalStatusCode.SUCCESS,
            message=message,
            data=data,
            request_id=request_id,
        )

    @classmethod
    def failure(
        cls,
        internal_code: InternalStatusCode,
        *,
        message: str,
        request_id: str,
        error_reason: str,
        data: T | None = None,
    ) -> ApiEnvelope[T]:
        return cls(
            internal_code=internal_code,
            message=message,
            data=data,
            request_id=request_id,
            error_reason=error_reason,
        )

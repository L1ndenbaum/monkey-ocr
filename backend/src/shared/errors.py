from __future__ import annotations

from typing import Any

from .api import InternalStatusCode


class BusinessError(Exception):
    """A controlled business outcome that must be returned with HTTP 200."""

    def __init__(
        self,
        internal_code: InternalStatusCode,
        message: str,
        error_reason: str,
        *,
        data: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.internal_code = internal_code
        self.message = message
        self.error_reason = error_reason
        self.data = data


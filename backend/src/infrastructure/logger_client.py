from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid6 import uuid7

from src.shared.api import ApiEnvelope, InternalStatusCode


SAFE_IDENTITY_FIELDS = {"api_key_id", "api_key_fingerprint", "content_type"}


def is_sensitive_field(key: object) -> bool:
    normalized = str(key).strip().lower()
    if normalized in SAFE_IDENTITY_FIELDS:
        return False
    if normalized in {
        "authorization",
        "api_key",
        "content",
        "document_content",
        "file_content",
        "markdown",
        "ocr_content",
        "ocr_text",
        "presigned_url",
        "request_body",
        "response_body",
    }:
        return True
    return any(
        marker in normalized
        for marker in ("password", "secret", "token", "presigned", "api_key_value")
    )


def sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]"
            if is_sensitive_field(key)
            else sanitize_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_value(item) for item in value]
    return value


def sanitize_fields(fields: dict[str, Any]) -> dict[str, Any]:
    return sanitize_value(fields)


class LoggerHTTPResponse(Protocol):
    status_code: int

    def json(self) -> Any: ...


class LoggerHTTPClient(Protocol):
    async def post(self, url: str, **kwargs: Any) -> LoggerHTTPResponse: ...


class LoggerClient:
    """Best-effort structured logger client for the logging service."""

    def __init__(
        self,
        *,
        base_url: str,
        client: LoggerHTTPClient,
        service_token: str,
        service_name: str = "monkeyocr-backend",
        timeout_seconds: float = 2,
    ) -> None:
        self.url = f"{base_url.rstrip('/')}/v1/log-events"
        self.client = client
        self.service_token = service_token
        self.service_name = service_name
        self.timeout_seconds = timeout_seconds
        self.fallback = logging.getLogger(service_name)

    async def info(self, event: str, **fields: Any) -> None:
        await self._send("info", event, fields)

    async def error(self, event: str, **fields: Any) -> None:
        await self._send("error", event, fields)

    async def _send(self, level: str, event: str, fields: dict[str, Any]) -> None:
        safe_fields = sanitize_fields(fields)
        trace_id = str(safe_fields.get("request_id") or safe_fields.get("trace_id") or "")
        payload = {
            "event": {
                "event_id": str(uuid7()),
                "timestamp": datetime.now(UTC).isoformat(),
                "level": level.upper(),
                "service": self.service_name,
                "message": event,
                "trace_id": trace_id,
                "metadata": safe_fields,
            }
        }
        try:
            response = await self.client.post(
                self.url,
                json=payload,
                headers={"X-Logging-Service-Token": self.service_token},
                timeout=self.timeout_seconds,
            )
            envelope = ApiEnvelope[dict[str, Any]].model_validate(response.json())
            if (
                response.status_code != 200
                or envelope.internal_code is not InternalStatusCode.SUCCESS
                or envelope.data is None
                or envelope.data.get("accepted") != 1
            ):
                raise RuntimeError(
                    "logging-service rejected event: "
                    f"http_status={response.status_code} "
                    f"internal_code={int(envelope.internal_code)}"
                )
        except Exception:
            self.fallback.log(
                logging.ERROR if level == "error" else logging.INFO,
                json.dumps(payload, ensure_ascii=False, default=str),
            )


class StdlibStructuredLogger:
    def __init__(self, service_name: str = "monkeyocr-backend") -> None:
        self.logger = logging.getLogger(service_name)

    async def info(self, event: str, **fields: Any) -> None:
        self._write(logging.INFO, event, fields)

    async def error(self, event: str, **fields: Any) -> None:
        self._write(logging.ERROR, event, fields)

    def _write(self, level: int, event: str, fields: dict[str, Any]) -> None:
        self.logger.log(
            level,
            json.dumps(
                {"event": event, **sanitize_fields(fields)},
                ensure_ascii=False,
                default=str,
            ),
        )

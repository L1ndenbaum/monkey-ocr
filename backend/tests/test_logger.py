from __future__ import annotations

import logging
from typing import Any

from src.infrastructure.logger_client import LoggerClient, sanitize_fields


def test_logger_redacts_sensitive_fields_recursively() -> None:
    result = sanitize_fields(
        {
            "request_id": "request",
            "nested": {"authorization": "Bearer secret"},
            "items": [{"presigned_url": "https://secret"}],
        }
    )
    assert result["nested"]["authorization"] == "[REDACTED]"
    assert result["items"][0]["presigned_url"] == "[REDACTED]"


def test_logger_redacts_secret_like_keys_but_keeps_operational_identity() -> None:
    result = sanitize_fields(
        {
            "database_password": "secret",
            "service_token": "token",
            "nested": {"markdown": "private OCR", "content_type": "application/pdf"},
            "api_key_id": "safe-id",
        }
    )

    assert result == {
        "database_password": "[REDACTED]",
        "service_token": "[REDACTED]",
        "nested": {"markdown": "[REDACTED]", "content_type": "application/pdf"},
        "api_key_id": "safe-id",
    }


class Response:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, Any]:
        return self.payload


class Client:
    def __init__(self, response: Response) -> None:
        self.response = response

    async def post(self, url: str, **kwargs: Any) -> Response:
        return self.response


def envelope(
    data: Any, *, internal_code: int = 0, error_reason: str | None = None
) -> dict[str, Any]:
    return {
        "internal_code": internal_code,
        "message": "操作成功" if internal_code == 0 else "日志事件无效",
        "data": data,
        "timestamp": "2026-07-11T00:00:00Z",
        "request_id": "request",
        "error_reason": error_reason,
    }


async def test_logger_accepts_successful_api_envelope(caplog: Any) -> None:
    service_name = "monkeyocr-logger-success-test"
    caplog.set_level(logging.INFO, logger=service_name)
    logger = LoggerClient(
        base_url="http://logging:13004",
        client=Client(Response(envelope({"accepted": 1}))),
        service_token="token",
        service_name=service_name,
    )

    await logger.info("ocr_job_succeeded", request_id="request")

    assert caplog.records == []


async def test_logger_falls_back_for_http_200_business_error(caplog: Any) -> None:
    service_name = "monkeyocr-logger-rejection-test"
    caplog.set_level(logging.INFO, logger=service_name)
    logger = LoggerClient(
        base_url="http://logging:13004",
        client=Client(
            Response(
                envelope(
                    None,
                    internal_code=10001,
                    error_reason="invalid_log_event",
                )
            )
        ),
        service_token="token",
        service_name=service_name,
    )

    await logger.info("ocr_job_succeeded", request_id="request")

    assert len(caplog.records) == 1
    assert "ocr_job_succeeded" in caplog.records[0].message

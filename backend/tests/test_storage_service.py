from __future__ import annotations

from typing import Any

import pytest

from src.infrastructure.storage import StorageServiceObjectStorage


class Response:
    def __init__(
        self,
        payload: dict[str, Any],
        status_code: int = 200,
        *,
        content: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.payload = payload
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}

    def json(self) -> dict[str, Any]:
        return self.payload


class Client:
    def __init__(self, response: Response) -> None:
        self.response = response
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def post(self, url: str, **kwargs: Any) -> Response:
        self.calls.append(("POST", url, kwargs))
        return self.response

    async def get(self, url: str, **kwargs: Any) -> Response:
        self.calls.append(("GET", url, kwargs))
        return self.response

    async def put(self, url: str, **kwargs: Any) -> Response:
        self.calls.append(("PUT", url, kwargs))
        return self.response


def envelope(data: Any, internal_code: int = 0, reason: str | None = None) -> dict[str, Any]:
    return {
        "internal_code": internal_code,
        "message": "操作成功" if internal_code == 0 else "资源不存在",
        "data": data,
        "timestamp": "2026-07-11T00:00:00Z",
        "request_id": "request",
        "error_reason": reason,
    }


async def test_storage_service_creates_multipart_target() -> None:
    client = Client(
        Response(
            envelope(
                {
                    "upload_id": "multipart-id",
                    "parts": [
                        {"part_number": 1, "url": "https://objects/part-1"},
                        {"part_number": 2, "url": "https://objects/part-2"},
                    ],
                }
            )
        )
    )
    storage = StorageServiceObjectStorage(
        base_url="http://storage:13003",
        service_token="token",
        bucket="monkeyocr-documents",
        client=client,
        multipart_threshold_bytes=8,
        multipart_part_size_bytes=8,
    )

    target = await storage.create_upload_target(
        "uploads/id/source",
        content_type="application/pdf",
        size_bytes=9,
        sha256="a" * 64,
    )

    assert target.upload_id == "multipart-id"
    assert target.part_urls == (
        (1, "https://objects/part-1"),
        (2, "https://objects/part-2"),
    )
    assert client.calls[0][2]["headers"]["X-Storage-Service-Token"] == "token"


async def test_storage_service_maps_enveloped_not_found_to_none() -> None:
    client = Client(Response(envelope(None, 10002, "resource_not_found")))
    storage = StorageServiceObjectStorage(
        base_url="http://storage:13003",
        service_token="token",
        bucket="monkeyocr-documents",
        client=client,
    )

    assert await storage.stat("missing") is None


async def test_storage_service_returns_raw_object_bytes() -> None:
    client = Client(
        Response({}, content=b"raw-object", headers={"Content-Type": "image/png"})
    )
    storage = StorageServiceObjectStorage(
        base_url="http://storage:13003",
        service_token="token",
        bucket="monkeyocr-documents",
        client=client,
    )

    assert await storage.get_bytes("jobs/id/page.png") == b"raw-object"


async def test_storage_service_maps_http_200_raw_get_not_found_envelope() -> None:
    client = Client(
        Response(
            envelope(None, 10002, "object_not_found"),
            content=b'{"internal_code":10002}',
            headers={"X-MonkeyOCR-Internal-Code": "10002"},
        )
    )
    storage = StorageServiceObjectStorage(
        base_url="http://storage:13003",
        service_token="token",
        bucket="monkeyocr-documents",
        client=client,
    )

    with pytest.raises(FileNotFoundError, match="object_not_found"):
        await storage.get_bytes("missing")


async def test_storage_service_rejects_http_200_raw_get_failure_envelope() -> None:
    client = Client(
        Response(
            envelope(None, 50003, "storage_unavailable"),
            content=b'{"internal_code":50003}',
            headers={"X-MonkeyOCR-Internal-Code": "50003"},
        )
    )
    storage = StorageServiceObjectStorage(
        base_url="http://storage:13003",
        service_token="token",
        bucket="monkeyocr-documents",
        client=client,
    )

    with pytest.raises(RuntimeError, match=r"storage_unavailable \(50003\)"):
        await storage.get_bytes("temporarily-unavailable")


async def test_storage_service_deletes_object_through_internal_endpoint() -> None:
    client = Client(Response(envelope({"status": "deleted"})))
    storage = StorageServiceObjectStorage(
        base_url="http://storage:13003",
        service_token="token",
        bucket="monkeyocr-documents",
        client=client,
    )

    await storage.delete_object("jobs/id/manifest.json")

    assert client.calls == [
        (
            "POST",
            "http://storage:13003/objects/delete",
            {
                "headers": {"X-Storage-Service-Token": "token"},
                "json": {
                    "bucket": "monkeyocr-documents",
                    "object_key": "jobs/id/manifest.json",
                },
            },
        )
    ]


async def test_storage_service_aborts_multipart_upload() -> None:
    client = Client(Response(envelope({"status": "aborted"})))
    storage = StorageServiceObjectStorage(
        base_url="http://storage:13003",
        service_token="token",
        bucket="monkeyocr-documents",
        client=client,
    )

    await storage.abort_multipart_upload("uploads/id/source", "multipart-id")

    assert client.calls[0][1] == "http://storage:13003/multipart/abort"
    assert client.calls[0][2]["json"] == {
        "bucket": "monkeyocr-documents",
        "object_key": "uploads/id/source",
        "upload_id": "multipart-id",
        "parts": [],
    }

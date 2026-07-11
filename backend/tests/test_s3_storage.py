from __future__ import annotations

from typing import Any

from src.infrastructure.storage import S3ObjectStorage


class S3ClientStub:
    def __init__(self) -> None:
        self.deleted: list[dict[str, Any]] = []
        self.aborted: list[dict[str, Any]] = []

    async def delete_object(self, **kwargs: Any) -> dict[str, Any]:
        self.deleted.append(kwargs)
        return {}

    async def abort_multipart_upload(self, **kwargs: Any) -> dict[str, Any]:
        self.aborted.append(kwargs)
        return {}


class NoSuchUploadError(Exception):
    response = {"Error": {"Code": "NoSuchUpload"}}


class MissingMultipartS3ClientStub(S3ClientStub):
    async def abort_multipart_upload(self, **kwargs: Any) -> dict[str, Any]:
        raise NoSuchUploadError


async def test_s3_storage_delete_is_scoped_to_configured_bucket() -> None:
    client = S3ClientStub()
    storage = S3ObjectStorage(
        client=client,  # type: ignore[arg-type]
        bucket="monkeyocr-documents",
    )

    await storage.delete_object("jobs/id/result.md")

    assert client.deleted == [
        {"Bucket": "monkeyocr-documents", "Key": "jobs/id/result.md"}
    ]


async def test_s3_storage_aborts_multipart_upload() -> None:
    client = S3ClientStub()
    storage = S3ObjectStorage(
        client=client,  # type: ignore[arg-type]
        bucket="monkeyocr-documents",
    )

    await storage.abort_multipart_upload("uploads/id/source", "multipart-id")

    assert client.aborted == [
        {
            "Bucket": "monkeyocr-documents",
            "Key": "uploads/id/source",
            "UploadId": "multipart-id",
        }
    ]


async def test_s3_storage_treats_missing_multipart_upload_as_already_aborted() -> None:
    storage = S3ObjectStorage(
        client=MissingMultipartS3ClientStub(),  # type: ignore[arg-type]
        bucket="monkeyocr-documents",
    )

    await storage.abort_multipart_upload("uploads/id/source", "multipart-id")

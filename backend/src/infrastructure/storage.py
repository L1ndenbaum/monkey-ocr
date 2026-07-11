from __future__ import annotations

import hashlib
from typing import Any, Protocol
from urllib.parse import quote

from src.contexts.ocr.application.ports import ObjectInfo, StoredObject, UploadTarget


class AsyncS3Client(Protocol):
    async def generate_presigned_url(
        self, operation_name: str, *, Params: dict[str, Any], ExpiresIn: int
    ) -> str: ...

    async def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]: ...

    async def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]: ...

    async def put_object(self, **kwargs: Any) -> dict[str, Any]: ...

    async def create_multipart_upload(self, **kwargs: Any) -> dict[str, Any]: ...

    async def complete_multipart_upload(self, **kwargs: Any) -> dict[str, Any]: ...

    async def delete_object(self, **kwargs: Any) -> dict[str, Any]: ...

    async def abort_multipart_upload(self, **kwargs: Any) -> dict[str, Any]: ...


class S3ObjectStorage:
    """S3/MinIO adapter; clients are injected so it can be contract-tested."""

    def __init__(
        self,
        *,
        client: AsyncS3Client,
        bucket: str,
        presign_ttl_seconds: int = 900,
        multipart_threshold_bytes: int = 16 * 1024 * 1024,
        multipart_part_size_bytes: int = 8 * 1024 * 1024,
    ) -> None:
        self.client = client
        self.bucket = bucket
        self.presign_ttl_seconds = presign_ttl_seconds
        self.multipart_threshold_bytes = multipart_threshold_bytes
        self.multipart_part_size_bytes = multipart_part_size_bytes

    async def create_upload_target(
        self,
        object_key: str,
        *,
        content_type: str,
        size_bytes: int,
        sha256: str,
    ) -> UploadTarget:
        params = {
            "Bucket": self.bucket,
            "Key": object_key,
            "ContentType": content_type,
            "Metadata": {"sha256": sha256, "expected-size": str(size_bytes)},
        }
        if size_bytes >= self.multipart_threshold_bytes:
            created = await self.client.create_multipart_upload(**params)
            upload_id = str(created["UploadId"])
            part_count = (size_bytes + self.multipart_part_size_bytes - 1) // self.multipart_part_size_bytes
            parts: list[tuple[int, str]] = []
            for part_number in range(1, part_count + 1):
                part_url = await self.client.generate_presigned_url(
                    "upload_part",
                    Params={
                        "Bucket": self.bucket,
                        "Key": object_key,
                        "UploadId": upload_id,
                        "PartNumber": part_number,
                    },
                    ExpiresIn=self.presign_ttl_seconds,
                )
                parts.append((part_number, part_url))
            return UploadTarget(
                url="",
                upload_id=upload_id,
                part_size_bytes=self.multipart_part_size_bytes,
                part_urls=tuple(parts),
            )
        url = await self.client.generate_presigned_url(
            "put_object", Params=params, ExpiresIn=self.presign_ttl_seconds
        )
        return UploadTarget(
            url=url,
            headers={
                "Content-Type": content_type,
                "x-amz-meta-sha256": sha256,
                "x-amz-meta-expected-size": str(size_bytes),
            },
        )

    async def complete_upload(
        self,
        object_key: str,
        *,
        upload_id: str | None,
        parts: list[tuple[int, str]],
    ) -> None:
        if upload_id is None:
            return
        if not parts:
            raise ValueError("multipart completion requires parts")
        await self.client.complete_multipart_upload(
            Bucket=self.bucket,
            Key=object_key,
            UploadId=upload_id,
            MultipartUpload={
                "Parts": [
                    {"PartNumber": part_number, "ETag": etag}
                    for part_number, etag in sorted(parts)
                ]
            },
        )

    async def stat(self, object_key: str) -> ObjectInfo | None:
        try:
            response = await self.client.head_object(Bucket=self.bucket, Key=object_key)
        except Exception as exc:
            if self._is_not_found(exc):
                return None
            raise
        metadata = response.get("Metadata") or {}
        return ObjectInfo(
            object_key=object_key,
            size_bytes=int(response["ContentLength"]),
            sha256=metadata.get("sha256"),
            content_type=response.get("ContentType", "application/octet-stream"),
        )

    async def get_bytes(self, object_key: str) -> bytes:
        response = await self.client.get_object(Bucket=self.bucket, Key=object_key)
        body = response["Body"]
        return await body.read()

    async def put_bytes(
        self, object_key: str, data: bytes, *, content_type: str
    ) -> StoredObject:
        digest = hashlib.sha256(data).hexdigest()
        await self.client.put_object(
            Bucket=self.bucket,
            Key=object_key,
            Body=data,
            ContentType=content_type,
            Metadata={"sha256": digest},
        )
        return StoredObject(
            object_key=object_key,
            size_bytes=len(data),
            sha256=digest,
            content_type=content_type,
        )

    async def delete_object(self, object_key: str) -> None:
        await self.client.delete_object(Bucket=self.bucket, Key=object_key)

    async def abort_multipart_upload(
        self, object_key: str, upload_id: str
    ) -> None:
        try:
            await self.client.abort_multipart_upload(
                Bucket=self.bucket, Key=object_key, UploadId=upload_id
            )
        except Exception as exc:
            if not self._is_no_such_upload(exc):
                raise

    async def create_download_url(self, object_key: str) -> str:
        return await self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": object_key},
            ExpiresIn=self.presign_ttl_seconds,
        )

    @staticmethod
    def _is_not_found(exc: Exception) -> bool:
        response = getattr(exc, "response", None)
        if not isinstance(response, dict):
            return False
        error = response.get("Error") or {}
        return error.get("Code") in {"404", "NoSuchKey", "NotFound"}

    @staticmethod
    def _is_no_such_upload(exc: Exception) -> bool:
        response = getattr(exc, "response", None)
        if not isinstance(response, dict):
            return False
        error = response.get("Error") or {}
        return error.get("Code") == "NoSuchUpload"


class StorageHTTPResponse(Protocol):
    status_code: int
    content: bytes
    headers: Any

    def json(self) -> Any: ...


class StorageHTTPClient(Protocol):
    async def post(self, url: str, **kwargs: Any) -> StorageHTTPResponse: ...

    async def get(self, url: str, **kwargs: Any) -> StorageHTTPResponse: ...

    async def put(self, url: str, **kwargs: Any) -> StorageHTTPResponse: ...


class StorageServiceObjectStorage:
    """Object storage adapter for the repository-owned Go storage-service."""

    _INTERNAL_CODE_HEADER = "x-monkeyocr-internal-code"

    def __init__(
        self,
        *,
        base_url: str,
        service_token: str,
        bucket: str,
        client: StorageHTTPClient,
        presign_ttl_seconds: int = 900,
        multipart_threshold_bytes: int = 16 * 1024 * 1024,
        multipart_part_size_bytes: int = 8 * 1024 * 1024,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.service_token = service_token
        self.bucket = bucket
        self.client = client
        self.presign_ttl_seconds = presign_ttl_seconds
        self.multipart_threshold_bytes = multipart_threshold_bytes
        self.multipart_part_size_bytes = multipart_part_size_bytes

    @property
    def _headers(self) -> dict[str, str]:
        return {"X-Storage-Service-Token": self.service_token}

    async def create_upload_target(
        self,
        object_key: str,
        *,
        content_type: str,
        size_bytes: int,
        sha256: str,
    ) -> UploadTarget:
        if size_bytes >= self.multipart_threshold_bytes:
            part_count = (size_bytes + self.multipart_part_size_bytes - 1) // self.multipart_part_size_bytes
            response = await self.client.post(
                f"{self.base_url}/multipart/create",
                headers=self._headers,
                json={
                    "bucket": self.bucket,
                    "object_key": object_key,
                    "content_type": content_type,
                    "metadata": {"sha256": sha256, "expected-size": str(size_bytes)},
                    "part_count": part_count,
                    "expires_in": self.presign_ttl_seconds,
                },
            )
            data = self._unwrap(response)
            return UploadTarget(
                url="",
                upload_id=str(data["upload_id"]),
                part_size_bytes=self.multipart_part_size_bytes,
                part_urls=tuple(
                    (int(part["part_number"]), str(part["url"]))
                    for part in data["parts"]
                ),
            )
        response = await self.client.post(
            f"{self.base_url}/presign/put",
            headers=self._headers,
            json={
                "bucket": self.bucket,
                "object_key": object_key,
                "content_type": content_type,
                "expires_in": self.presign_ttl_seconds,
            },
        )
        data = self._unwrap(response)
        return UploadTarget(
            url=str(data["url"]),
            headers={"Content-Type": content_type},
        )

    async def complete_upload(
        self,
        object_key: str,
        *,
        upload_id: str | None,
        parts: list[tuple[int, str]],
    ) -> None:
        if upload_id is None:
            return
        response = await self.client.post(
            f"{self.base_url}/multipart/complete",
            headers=self._headers,
            json={
                "bucket": self.bucket,
                "object_key": object_key,
                "upload_id": upload_id,
                "parts": [
                    {"part_number": number, "etag": etag}
                    for number, etag in sorted(parts)
                ],
            },
        )
        self._unwrap(response)

    async def stat(self, object_key: str) -> ObjectInfo | None:
        response = await self.client.post(
            f"{self.base_url}/objects/stat",
            headers=self._headers,
            json={"bucket": self.bucket, "object_key": object_key, "expires_in": 0},
        )
        try:
            data = self._unwrap(response)
        except FileNotFoundError:
            return None
        metadata = data.get("metadata") or {}
        return ObjectInfo(
            object_key=object_key,
            size_bytes=int(data["size"]),
            sha256=metadata.get("sha256"),
            content_type=str(data.get("content_type") or "application/octet-stream"),
        )

    async def get_bytes(self, object_key: str) -> bytes:
        response = await self.client.get(
            self._object_url(object_key), headers=self._headers
        )
        if self._is_enveloped_response(response):
            self._unwrap(response)
            raise RuntimeError(
                "storage-service returned an unexpected success envelope for object data"
            )
        if response.status_code != 200:
            if response.status_code == 404:
                raise FileNotFoundError(object_key)
            raise RuntimeError(
                f"storage-service returned HTTP {response.status_code} for object data"
            )
        return bytes(response.content)

    async def put_bytes(
        self, object_key: str, data: bytes, *, content_type: str
    ) -> StoredObject:
        response = await self.client.put(
            self._object_url(object_key),
            headers={**self._headers, "Content-Type": content_type},
            content=data,
        )
        self._unwrap(response)
        return StoredObject(
            object_key=object_key,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            content_type=content_type,
        )

    async def delete_object(self, object_key: str) -> None:
        response = await self.client.post(
            f"{self.base_url}/objects/delete",
            headers=self._headers,
            json={"bucket": self.bucket, "object_key": object_key},
        )
        self._unwrap(response)

    async def abort_multipart_upload(
        self, object_key: str, upload_id: str
    ) -> None:
        response = await self.client.post(
            f"{self.base_url}/multipart/abort",
            headers=self._headers,
            json={
                "bucket": self.bucket,
                "object_key": object_key,
                "upload_id": upload_id,
                "parts": [],
            },
        )
        self._unwrap(response)

    async def create_download_url(self, object_key: str) -> str:
        response = await self.client.post(
            f"{self.base_url}/presign/get",
            headers=self._headers,
            json={
                "bucket": self.bucket,
                "object_key": object_key,
                "expires_in": self.presign_ttl_seconds,
            },
        )
        return str(self._unwrap(response)["url"])

    def _object_url(self, object_key: str) -> str:
        return f"{self.base_url}/objects/{quote(self.bucket, safe='')}/{quote(object_key, safe='/')}"

    @classmethod
    def _is_enveloped_response(cls, response: StorageHTTPResponse) -> bool:
        headers = response.headers
        if hasattr(headers, "items"):
            for name, _ in headers.items():
                if str(name).lower() == cls._INTERNAL_CODE_HEADER:
                    return True
        return False

    @staticmethod
    def _unwrap(response: StorageHTTPResponse) -> dict[str, Any]:
        if response.status_code != 200:
            if response.status_code == 404:
                raise FileNotFoundError("storage object not found")
            raise RuntimeError(f"storage-service returned HTTP {response.status_code}")
        payload = response.json()
        if not isinstance(payload, dict) or "internal_code" not in payload:
            raise RuntimeError("storage-service returned an invalid ApiEnvelope")
        internal_code = int(payload["internal_code"])
        if internal_code != 0:
            reason = str(payload.get("error_reason") or "storage_service_error")
            if internal_code == 10002 or reason in {
                "object_not_found",
                "resource_not_found",
                "storage_object_not_found",
            }:
                raise FileNotFoundError(reason)
            raise RuntimeError(f"storage-service failed: {reason} ({internal_code})")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("storage-service response data is invalid")
        return data

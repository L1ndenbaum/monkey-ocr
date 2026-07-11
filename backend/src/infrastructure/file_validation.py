from __future__ import annotations

from src.contexts.ocr.application.ports import FileValidationResult
from src.contexts.ocr.domain.models import Upload
from src.shared.api import InternalStatusCode
from src.shared.errors import BusinessError


class MagicBytesFileValidator:
    """Small dependency-free truth check before the sandbox parses a document."""

    _SIGNATURES: tuple[tuple[bytes, str], ...] = (
        (b"%PDF-", "application/pdf"),
        (b"\x89PNG\r\n\x1a\n", "image/png"),
        (b"\xff\xd8\xff", "image/jpeg"),
        (b"BM", "image/bmp"),
        (b"II*\x00", "image/tiff"),
        (b"MM\x00*", "image/tiff"),
        (b"RIFF", "image/webp"),
    )

    def __init__(self, *, max_image_pixels_hint_bytes: int = 100 * 1024 * 1024) -> None:
        self.max_image_pixels_hint_bytes = max_image_pixels_hint_bytes

    async def validate(self, upload: Upload, data: bytes) -> FileValidationResult:
        if len(data) != upload.size_bytes:
            raise BusinessError(
                InternalStatusCode.UPLOAD_HASH_MISMATCH,
                "上传对象大小不匹配",
                "upload_size_mismatch",
            )
        detected = self._detect(data)
        if detected is None:
            raise BusinessError(
                InternalStatusCode.UPLOAD_UNSUPPORTED_FILE_TYPE,
                "文件真实类型不受支持",
                "unknown_magic_bytes",
            )
        if detected == "image/webp" and data[8:12] != b"WEBP":
            raise BusinessError(
                InternalStatusCode.UPLOAD_SECURITY_REJECTED,
                "图片容器签名无效",
                "invalid_webp_signature",
            )
        if detected != upload.content_type:
            raise BusinessError(
                InternalStatusCode.UPLOAD_SECURITY_REJECTED,
                "声明类型与文件真实类型不一致",
                "content_type_mismatch",
                data={"declared": upload.content_type, "detected": detected},
            )
        if detected == "application/pdf" and b"/Encrypt" in data[: 2 * 1024 * 1024]:
            raise BusinessError(
                InternalStatusCode.UPLOAD_SECURITY_REJECTED,
                "暂不支持加密 PDF",
                "encrypted_pdf",
            )
        return FileValidationResult(detected_content_type=detected)

    def _detect(self, data: bytes) -> str | None:
        for signature, content_type in self._SIGNATURES:
            if data.startswith(signature):
                return content_type
        return None

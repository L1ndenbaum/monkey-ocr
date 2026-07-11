from __future__ import annotations

import asyncio
import base64
from collections.abc import Mapping
from typing import Any, Protocol

from src.contexts.ocr.application.exceptions import (
    EngineProtocolError,
    EngineTimeoutError,
    EngineUnavailableError,
)
from src.contexts.ocr.application.ports import OCRResult


class HTTPResponse(Protocol):
    status_code: int

    def json(self) -> Any: ...


class AsyncHTTPClient(Protocol):
    async def post(self, url: str, **kwargs: Any) -> HTTPResponse: ...


class FakeOCREngine:
    """Deterministic local engine with injectable transient failures."""

    def __init__(
        self,
        *,
        failures_before_success: int = 0,
        delay_seconds: float = 0,
        visualization: bytes | None = b"fake-visualization",
    ) -> None:
        self.failures_before_success = failures_before_success
        self.delay_seconds = delay_seconds
        self.visualization = visualization
        self.calls = 0

    async def recognize(
        self,
        *,
        image: bytes,
        page_number: int,
        options: dict[str, Any],
        request_id: str,
    ) -> OCRResult:
        self.calls += 1
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.calls <= self.failures_before_success:
            raise EngineUnavailableError("injected fake engine failure")
        digest = __import__("hashlib").sha256(image).hexdigest()
        return OCRResult(
            markdown=f"## Page {page_number}\n\nFake OCR {digest[:12]}",
            structured={
                "page_number": page_number,
                "blocks": [
                    {
                        "type": "text",
                        "text": f"Fake OCR {digest[:12]}",
                        "bbox": [0, 0, 1, 1],
                        "confidence": 1.0,
                    }
                ],
            },
            visualization=self.visualization,
            engine_metadata={
                "engine": "fake",
                "model": "fake-local",
                "version": "1",
                "request_id": request_id,
            },
        )


class PaddleOCRVLEngineAdapter:
    """Adapter for the official PaddleOCR-VL serving endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        client: AsyncHTTPClient,
        endpoint_path: str = "/layout-parsing",
        timeout_seconds: float = 300,
        model_name: str = "PaddleOCR-VL-1.6",
        engine_version: str = "3.6",
    ) -> None:
        self.url = f"{base_url.rstrip('/')}/{endpoint_path.lstrip('/')}"
        self.client = client
        self.timeout_seconds = timeout_seconds
        self.model_name = model_name
        self.engine_version = engine_version

    async def recognize(
        self,
        *,
        image: bytes,
        page_number: int,
        options: dict[str, Any],
        request_id: str,
    ) -> OCRResult:
        body = {
            "file": base64.b64encode(image).decode("ascii"),
            "fileType": 1,
            "useDocOrientationClassify": options.get("use_doc_orientation_classify", False),
            "useDocUnwarping": options.get("use_doc_unwarping", False),
            "useLayoutDetection": options.get("use_layout_detection", True),
            "useChartRecognition": options.get("use_chart_recognition", True),
            "visualize": options.get("visualize", True),
        }
        try:
            response = await self.client.post(
                self.url,
                json=body,
                headers={"X-Request-ID": request_id},
                timeout=self.timeout_seconds,
            )
        except TimeoutError as exc:
            raise EngineTimeoutError("PaddleOCR-VL request timed out") from exc
        except Exception as exc:
            if type(exc).__name__.lower().endswith("timeout"):
                raise EngineTimeoutError("PaddleOCR-VL request timed out") from exc
            raise EngineUnavailableError("PaddleOCR-VL is unavailable") from exc
        if response.status_code == 504:
            raise EngineTimeoutError("PaddleOCR-VL request timed out")
        if response.status_code >= 500:
            raise EngineUnavailableError(f"PaddleOCR-VL returned {response.status_code}")
        if response.status_code != 200:
            raise EngineProtocolError(f"PaddleOCR-VL returned {response.status_code}")
        try:
            payload = response.json()
        except Exception as exc:
            raise EngineProtocolError("PaddleOCR-VL returned invalid JSON") from exc
        if not isinstance(payload, Mapping):
            raise EngineProtocolError("PaddleOCR-VL response is not an object")
        if payload.get("errorCode") not in {None, 0, "0"}:
            raise EngineProtocolError(
                f"PaddleOCR-VL error: {payload.get('errorCode')}"
            )
        return self._parse_result(payload, page_number)

    def _parse_result(self, payload: Mapping[str, Any], page_number: int) -> OCRResult:
        result = payload.get("result", payload)
        if not isinstance(result, Mapping):
            raise EngineProtocolError("PaddleOCR-VL result is not an object")
        candidates = result.get("layoutParsingResults") or result.get("results") or [result]
        if not isinstance(candidates, list) or not candidates:
            raise EngineProtocolError("PaddleOCR-VL response has no parsing result")
        first = candidates[0]
        if not isinstance(first, Mapping):
            raise EngineProtocolError("PaddleOCR-VL parsing result is invalid")
        markdown_value = first.get("markdown") or result.get("markdown")
        if isinstance(markdown_value, Mapping):
            markdown_value = markdown_value.get("text") or markdown_value.get("markdown")
        if not isinstance(markdown_value, str):
            markdown_value = first.get("markdownText")
        if not isinstance(markdown_value, str):
            raise EngineProtocolError("PaddleOCR-VL response is missing markdown")
        visualization = None
        output_images = first.get("outputImages")
        if isinstance(output_images, Mapping):
            visualization = next(
                (
                    decoded
                    for value in output_images.values()
                    if (decoded := self._decode_optional_image(value)) is not None
                ),
                None,
            )
        if visualization is None:
            visualization = self._decode_optional_image(first.get("inputImage"))
        pruned_result = first.get("prunedResult")
        if not isinstance(pruned_result, Mapping):
            pruned_result = {}
        return OCRResult(
            markdown=markdown_value,
            structured={
                "page_number": page_number,
                "pruned_result": dict(pruned_result),
                "data_info": result.get("dataInfo"),
            },
            visualization=visualization,
            visualization_content_type=self._image_content_type(visualization),
            engine_metadata={
                "engine": "paddleocr-vl",
                "version": self.engine_version,
                "model": result.get("modelName") or payload.get("modelName") or self.model_name,
                "log_id": payload.get("logId"),
            },
        )

    @staticmethod
    def _decode_optional_image(value: Any) -> bytes | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            return base64.b64decode(value, validate=True)
        except ValueError:
            return None

    @staticmethod
    def _image_content_type(value: bytes | None) -> str:
        if value and value.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if value and value.startswith(b"RIFF") and value[8:12] == b"WEBP":
            return "image/webp"
        return "image/jpeg"

import base64

import pytest

from src.contexts.ocr.application.exceptions import EngineTimeoutError, EngineUnavailableError
from src.infrastructure.engine import PaddleOCRVLEngineAdapter


class Response:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self.payload = payload

    def json(self):
        return self.payload


class Client:
    def __init__(self, response: Response) -> None:
        self.response = response
        self.request = None

    async def post(self, url: str, **kwargs):
        self.request = (url, kwargs)
        return self.response


@pytest.mark.asyncio
async def test_paddle_adapter_maps_official_layout_response() -> None:
    rendered = b"\x89PNG\r\n\x1a\nrendered"
    visualization = base64.b64encode(rendered).decode()
    client = Client(
        Response(
            200,
            {
                "errorCode": 0,
                "result": {
                    "layoutParsingResults": [
                        {
                            "markdown": {"text": "# OCR", "images": {"figure.jpg": "large"}},
                            "prunedResult": {"blocks": [{"label": "text"}]},
                            "outputImages": {"page": visualization},
                            "inputImage": base64.b64encode(b"original").decode(),
                        }
                    ],
                    "modelName": "PaddleOCR-VL",
                },
            },
        )
    )
    adapter = PaddleOCRVLEngineAdapter(base_url="http://engine", client=client)

    result = await adapter.recognize(
        image=b"image", page_number=1, options={}, request_id="req"
    )

    assert result.markdown == "# OCR"
    assert result.visualization == rendered
    assert result.visualization_content_type == "image/png"
    assert result.engine_metadata["model"] == "PaddleOCR-VL"
    assert result.engine_metadata["version"] == "3.6"
    assert result.structured["pruned_result"] == {"blocks": [{"label": "text"}]}
    assert "images" not in result.structured
    assert client.request[1]["json"]["visualize"] is True
    assert client.request[1]["json"]["file"] == base64.b64encode(b"image").decode()


@pytest.mark.asyncio
async def test_paddle_adapter_marks_5xx_as_transient() -> None:
    adapter = PaddleOCRVLEngineAdapter(
        base_url="http://engine", client=Client(Response(503, {}))
    )
    with pytest.raises(EngineUnavailableError):
        await adapter.recognize(
            image=b"image", page_number=1, options={}, request_id="req"
        )


@pytest.mark.asyncio
async def test_paddle_adapter_maps_gateway_timeout() -> None:
    adapter = PaddleOCRVLEngineAdapter(
        base_url="http://engine", client=Client(Response(504, {}))
    )
    with pytest.raises(EngineTimeoutError):
        await adapter.recognize(
            image=b"image", page_number=1, options={}, request_id="req"
        )

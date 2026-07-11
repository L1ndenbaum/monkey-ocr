from __future__ import annotations

import asyncio
import hashlib
from io import BytesIO

from PIL import Image

from infrastructure.sandbox.daemon import process_request
from src.contexts.ocr.domain.models import Job, Upload, UploadState
from src.infrastructure.memory import InMemoryObjectStorage
from src.infrastructure.preprocessor import DirectorySandboxPreprocessor


async def test_networkless_directory_sandbox_exchange(tmp_path) -> None:
    image = BytesIO()
    Image.new("RGB", (10, 7), "white").save(image, "PNG")
    source = image.getvalue()
    storage = InMemoryObjectStorage()
    await storage.put_bytes("uploads/source", source, content_type="image/png")
    upload = Upload(
        owner_id="owner",
        filename="scan.png",
        size_bytes=len(source),
        content_type="image/png",
        sha256=hashlib.sha256(source).hexdigest(),
        object_key="uploads/source",
        state=UploadState.COMPLETED,
        detected_content_type="image/png",
    )
    job = Job(owner_id="owner", upload_id=upload.id, request_id="request")
    preprocessor = DirectorySandboxPreprocessor(
        storage=storage,
        exchange_dir=str(tmp_path),
        timeout_seconds=2,
        poll_interval_seconds=0.01,
    )

    pending = asyncio.create_task(preprocessor.prepare(upload, job))
    request_file = None
    for _ in range(100):
        request_file = next(tmp_path.glob("*/request.json"), None)
        if request_file is not None:
            break
        await asyncio.sleep(0.01)
    assert request_file is not None
    process_request(request_file)
    pages = await asyncio.wait_for(pending, timeout=3)

    assert len(pages) == 1
    assert pages[0].page_number == 1
    assert await storage.get_bytes(pages[0].object_key)
    assert list(tmp_path.iterdir()) == []

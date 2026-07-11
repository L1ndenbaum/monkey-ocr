from __future__ import annotations

import hashlib
import json
import sys

import fitz
import pytest
from PIL import Image

from infrastructure.sandbox.validate_and_render import main, validate_and_render


def test_sandbox_normalizes_image_and_writes_relative_manifest(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "output"
    Image.new("RGB", (8, 6), "white").save(source, "PNG")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "validate_and_render",
            str(source),
            str(output),
            "--expected-sha256",
            digest,
        ],
    )

    assert main() == 0
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["detected_content_type"] == "image/png"
    assert manifest["pages"] == [
        {
            "page_number": 1,
            "path": "page-000001.png",
            "sha256": hashlib.sha256((output / "page-000001.png").read_bytes()).hexdigest(),
        }
    ]


def test_sandbox_rejects_oversized_pdf_page_before_rasterizing(tmp_path) -> None:
    source = tmp_path / "oversized.pdf"
    document = fitz.open()
    document.new_page(width=10_000, height=10_000)
    document.save(source)
    document.close()

    with pytest.raises(ValueError, match="image_pixel_limit"):
        validate_and_render(
            source,
            tmp_path / "output",
            expected_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            max_pixels=1_000_000,
        )

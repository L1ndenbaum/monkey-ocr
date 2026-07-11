"""Offline file validator and page renderer used by the restricted sandbox."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import fitz
import magic
from PIL import Image


ALLOWED_MIME = {"application/pdf", "image/jpeg", "image/png", "image/tiff", "image/webp", "image/bmp"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_pdf(
    source: Path,
    output: Path,
    max_pages: int,
    max_pixels: int,
    dpi: int,
) -> list[dict[str, object]]:
    document = fitz.open(source)
    if document.needs_pass:
        raise ValueError("encrypted_pdf")
    if document.page_count < 1 or document.page_count > max_pages:
        raise ValueError("invalid_page_count")
    scale = dpi / 72
    pages: list[dict[str, object]] = []
    for index, page in enumerate(document):
        width = int(page.rect.width * scale + 0.5)
        height = int(page.rect.height * scale + 0.5)
        if width <= 0 or height <= 0 or width * height > max_pixels:
            raise ValueError("image_pixel_limit")
        pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        page_path = output / f"page-{index + 1:06d}.png"
        pixmap.save(page_path)
        pages.append({"page_number": index + 1, "path": page_path.name, "sha256": sha256(page_path)})
    document.close()
    return pages


def normalize_image(source: Path, output: Path, max_pixels: int) -> list[dict[str, object]]:
    Image.MAX_IMAGE_PIXELS = max_pixels
    with Image.open(source) as image:
        image.verify()
    with Image.open(source) as image:
        if image.width * image.height > max_pixels:
            raise ValueError("image_pixel_limit")
        normalized = image.convert("RGB")
        page_path = output / "page-000001.png"
        normalized.save(page_path, "PNG", optimize=True)
    return [{"page_number": 1, "path": page_path.name, "sha256": sha256(page_path)}]


def validate_and_render(
    source: Path,
    output: Path,
    *,
    expected_sha256: str,
    max_pages: int = 500,
    max_pixels: int = 100_000_000,
    dpi: int = 180,
) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    actual_hash = sha256(source)
    if actual_hash != expected_sha256.lower():
        raise ValueError("hash_mismatch")
    mime = magic.from_file(str(source), mime=True)
    if mime not in ALLOWED_MIME:
        raise ValueError("unsupported_file_type")
    pages = (
        render_pdf(source, output, max_pages, max_pixels, dpi)
        if mime == "application/pdf"
        else normalize_image(source, output, max_pixels)
    )
    manifest: dict[str, object] = {
        "sha256": actual_hash,
        "detected_content_type": mime,
        "pages": pages,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--max-pages", type=int, default=500)
    parser.add_argument("--max-pixels", type=int, default=100_000_000)
    parser.add_argument("--dpi", type=int, default=180)
    args = parser.parse_args()
    manifest = validate_and_render(
        args.source,
        args.output,
        expected_sha256=args.expected_sha256,
        max_pages=args.max_pages,
        max_pixels=args.max_pixels,
        dpi=args.dpi,
    )
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

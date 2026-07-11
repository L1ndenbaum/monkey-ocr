from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil
import tempfile
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from src.contexts.ocr.application.exceptions import PreprocessingError
from src.contexts.ocr.application.ports import ObjectStorage, PreparedPage
from src.contexts.ocr.domain.models import Job, Upload


class PreprocessorHTTPResponse(Protocol):
    status_code: int

    def json(self) -> Any: ...


class PreprocessorHTTPClient(Protocol):
    async def post(self, url: str, **kwargs: Any) -> PreprocessorHTTPResponse: ...


class PassthroughDocumentPreprocessor:
    """Local fake-engine preprocessor: each validated input is one logical page."""

    async def prepare(self, upload: Upload, job: Job) -> list[PreparedPage]:
        return [PreparedPage(page_number=1, object_key=upload.object_key)]


class StaticDocumentPreprocessor:
    """Test adapter that persists configured normalized page images."""

    def __init__(self, storage: ObjectStorage, page_images: list[bytes]) -> None:
        self.storage = storage
        self.page_images = page_images

    async def prepare(self, upload: Upload, job: Job) -> list[PreparedPage]:
        pages: list[PreparedPage] = []
        for number, image in enumerate(self.page_images, start=1):
            key = f"jobs/{job.id}/attempts/{job.attempt}/pages/{number:06d}.png"
            await self.storage.put_bytes(key, image, content_type="image/png")
            pages.append(PreparedPage(page_number=number, object_key=key))
        return pages


class SandboxDocumentPreprocessorAdapter:
    """Calls an isolated parser that reads/writes object-store references."""

    def __init__(
        self,
        *,
        base_url: str,
        client: PreprocessorHTTPClient,
        timeout_seconds: float = 120,
    ) -> None:
        self.url = f"{base_url.rstrip('/')}/v1/documents/prepare"
        self.client = client
        self.timeout_seconds = timeout_seconds

    async def prepare(self, upload: Upload, job: Job) -> list[PreparedPage]:
        try:
            response = await self.client.post(
                self.url,
                json={
                    "schema_version": 1,
                    "source_object_key": upload.object_key,
                    "source_content_type": upload.detected_content_type,
                    "output_prefix": f"jobs/{job.id}/attempts/{job.attempt}/pages",
                    "request_id": job.request_id,
                },
                headers={"X-Request-ID": job.request_id},
                timeout=self.timeout_seconds,
            )
        except Exception as exc:
            raise PreprocessingError("sandbox preprocessor unavailable") from exc
        if response.status_code != 200:
            raise PreprocessingError(
                f"sandbox preprocessor returned {response.status_code}"
            )
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("pages"), list):
            raise PreprocessingError("sandbox preprocessor response is invalid")
        output_prefix = f"jobs/{job.id}/attempts/{job.attempt}/pages/"
        try:
            pages = []
            for expected_number, page in enumerate(payload["pages"], start=1):
                number = int(page["page_number"])
                object_key = str(page["object_key"])
                if number != expected_number:
                    raise ValueError("sandbox pages must be contiguous")
                if not object_key.startswith(output_prefix):
                    raise ValueError("sandbox page is outside the job prefix")
                pages.append(
                    PreparedPage(page_number=number, object_key=object_key)
                )
        except (KeyError, TypeError, ValueError) as exc:
            raise PreprocessingError("sandbox page descriptor is invalid") from exc
        if not pages:
            raise PreprocessingError("sandbox produced no pages")
        return pages


class DirectorySandboxPreprocessor:
    """Exchanges files with a network-disabled parser sidecar through a volume."""

    def __init__(
        self,
        *,
        storage: ObjectStorage,
        exchange_dir: str,
        timeout_seconds: float = 300,
        poll_interval_seconds: float = 0.1,
        max_pages: int = 500,
        max_pixels: int = 100_000_000,
        dpi: int = 180,
    ) -> None:
        self.storage = storage
        self.exchange_dir = Path(exchange_dir)
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.max_pages = max_pages
        self.max_pixels = max_pixels
        self.dpi = dpi

    async def prepare(self, upload: Upload, job: Job) -> list[PreparedPage]:
        request_dir = self.exchange_dir / f"{job.id}-{job.attempt}-{uuid4().hex}"
        output_dir = request_dir / "output"
        try:
            request_dir.mkdir(parents=True, mode=0o700)
            source = await self.storage.get_bytes(upload.object_key)
            (request_dir / "input").write_bytes(source)
            request = {
                "input": "input",
                "sha256": upload.sha256,
                "max_pages": self.max_pages,
                "max_pixels": self.max_pixels,
                "dpi": self.dpi,
                "request_id": job.request_id,
            }
            temporary = request_dir / "request.tmp"
            temporary.write_text(
                json.dumps(request, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            temporary.replace(request_dir / "request.json")

            response_path = request_dir / "response.json"
            deadline = asyncio.get_running_loop().time() + self.timeout_seconds
            while not response_path.exists():
                if asyncio.get_running_loop().time() >= deadline:
                    raise PreprocessingError("sandbox preprocessor timed out")
                await asyncio.sleep(self.poll_interval_seconds)
            response = json.loads(response_path.read_text(encoding="utf-8"))
            if not response.get("ok"):
                reason = str(response.get("error_reason") or "sandbox_failed")[:160]
                raise PreprocessingError(f"sandbox preprocessor rejected input: {reason}")
            return await self._upload_pages(output_dir, job)
        except PreprocessingError:
            raise
        except Exception as exc:
            raise PreprocessingError("sandbox exchange failed") from exc
        finally:
            shutil.rmtree(request_dir, ignore_errors=True)

    async def _upload_pages(self, output_dir: Path, job: Job) -> list[PreparedPage]:
        try:
            manifest = json.loads(
                (output_dir / "manifest.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise PreprocessingError("sandbox did not produce a valid manifest") from exc
        descriptors = manifest.get("pages") if isinstance(manifest, dict) else None
        if not isinstance(descriptors, list) or not (1 <= len(descriptors) <= self.max_pages):
            raise PreprocessingError("sandbox page count is invalid")
        pages: list[PreparedPage] = []
        root = output_dir.resolve()
        for expected_number, descriptor in enumerate(descriptors, start=1):
            if not isinstance(descriptor, dict):
                raise PreprocessingError("sandbox page descriptor is invalid")
            number = int(descriptor.get("page_number", expected_number))
            if number != expected_number:
                raise PreprocessingError("sandbox pages must be contiguous and one-based")
            relative_path = descriptor.get("path")
            if not isinstance(relative_path, str):
                raise PreprocessingError("sandbox page path is missing")
            page_path = (output_dir / relative_path).resolve()
            if root not in page_path.parents:
                raise PreprocessingError("sandbox page path escapes output directory")
            data = page_path.read_bytes()
            if not data:
                raise PreprocessingError("sandbox produced an empty page")
            object_key = f"jobs/{job.id}/attempts/{job.attempt}/pages/{number:06d}.png"
            await self.storage.put_bytes(object_key, data, content_type="image/png")
            pages.append(PreparedPage(page_number=number, object_key=object_key))
        return pages


class SubprocessSandboxPreprocessor:
    """Runs a configured isolation command without a shell and imports its page manifest."""

    def __init__(
        self,
        *,
        storage: ObjectStorage,
        command: str,
        timeout_seconds: float = 120,
        max_pages: int = 2_000,
    ) -> None:
        self.storage = storage
        self.command = tuple(shlex.split(command))
        self.timeout_seconds = timeout_seconds
        self.max_pages = max_pages
        if not self.command or not any("{input}" in item for item in self.command):
            raise ValueError("sandbox command must contain {input}")
        if not any("{output_dir}" in item for item in self.command):
            raise ValueError("sandbox command must contain {output_dir}")

    async def prepare(self, upload: Upload, job: Job) -> list[PreparedPage]:
        source = await self.storage.get_bytes(upload.object_key)
        suffix = ".pdf" if upload.detected_content_type == "application/pdf" else ".image"
        with tempfile.TemporaryDirectory(prefix="monkeyocr-sandbox-") as temp:
            root = Path(temp)
            input_path = root / f"input{suffix}"
            output_dir = root / "output"
            output_dir.mkdir(mode=0o700)
            await asyncio.to_thread(input_path.write_bytes, source)
            values = {
                "input": str(input_path),
                "output_dir": str(output_dir),
                "content_type": upload.detected_content_type or upload.content_type,
                "request_id": job.request_id,
                "sha256": upload.sha256,
            }
            argv = [argument.format_map(values) for argument in self.command]
            environment = {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "HOME": str(root),
                "TMPDIR": str(root),
                "LANG": "C.UTF-8",
            }
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=root,
                env=environment,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=self.timeout_seconds
                )
            except TimeoutError as exc:
                process.kill()
                await process.wait()
                raise PreprocessingError("sandbox preprocessor timed out") from exc
            if process.returncode != 0:
                safe_error = stderr.decode("utf-8", errors="replace")[-500:]
                raise PreprocessingError(
                    f"sandbox preprocessor failed with exit {process.returncode}: {safe_error}"
                )
            manifest_path = output_dir / "manifest.json"
            try:
                manifest = json.loads(await asyncio.to_thread(manifest_path.read_text, "utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise PreprocessingError("sandbox did not produce a valid manifest") from exc
            descriptors = manifest.get("pages") if isinstance(manifest, dict) else None
            if not isinstance(descriptors, list) or not (1 <= len(descriptors) <= self.max_pages):
                raise PreprocessingError("sandbox page count is invalid")
            pages: list[PreparedPage] = []
            for expected_number, descriptor in enumerate(descriptors, start=1):
                if not isinstance(descriptor, dict):
                    raise PreprocessingError("sandbox page descriptor is invalid")
                number = int(descriptor.get("page_number", expected_number))
                if number != expected_number:
                    raise PreprocessingError("sandbox pages must be contiguous and one-based")
                relative_path = descriptor.get("path")
                if not isinstance(relative_path, str):
                    raise PreprocessingError("sandbox page path is missing")
                page_path = (output_dir / relative_path).resolve()
                if output_dir.resolve() not in page_path.parents:
                    raise PreprocessingError("sandbox page path escapes output directory")
                data = await asyncio.to_thread(page_path.read_bytes)
                if not data:
                    raise PreprocessingError("sandbox produced an empty page")
                object_key = (
                    f"jobs/{job.id}/attempts/{job.attempt}/pages/{number:06d}.png"
                )
                await self.storage.put_bytes(object_key, data, content_type="image/png")
                pages.append(PreparedPage(page_number=number, object_key=object_key))
            return pages

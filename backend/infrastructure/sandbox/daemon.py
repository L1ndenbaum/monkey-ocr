"""Filesystem mailbox daemon for the network-isolated parser container."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

try:
    from .validate_and_render import validate_and_render
except ImportError:  # Executed as the standalone container entrypoint.
    from validate_and_render import validate_and_render


SANDBOX_HEARTBEAT_FILENAME = ".heartbeat.json"


def atomic_json(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    temporary.replace(path)


def process_request(request_file: Path) -> None:
    request_dir = request_file.parent
    claimed = request_dir / "processing.json"
    try:
        request_file.replace(claimed)
    except FileNotFoundError:
        return
    try:
        request = json.loads(claimed.read_text(encoding="utf-8"))
        source = (request_dir / str(request["input"])).resolve()
        output = (request_dir / "output").resolve()
        if request_dir.resolve() not in source.parents or request_dir.resolve() not in output.parents:
            raise ValueError("sandbox_path_escape")
        validate_and_render(
            source,
            output,
            expected_sha256=str(request["sha256"]),
            max_pages=int(request.get("max_pages", 500)),
            max_pixels=int(request.get("max_pixels", 100_000_000)),
            dpi=int(request.get("dpi", 180)),
        )
        atomic_json(request_dir / "response.json", {"ok": True})
    except Exception as exc:
        atomic_json(
            request_dir / "response.json",
            {"ok": False, "error_reason": str(exc)[:160] or type(exc).__name__},
        )


def write_heartbeat(root: Path, *, now: float | None = None) -> None:
    atomic_json(
        root / SANDBOX_HEARTBEAT_FILENAME,
        {"status": "ok", "updated_at_unix": time.time() if now is None else now},
    )


def heartbeat_loop(root: Path, *, interval_seconds: float = 1.0) -> None:
    while True:
        write_heartbeat(root)
        time.sleep(interval_seconds)


def main() -> int:
    root = Path(os.environ.get("SANDBOX_EXCHANGE_DIR", "/exchange"))
    root.mkdir(parents=True, exist_ok=True)
    interval = float(os.environ.get("SANDBOX_POLL_INTERVAL_SECONDS", "0.1"))
    threading.Thread(
        target=heartbeat_loop,
        args=(root,),
        name="monkeyocr-sandbox-heartbeat",
        daemon=True,
    ).start()
    while True:
        for request_file in root.glob("*/request.json"):
            process_request(request_file)
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())

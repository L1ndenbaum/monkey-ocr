#!/usr/bin/env python3
"""Generate the shared InternalStatusCode enum for Python, Go, and TypeScript."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "backend/contracts/internal_status_codes.json"


def load_statuses() -> list[dict[str, object]]:
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    statuses = [payload["success"], *payload["statuses"]]
    names = [str(item["name"]) for item in statuses]
    values = [int(item["value"]) for item in statuses]
    if len(names) != len(set(names)) or len(values) != len(set(values)):
        raise ValueError("status registry contains duplicate names or values")
    return statuses


def render_python(statuses: list[dict[str, object]]) -> str:
    lines = [
        '"""Generated from backend/contracts/internal_status_codes.json; do not edit."""',
        "",
        "from enum import IntEnum",
        "",
        "",
        "class InternalStatusCode(IntEnum):",
    ]
    lines.extend(f"    {item['name']} = {item['value']}" for item in statuses)
    lines.extend(["", "", '__all__ = ["InternalStatusCode"]', ""])
    return "\n".join(lines)


def render_go(statuses: list[dict[str, object]]) -> str:
    lines = [
        "// Code generated from backend/contracts/internal_status_codes.json; DO NOT EDIT.",
        "package api",
        "",
        "type InternalStatusCode int",
        "",
        "const (",
    ]
    lines.extend(
        f"\t{go_identifier(str(item['name']))} InternalStatusCode = {item['value']}"
        for item in statuses
    )
    lines.extend([
        ")",
        "",
        "// String returns the stable cross-language enum name used in structured logs.",
        "func (code InternalStatusCode) String() string {",
        "\tswitch code {",
    ])
    for item in statuses:
        lines.extend([
            f"\tcase {go_identifier(str(item['name']))}:",
            f'\t\treturn "{item["name"]}"',
        ])
    lines.extend(["\tdefault:", '\t\treturn "UNKNOWN"', "\t}", "}", ""])
    source = "\n".join(lines)
    result = subprocess.run(
        ["gofmt"],
        input=source,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout


def go_identifier(name: str) -> str:
    acronyms = {"API": "API", "ID": "ID", "OCR": "OCR"}
    parts = [acronyms.get(part, part.title()) for part in name.split("_")]
    return "InternalStatus" + "".join(parts)


def render_typescript(statuses: list[dict[str, object]]) -> str:
    lines = [
        "// Generated from backend/contracts/internal_status_codes.json; do not edit.",
        "export enum InternalStatusCode {",
    ]
    lines.extend(f"  {item['name']} = {item['value']}," for item in statuses)
    lines.extend(["}", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    statuses = load_statuses()
    outputs = {
        ROOT / "backend/src/shared/internal_status_codes.py": render_python(statuses),
        ROOT / "backend/services/lib-go/http/api/internal_status_codes_generated.go": render_go(statuses),
        ROOT / "frontend/src/domain/internalStatusCodes.generated.ts": render_typescript(statuses),
    }
    stale: list[Path] = []
    for path, content in outputs.items():
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                stale.append(path)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    if stale:
        for path in stale:
            print(f"stale generated file: {path.relative_to(ROOT)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

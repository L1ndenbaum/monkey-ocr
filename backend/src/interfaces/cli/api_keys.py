from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import sys
from dataclasses import dataclass
from typing import Any, Protocol

from src.infrastructure.api_keys import hash_api_key, verify_api_key


class DatabaseConnection(Protocol):
    async def fetchrow(self, query: str, *args: Any) -> Any: ...

    async def fetch(self, query: str, *args: Any) -> list[Any]: ...

    async def execute(self, query: str, *args: Any) -> str: ...

    async def close(self) -> None: ...


@dataclass(slots=True, frozen=True)
class GeneratedAPIKey:
    plaintext: str
    prefix: str
    salt: bytes
    digest: bytes


def generate_api_key(pepper: str) -> GeneratedAPIKey:
    prefix = secrets.token_urlsafe(9).replace("-", "A").replace("_", "B")[:12]
    plaintext = f"mocr_{prefix}_{secrets.token_urlsafe(32)}"
    salt = os.urandom(16)
    return GeneratedAPIKey(
        plaintext=plaintext,
        prefix=f"mocr_{prefix}",
        salt=salt,
        digest=hash_api_key(plaintext, salt=salt, pepper=pepper),
    )


async def create_key(connection: DatabaseConnection, *, name: str, pepper: str) -> str:
    generated = generate_api_key(pepper)
    row = await connection.fetchrow(
        """
        INSERT INTO api_keys (name, key_prefix, key_hash, salt, status)
        VALUES ($1, $2, $3, $4, 'active')
        RETURNING id
        """,
        name,
        generated.prefix,
        generated.digest,
        generated.salt,
    )
    key_id = row["id"]
    return (
        f"API key created: {key_id}\n"
        "Copy this value now; it cannot be recovered later:\n"
        f"{generated.plaintext}"
    )


async def list_keys(connection: DatabaseConnection) -> str:
    rows = await connection.fetch(
        """
        SELECT id, name, key_prefix, status, created_at, last_used_at, revoked_at
        FROM api_keys
        ORDER BY created_at DESC
        """
    )
    if not rows:
        return "No API keys found."
    lines = ["id\tstatus\tprefix\tname\tcreated_at\tlast_used_at"]
    for row in rows:
        lines.append(
            "\t".join(
                str(value or "-")
                for value in (
                    row["id"],
                    row["status"],
                    row["key_prefix"],
                    row["name"],
                    row["created_at"],
                    row["last_used_at"],
                )
            )
        )
    return "\n".join(lines)


async def revoke_key(connection: DatabaseConnection, *, identifier: str) -> str:
    result = await connection.execute(
        """
        UPDATE api_keys
        SET status = 'revoked', revoked_at = now(), updated_at = now()
        WHERE id::text = $1 OR key_prefix = $1
        """,
        identifier,
    )
    if result.endswith(" 0"):
        raise ValueError("API key was not found")
    return f"API key revoked: {identifier}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="monkeyocr-api-keys")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="issue a new API key")
    create.add_argument("--name", required=True)
    commands.add_parser("list", help="list API key metadata")
    revoke = commands.add_parser("revoke", help="revoke by UUID or key prefix")
    revoke.add_argument("identifier")
    return parser


async def _run(args: argparse.Namespace) -> str:
    database_url = os.environ.get("MONKEYOCR_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not database_url:
        raise ValueError("MONKEYOCR_DATABASE_URL is required")
    database_url = database_url.replace("postgresql+psycopg://", "postgresql://").replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    try:
        import asyncpg
    except ImportError as exc:
        raise RuntimeError("asyncpg is required to run the API key CLI") from exc
    connection = await asyncpg.connect(database_url)
    try:
        if args.command == "create":
            pepper = os.environ.get("MONKEYOCR_API_KEY_PEPPER", "")
            if not pepper:
                raise ValueError("MONKEYOCR_API_KEY_PEPPER is required for key creation")
            return await create_key(connection, name=args.name, pepper=pepper)
        if args.command == "list":
            return await list_keys(connection)
        if args.command == "revoke":
            return await revoke_key(connection, identifier=args.identifier)
        raise ValueError(f"unknown command: {args.command}")
    finally:
        await connection.close()


def main() -> int:
    try:
        output = asyncio.run(_run(build_parser().parse_args()))
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

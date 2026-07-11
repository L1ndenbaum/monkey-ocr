from __future__ import annotations

import hashlib
import hmac
from typing import Any, Protocol

from src.contexts.ocr.application.exceptions import (
    DatabaseUnavailableError,
    DependencyError,
)
from src.shared.api import InternalStatusCode
from src.shared.errors import BusinessError

PBKDF2_ITERATIONS = 600_000


def hash_api_key(plaintext: str, *, salt: bytes, pepper: str) -> bytes:
    if not pepper:
        raise ValueError("API key pepper must not be empty")
    return hashlib.pbkdf2_hmac(
        "sha256",
        plaintext.encode("utf-8") + pepper.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
        dklen=32,
    )


def verify_api_key(plaintext: str, *, salt: bytes, pepper: str, digest: bytes) -> bool:
    return hmac.compare_digest(hash_api_key(plaintext, salt=salt, pepper=pepper), digest)


def key_prefix(plaintext: str) -> str | None:
    parts = plaintext.split("_", 2)
    if len(parts) != 3 or parts[0] != "mocr" or not parts[1] or not parts[2]:
        return None
    return f"mocr_{parts[1]}"


class APIKeyAuthenticator(Protocol):
    async def authenticate(self, plaintext: str) -> str: ...


class PostgresAPIKeyAuthenticator:
    def __init__(self, *, pool: Any, pepper: str) -> None:
        self.pool = pool
        self.pepper = pepper

    async def authenticate(self, plaintext: str) -> str:
        prefix = key_prefix(plaintext)
        if prefix is None:
            raise self._unauthorized()
        try:
            async with self.pool.acquire() as connection:
                row = await connection.fetchrow(
                    "SELECT id,status,key_hash,salt FROM api_keys WHERE key_prefix=$1",
                    prefix,
                )
                if row is None:
                    raise self._unauthorized()
                if row["status"] == "revoked":
                    raise BusinessError(
                        InternalStatusCode.API_KEY_REVOKED,
                        "API Key 已被吊销",
                        "api_key_revoked",
                    )
                if not verify_api_key(
                    plaintext,
                    salt=bytes(row["salt"]),
                    pepper=self.pepper,
                    digest=bytes(row["key_hash"]),
                ):
                    raise self._unauthorized()
                await connection.execute(
                    "UPDATE api_keys SET last_used_at=now(), updated_at=now() WHERE id=$1",
                    row["id"],
                )
                return str(row["id"])
        except (BusinessError, DependencyError):
            raise
        except Exception as exc:
            raise DatabaseUnavailableError("API key database operation failed") from exc

    @staticmethod
    def _unauthorized() -> BusinessError:
        return BusinessError(
            InternalStatusCode.USER_UNAUTHORIZED,
            "API Key 无效或缺失",
            "user_unauthorized",
        )


class DevelopmentAPIKeyAuthenticator:
    def __init__(self, owner_id: str) -> None:
        self.owner_id = owner_id

    async def authenticate(self, plaintext: str) -> str:
        return self.owner_id

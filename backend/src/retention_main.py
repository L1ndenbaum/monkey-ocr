from __future__ import annotations

import argparse
import asyncio
import logging
from contextlib import AsyncExitStack, asynccontextmanager
from typing import AsyncIterator

from src.config import Settings, get_settings
from src.contexts.ocr.application.ports import ObjectStorage, StructuredLogger
from src.contexts.ocr.application.retention import RetentionCleanupService
from src.infrastructure.logger_client import LoggerClient, StdlibStructuredLogger
from src.infrastructure.persistence import AsyncpgRetentionRepository
from src.infrastructure.storage import S3ObjectStorage, StorageServiceObjectStorage


@asynccontextmanager
async def create_retention_service(
    settings: Settings,
) -> AsyncIterator[tuple[RetentionCleanupService, StructuredLogger]]:
    if settings.repository_adapter != "postgres" or not settings.database_url:
        raise RuntimeError("retention cleanup requires DATABASE_URL")

    import asyncpg
    import httpx

    async with AsyncExitStack() as stack:
        pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=2)
        stack.push_async_callback(pool.close)
        http_client = httpx.AsyncClient()
        stack.push_async_callback(http_client.aclose)

        if settings.storage_adapter == "storage-service":
            if not settings.storage_service_url or not settings.storage_service_token:
                raise RuntimeError("storage-service URL and token are required")
            storage: ObjectStorage = StorageServiceObjectStorage(
                base_url=settings.storage_service_url,
                service_token=settings.storage_service_token,
                bucket=settings.s3_bucket,
                client=http_client,
                presign_ttl_seconds=settings.s3_presign_ttl_seconds,
            )
        elif settings.storage_adapter == "s3":
            import aioboto3

            session = aioboto3.Session()
            client_context = session.client(
                "s3",
                endpoint_url=settings.s3_endpoint_url,
                region_name=settings.s3_region,
                aws_access_key_id=settings.s3_access_key_id,
                aws_secret_access_key=settings.s3_secret_access_key,
            )
            s3_client = await stack.enter_async_context(client_context)
            storage = S3ObjectStorage(
                client=s3_client,
                bucket=settings.s3_bucket,
                presign_ttl_seconds=settings.s3_presign_ttl_seconds,
            )
        else:
            raise RuntimeError("retention cleanup requires durable object storage")

        if settings.logging_service_url and settings.logging_service_token:
            logger: StructuredLogger = LoggerClient(
                base_url=settings.logging_service_url,
                service_token=settings.logging_service_token,
                service_name="monkeyocr-retention-cleanup",
                timeout_seconds=settings.logging_service_timeout_seconds,
                client=http_client,
            )
        else:
            logger = StdlibStructuredLogger("monkeyocr-retention-cleanup")

        yield (
            RetentionCleanupService(
                repository=AsyncpgRetentionRepository(pool),
                storage=storage,
                logger=logger,
                delete_concurrency=settings.retention_cleanup_delete_concurrency,
                retry_delay_seconds=settings.retention_cleanup_retry_seconds,
            ),
            logger,
        )


async def run(*, once: bool = False) -> None:
    settings = get_settings()
    async with create_retention_service(settings) as (service, logger):
        while True:
            try:
                result = await service.run_batch(
                    limit=settings.retention_cleanup_batch_size,
                    lease_seconds=settings.retention_cleanup_lease_seconds,
                )
                if result.claimed:
                    await logger.info(
                        "retention_batch_completed",
                        claimed=result.claimed,
                        completed=result.completed,
                        deferred=result.deferred,
                        deleted_objects=result.deleted_objects,
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await logger.error(
                    "retention_batch_failed", error_type=type(exc).__name__
                )
                if once:
                    raise
                await asyncio.sleep(settings.retention_cleanup_interval_seconds)
                continue

            if once:
                return
            if result.claimed >= settings.retention_cleanup_batch_size:
                await asyncio.sleep(0)
            else:
                await asyncio.sleep(settings.retention_cleanup_interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Delete expired MonkeyOCR data")
    parser.add_argument(
        "--once", action="store_true", help="process one cleanup batch and exit"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run(once=args.once))


if __name__ == "__main__":
    main()

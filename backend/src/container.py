from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator

from src.config import Settings
from src.contexts.ocr.application.ports import (
    DocumentPreprocessor,
    JobEventRepository,
    JobRepository,
    OCREngine,
    ObjectStorage,
    OutboxRepository,
    UploadRepository,
    StructuredLogger,
)
from src.contexts.ocr.application.exceptions import DependencyError
from src.contexts.ocr.application.services import OCRApplicationService
from src.contexts.ocr.application.readiness import (
    DependencyReadinessCheck,
    ReadinessService,
)
from src.infrastructure.file_validation import MagicBytesFileValidator
from src.infrastructure.api_keys import APIKeyAuthenticator, DevelopmentAPIKeyAuthenticator
from src.infrastructure.memory import (
    InMemoryJobEventRepository,
    InMemoryJobRepository,
    InMemoryObjectStorage,
    InMemoryOutboxRepository,
    InMemoryStructuredLogger,
    InMemoryUploadRepository,
)
from src.infrastructure.preprocessor import PassthroughDocumentPreprocessor
from src.infrastructure.api_keys import PostgresAPIKeyAuthenticator
from src.infrastructure.engine import FakeOCREngine, PaddleOCRVLEngineAdapter
from src.infrastructure.logger_client import LoggerClient, StdlibStructuredLogger
from src.infrastructure.messaging import KafkaJobPublisher, OutboxDispatcher
from src.infrastructure.persistence import (
    AsyncpgJobEventRepository,
    AsyncpgJobRepository,
    AsyncpgOutboxRepository,
    AsyncpgUploadRepository,
)
from src.infrastructure.preprocessor import (
    DirectorySandboxPreprocessor,
    SandboxDocumentPreprocessorAdapter,
    SubprocessSandboxPreprocessor,
)
from src.infrastructure.readiness import (
    HTTPStatusReadinessProbe,
    KafkaReadinessProbe,
    ObjectStorageReadinessProbe,
    PostgresReadinessProbe,
    SandboxHeartbeatReadinessProbe,
)
from src.infrastructure.storage import S3ObjectStorage, StorageServiceObjectStorage
from src.shared.internal_status_codes import InternalStatusCode


@dataclass(slots=True)
class AppContainer:
    settings: Settings
    service: OCRApplicationService
    uploads: UploadRepository
    jobs: JobRepository
    events: JobEventRepository
    outbox: OutboxRepository
    storage: ObjectStorage
    preprocessor: DocumentPreprocessor
    authenticator: APIKeyAuthenticator
    engine: OCREngine
    logger: StructuredLogger
    readiness: ReadinessService


def create_memory_container(settings: Settings | None = None) -> AppContainer:
    settings = settings or Settings(environment="test")
    uploads = InMemoryUploadRepository()
    events = InMemoryJobEventRepository()
    jobs = InMemoryJobRepository(events)
    outbox = InMemoryOutboxRepository()
    storage = InMemoryObjectStorage()
    preprocessor = PassthroughDocumentPreprocessor()
    service = OCRApplicationService(
        uploads=uploads,
        jobs=jobs,
        outbox=outbox,
        storage=storage,
        validator=MagicBytesFileValidator(),
        max_upload_bytes=settings.max_upload_bytes,
    )
    return AppContainer(
        settings=settings,
        service=service,
        uploads=uploads,
        jobs=jobs,
        events=events,
        outbox=outbox,
        storage=storage,
        preprocessor=preprocessor,
        authenticator=DevelopmentAPIKeyAuthenticator(settings.dev_api_key_id),
        engine=FakeOCREngine(),
        logger=InMemoryStructuredLogger(),
        readiness=ReadinessService(),
    )


OUTBOX_ADVISORY_LOCK_NAME = "monkeyocr:outbox-dispatcher"


async def _run_outbox(
    dispatcher: OutboxDispatcher,
    logger: StructuredLogger,
    pool: Any,
) -> None:
    while True:
        connection = None
        lock_acquired = False
        try:
            connection = await pool.acquire()
            lock_acquired = bool(
                await connection.fetchval(
                    "SELECT pg_try_advisory_lock(hashtextextended($1,0))",
                    OUTBOX_ADVISORY_LOCK_NAME,
                )
            )
            if not lock_acquired:
                await asyncio.sleep(1)
                continue
            while True:
                try:
                    count = await dispatcher.dispatch_once(limit=100)
                    await asyncio.sleep(0.1 if count else 0.5)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    fields: dict[str, object] = {"error_type": type(exc).__name__}
                    if isinstance(exc, DependencyError):
                        fields.update(
                            internal_code=int(exc.internal_code),
                            internal_status_name=exc.internal_code.name,
                            error_reason=exc.error_reason,
                        )
                    await logger.error("outbox_dispatch_failed", **fields)
                    await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            fields: dict[str, object] = {"error_type": type(exc).__name__}
            if isinstance(exc, DependencyError):
                fields.update(
                    internal_code=int(exc.internal_code),
                    internal_status_name=exc.internal_code.name,
                    error_reason=exc.error_reason,
                )
            await logger.error("outbox_dispatch_failed", **fields)
            await asyncio.sleep(1)
        finally:
            if connection is not None:
                if lock_acquired:
                    try:
                        await connection.fetchval(
                            "SELECT pg_advisory_unlock(hashtextextended($1,0))",
                            OUTBOX_ADVISORY_LOCK_NAME,
                        )
                    except Exception:
                        pass
                await pool.release(connection)


async def _cancel_task(task: asyncio.Task[None]) -> None:
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@asynccontextmanager
async def create_runtime_container(
    settings: Settings, *, start_outbox_dispatcher: bool = True
) -> AsyncIterator[AppContainer]:
    if settings.repository_adapter != "postgres" or not settings.database_url:
        raise RuntimeError("durable runtime requires DATABASE_URL")
    import asyncpg
    import httpx

    async with AsyncExitStack() as stack:
        pool = await asyncpg.create_pool(
            settings.database_url,
            min_size=1,
            max_size=settings.database_pool_size,
        )
        stack.push_async_callback(pool.close)
        http_client = httpx.AsyncClient()
        stack.push_async_callback(http_client.aclose)

        uploads = AsyncpgUploadRepository(
            pool, upload_ttl_seconds=settings.upload_session_ttl_seconds
        )
        jobs = AsyncpgJobRepository(
            pool,
            topic=settings.kafka_jobs_topic,
            retention_days=settings.job_retention_days,
        )
        events = AsyncpgJobEventRepository(pool)
        outbox = AsyncpgOutboxRepository(pool, topic=settings.kafka_jobs_topic)

        if settings.storage_adapter == "storage-service":
            if not settings.storage_service_url or not settings.storage_service_token:
                raise RuntimeError("storage-service URL and token are required")
            storage: ObjectStorage = StorageServiceObjectStorage(
                base_url=settings.storage_service_url,
                service_token=settings.storage_service_token,
                bucket=settings.s3_bucket,
                client=http_client,
                presign_ttl_seconds=settings.s3_presign_ttl_seconds,
                multipart_part_size_bytes=settings.multipart_part_size_bytes,
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
                multipart_part_size_bytes=settings.multipart_part_size_bytes,
            )
        else:
            raise RuntimeError("durable runtime cannot use memory storage")

        if settings.preprocessor_adapter == "sandbox":
            if settings.sandbox_exchange_dir:
                preprocessor: DocumentPreprocessor = DirectorySandboxPreprocessor(
                    storage=storage,
                    exchange_dir=settings.sandbox_exchange_dir,
                    timeout_seconds=settings.sandbox_timeout_seconds,
                    max_pages=settings.sandbox_max_pages,
                    max_pixels=settings.sandbox_max_pixels,
                    dpi=settings.sandbox_pdf_dpi,
                )
            elif settings.sandbox_command:
                preprocessor: DocumentPreprocessor = SubprocessSandboxPreprocessor(
                    storage=storage,
                    command=settings.sandbox_command,
                    timeout_seconds=settings.sandbox_timeout_seconds,
                    max_pages=settings.sandbox_max_pages,
                )
            elif settings.sandbox_base_url:
                preprocessor = SandboxDocumentPreprocessorAdapter(
                    base_url=settings.sandbox_base_url,
                    client=http_client,
                    timeout_seconds=settings.sandbox_timeout_seconds,
                )
            else:
                raise RuntimeError("sandbox preprocessor configuration is required")
        else:
            preprocessor = PassthroughDocumentPreprocessor()

        if settings.engine_adapter == "paddleocr-vl":
            if not settings.paddleocr_vl_base_url:
                raise RuntimeError("OCR_ENGINE_URL is required")
            engine: OCREngine = PaddleOCRVLEngineAdapter(
                base_url=settings.paddleocr_vl_base_url,
                endpoint_path=settings.paddleocr_vl_endpoint_path,
                timeout_seconds=settings.paddleocr_vl_timeout_seconds,
                model_name=settings.paddleocr_vl_model_name,
                engine_version=settings.paddleocr_vl_engine_version,
                client=http_client,
            )
        else:
            engine = FakeOCREngine()

        if settings.logging_service_url and settings.logging_service_token:
            structured_logger: StructuredLogger = LoggerClient(
                base_url=settings.logging_service_url,
                service_token=settings.logging_service_token,
                service_name=settings.logging_service_name,
                timeout_seconds=settings.logging_service_timeout_seconds,
                client=http_client,
            )
        else:
            structured_logger = StdlibStructuredLogger()

        if not settings.api_key_pepper:
            raise RuntimeError("MONKEYOCR_API_KEY_PEPPER is required with PostgreSQL")
        authenticator = PostgresAPIKeyAuthenticator(
            pool=pool, pepper=settings.api_key_pepper
        )
        service = OCRApplicationService(
            uploads=uploads,
            jobs=jobs,
            outbox=outbox,
            storage=storage,
            validator=MagicBytesFileValidator(),
            max_upload_bytes=settings.max_upload_bytes,
        )
        producer = None
        if start_outbox_dispatcher:
            if not settings.kafka_bootstrap_servers:
                raise RuntimeError("KAFKA_BROKERS is required")
            from aiokafka import AIOKafkaProducer

            producer = AIOKafkaProducer(
                bootstrap_servers=settings.kafka_bootstrap_servers,
                client_id=f"{settings.kafka_client_id}-outbox",
                acks="all",
            )
            await producer.start()
            stack.push_async_callback(producer.stop)
            publisher = KafkaJobPublisher(
                producer=producer, topic=settings.kafka_jobs_topic
            )
            task = asyncio.create_task(
                _run_outbox(
                    OutboxDispatcher(outbox=outbox, publisher=publisher),
                    structured_logger,
                    pool,
                ),
                name="monkeyocr-outbox-dispatcher",
            )
            stack.push_async_callback(_cancel_task, task)

        readiness_checks = [
            DependencyReadinessCheck(
                "postgresql",
                InternalStatusCode.DATABASE_UNAVAILABLE,
                PostgresReadinessProbe(pool),
            ),
            DependencyReadinessCheck(
                "object_storage",
                InternalStatusCode.STORAGE_UNAVAILABLE,
                ObjectStorageReadinessProbe(storage),
            ),
        ]
        if producer is not None:
            readiness_checks.append(
                DependencyReadinessCheck(
                    "kafka",
                    InternalStatusCode.QUEUE_UNAVAILABLE,
                    KafkaReadinessProbe(producer, settings.kafka_jobs_topic),
                )
            )
        if settings.engine_adapter == "paddleocr-vl" and settings.paddleocr_vl_base_url:
            readiness_checks.append(
                DependencyReadinessCheck(
                    "paddleocr_vl",
                    InternalStatusCode.ENGINE_UNAVAILABLE,
                    HTTPStatusReadinessProbe(
                        http_client,
                        f"{settings.paddleocr_vl_base_url.rstrip('/')}/health/ready",
                    ),
                )
            )
        if settings.sandbox_exchange_dir:
            readiness_checks.append(
                DependencyReadinessCheck(
                    "sandbox",
                    InternalStatusCode.INTERNAL_CONTROLLED_ERROR,
                    SandboxHeartbeatReadinessProbe(settings.sandbox_exchange_dir),
                )
            )

        container = AppContainer(
            settings=settings,
            service=service,
            uploads=uploads,
            jobs=jobs,
            events=events,
            outbox=outbox,
            storage=storage,
            preprocessor=preprocessor,
            authenticator=authenticator,
            engine=engine,
            logger=structured_logger,
            readiness=ReadinessService(readiness_checks),
        )

        yield container

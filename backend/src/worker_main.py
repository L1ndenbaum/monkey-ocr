from __future__ import annotations

import asyncio
import signal
from collections.abc import Awaitable
from typing import Any, Protocol, TypeVar

from src.config import get_settings
from src.container import create_runtime_container
from src.contexts.ocr.application.worker import OCRWorker
from src.infrastructure.messaging import decode_job_message


T = TypeVar("T")
SAFE_CONSUMER_POLL_INTERVAL_SECONDS = 30.0


class ConsumerPoller(Protocol):
    def assignment(self) -> set[Any]: ...

    def paused(self) -> set[Any]: ...

    def pause(self, *partitions: Any) -> None: ...

    def resume(self, *partitions: Any) -> None: ...

    async def getmany(
        self, *partitions: Any, timeout_ms: int, max_records: int
    ) -> dict[Any, list[Any]]: ...


async def await_with_safe_consumer_polls(
    consumer: ConsumerPoller,
    operation: Awaitable[T],
    *,
    poll_interval_seconds: float = SAFE_CONSUMER_POLL_INTERVAL_SECONDS,
) -> T:
    """Keep Kafka's max-poll timer fresh without consuming the next record."""

    if poll_interval_seconds <= 0:
        raise ValueError("poll_interval_seconds must be positive")

    operation_task = asyncio.ensure_future(operation)
    paused_by_helper: set[Any] = set()

    def pause_current_assignment() -> None:
        assigned = set(consumer.assignment())
        already_paused = set(consumer.paused())
        to_pause = assigned - already_paused
        if to_pause:
            consumer.pause(*to_pause)
            paused_by_helper.update(to_pause)

    try:
        pause_current_assignment()
        while True:
            try:
                return await asyncio.wait_for(
                    asyncio.shield(operation_task), timeout=poll_interval_seconds
                )
            except TimeoutError:
                # Assignment may change independently of this task. Pause any
                # newly assigned partitions before touching the consumer so a
                # keepalive poll cannot drain prefetched work.
                pause_current_assignment()
                records = await consumer.getmany(timeout_ms=0, max_records=1)
                if any(records.values()):
                    raise RuntimeError(
                        "safe Kafka poll returned records while work was in progress"
                    )
    finally:
        if not operation_task.done():
            operation_task.cancel()
            await asyncio.gather(operation_task, return_exceptions=True)
        resumable = (
            paused_by_helper
            & set(consumer.assignment())
            & set(consumer.paused())
        )
        if resumable:
            consumer.resume(*resumable)


async def wait_for_runtime_readiness(
    container: Any,
    stop: asyncio.Event,
    *,
    timeout_seconds: float,
    poll_seconds: float,
) -> bool:
    """Wait before consuming Kafka so engine warm-up does not spend job retries."""

    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while not stop.is_set():
        report = await container.readiness.check()
        if report.ready:
            return True
        if asyncio.get_running_loop().time() >= deadline:
            await container.logger.error(
                "worker_readiness_timeout",
                internal_code=int(report.internal_code or 0),
                error_reason=report.error_reason or "runtime_not_ready",
            )
            raise RuntimeError("worker dependencies did not become ready")
        try:
            await asyncio.wait_for(stop.wait(), timeout=poll_seconds)
        except TimeoutError:
            continue
    return False


async def run_worker() -> None:
    settings = get_settings()
    if not settings.kafka_bootstrap_servers:
        raise RuntimeError("KAFKA_BROKERS is required")
    from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
    from aiokafka.structs import OffsetAndMetadata

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(name, stop.set)
        except NotImplementedError:
            pass

    async with create_runtime_container(
        settings, start_outbox_dispatcher=False
    ) as container:
        if not await wait_for_runtime_readiness(
            container,
            stop,
            timeout_seconds=settings.worker_readiness_timeout_seconds,
            poll_seconds=settings.worker_readiness_poll_seconds,
        ):
            return
        consumer = AIOKafkaConsumer(
            settings.kafka_jobs_topic,
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id=settings.kafka_consumer_group,
            client_id=f"{settings.kafka_client_id}-ocr-worker",
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            max_poll_records=1,
            max_poll_interval_ms=3_600_000,
        )
        dlq_producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            client_id=f"{settings.kafka_client_id}-ocr-worker-dlq",
            acks="all",
        )
        await consumer.start()
        await dlq_producer.start()
        worker = OCRWorker(
            jobs=container.jobs,
            uploads=container.uploads,
            events=container.events,
            storage=container.storage,
            preprocessor=container.preprocessor,
            engine=container.engine,
            logger=container.logger,
            max_page_retries=settings.worker_max_page_retries,
            retry_base_seconds=settings.worker_retry_base_seconds,
            sleeper=asyncio.sleep,
        )
        try:
            while not stop.is_set():
                records = await consumer.getmany(timeout_ms=1_000, max_records=1)
                for topic_partition, messages in records.items():
                    for record in messages:
                        async def process_record() -> None:
                            try:
                                message = decode_job_message(record.value)
                            except Exception as exc:
                                await container.logger.error(
                                    "ocr_job_message_invalid",
                                    error_type=type(exc).__name__,
                                    topic=record.topic,
                                    partition=record.partition,
                                    offset=record.offset,
                                )
                                await dlq_producer.send_and_wait(
                                    settings.kafka_jobs_dlq_topic,
                                    key=record.key,
                                    value=record.value,
                                    headers=[
                                        ("error_reason", b"invalid_job_message"),
                                    ],
                                )
                            else:
                                await worker.process(message)

                        await await_with_safe_consumer_polls(
                            consumer,
                            process_record(),
                        )
                        await consumer.commit(
                            {
                                topic_partition: OffsetAndMetadata(
                                    record.offset + 1, ""
                                )
                            }
                        )
        finally:
            await consumer.stop()
            await dlq_producer.stop()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()

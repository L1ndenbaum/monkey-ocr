from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.contexts.ocr.application.readiness import ReadinessReport
from src.shared.internal_status_codes import InternalStatusCode
from src.worker_main import await_with_safe_consumer_polls, wait_for_runtime_readiness


class FakeConsumer:
    def __init__(self) -> None:
        self.assigned = {"partition-0", "partition-1"}
        self.paused_partitions: set[str] = set()
        self.pause_calls: list[set[str]] = []
        self.resume_calls: list[set[str]] = []
        self.poll_calls = 0
        self.release_operation = asyncio.Event()

    def assignment(self) -> set[str]:
        return set(self.assigned)

    def paused(self) -> set[str]:
        return set(self.paused_partitions)

    def pause(self, *partitions: Any) -> None:
        values = {str(partition) for partition in partitions}
        self.pause_calls.append(values)
        self.paused_partitions.update(values)

    def resume(self, *partitions: Any) -> None:
        values = {str(partition) for partition in partitions}
        self.resume_calls.append(values)
        self.paused_partitions.difference_update(values)

    async def getmany(
        self, *partitions: Any, timeout_ms: int, max_records: int
    ) -> dict[Any, list[Any]]:
        assert timeout_ms == 0
        assert max_records == 1
        assert self.paused_partitions == self.assigned
        self.poll_calls += 1
        if self.poll_calls == 2:
            self.release_operation.set()
        return {}


class EventuallyReadyContainer:
    def __init__(self) -> None:
        self.calls = 0
        self.errors: list[tuple[str, dict[str, object]]] = []
        self.readiness = self
        self.logger = self

    async def check(self) -> ReadinessReport:
        self.calls += 1
        if self.calls < 3:
            return ReadinessReport(
                checks={"paddleocr_vl": "unavailable"},
                internal_code=InternalStatusCode.ENGINE_UNAVAILABLE,
                error_reason="readiness_paddleocr_vl_unavailable",
            )
        return ReadinessReport(checks={"paddleocr_vl": "ok"})

    async def error(self, event: str, **fields: object) -> None:
        self.errors.append((event, fields))


@pytest.mark.asyncio
async def test_safe_consumer_polls_keep_long_operation_alive_without_draining_records() -> None:
    consumer = FakeConsumer()

    async def long_operation() -> str:
        await consumer.release_operation.wait()
        return "complete"

    result = await await_with_safe_consumer_polls(
        consumer,
        long_operation(),
        poll_interval_seconds=0.001,
    )

    assert result == "complete"
    assert consumer.poll_calls == 2
    assert consumer.pause_calls == [{"partition-0", "partition-1"}]
    assert consumer.resume_calls == [{"partition-0", "partition-1"}]
    assert consumer.paused_partitions == set()


@pytest.mark.asyncio
async def test_safe_consumer_polls_resume_partitions_when_operation_fails() -> None:
    consumer = FakeConsumer()

    async def failing_operation() -> None:
        raise RuntimeError("worker failed")

    with pytest.raises(RuntimeError, match="worker failed"):
        await await_with_safe_consumer_polls(
            consumer,
            failing_operation(),
            poll_interval_seconds=1,
        )

    assert consumer.poll_calls == 0
    assert consumer.paused_partitions == set()
    assert consumer.resume_calls == [{"partition-0", "partition-1"}]


@pytest.mark.asyncio
async def test_worker_waits_for_engine_warmup_before_consuming() -> None:
    container = EventuallyReadyContainer()

    ready = await wait_for_runtime_readiness(
        container,
        asyncio.Event(),
        timeout_seconds=1,
        poll_seconds=0.001,
    )

    assert ready is True
    assert container.calls == 3
    assert container.errors == []

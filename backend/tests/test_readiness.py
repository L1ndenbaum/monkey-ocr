from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from infrastructure.sandbox.daemon import write_heartbeat
from src.container import create_memory_container
from src.contexts.ocr.application.readiness import (
    DependencyReadinessCheck,
    ReadinessService,
)
from src.infrastructure.readiness import (
    HTTPStatusReadinessProbe,
    KafkaReadinessProbe,
    ObjectStorageReadinessProbe,
    PostgresReadinessProbe,
    SandboxHeartbeatReadinessProbe,
)
from src.main import create_app
from src.shared.internal_status_codes import InternalStatusCode


async def _succeed() -> None:
    return None


async def _fail_with_secret() -> None:
    raise RuntimeError("postgresql://operator:secret@database/monkeyocr_db")


@pytest.mark.asyncio
async def test_readiness_service_reports_all_checks_and_first_failure_safely() -> None:
    readiness = ReadinessService(
        [
            DependencyReadinessCheck(
                "postgresql",
                InternalStatusCode.DATABASE_UNAVAILABLE,
                _fail_with_secret,
            ),
            DependencyReadinessCheck(
                "object_storage", InternalStatusCode.STORAGE_UNAVAILABLE, _succeed
            ),
        ]
    )

    report = await readiness.check()

    assert report.ready is False
    assert report.internal_code == InternalStatusCode.DATABASE_UNAVAILABLE
    assert report.error_reason == "readiness_postgresql_unavailable"
    assert report.checks == {
        "application": "ok",
        "postgresql": "unavailable",
        "object_storage": "ok",
    }
    assert "secret" not in str(report)


@pytest.mark.asyncio
async def test_readiness_service_bounds_slow_dependency_probes() -> None:
    async def slow() -> None:
        await asyncio.sleep(10)

    readiness = ReadinessService(
        [
            DependencyReadinessCheck(
                "kafka", InternalStatusCode.QUEUE_UNAVAILABLE, slow
            )
        ],
        timeout_seconds=0.01,
    )

    report = await readiness.check()

    assert report.checks["kafka"] == "unavailable"
    assert report.internal_code == InternalStatusCode.QUEUE_UNAVAILABLE


@pytest.mark.asyncio
async def test_memory_readiness_endpoint_is_ready() -> None:
    app = create_app(container=create_memory_container())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["internal_code"] == InternalStatusCode.SUCCESS
    assert response.json()["data"] == {
        "status": "ready",
        "checks": {"application": "ok"},
    }


@pytest.mark.asyncio
async def test_unready_endpoint_uses_business_envelope_and_safe_details() -> None:
    container = create_memory_container()
    container.readiness = ReadinessService(
        [
            DependencyReadinessCheck(
                "postgresql",
                InternalStatusCode.DATABASE_UNAVAILABLE,
                _fail_with_secret,
            )
        ]
    )
    app = create_app(container=container)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health/ready")

    payload = response.json()
    assert response.status_code == 200
    assert payload["internal_code"] == InternalStatusCode.DATABASE_UNAVAILABLE
    assert payload["error_reason"] == "readiness_postgresql_unavailable"
    assert payload["data"] == {
        "status": "not_ready",
        "checks": {"application": "ok", "postgresql": "unavailable"},
    }
    assert "secret" not in response.text


@pytest.mark.asyncio
async def test_concrete_dependency_probes_verify_expected_contracts(tmp_path) -> None:
    class Pool:
        async def fetchval(self, query: str, *args: object) -> int:
            assert query == "SELECT 1"
            return 1

    class Storage:
        async def stat(self, object_key: str) -> None:
            assert object_key == ".monkeyocr-readiness-probe"

    class Metadata:
        def partitions_for_topic(self, topic: str) -> set[int]:
            assert topic == "monkeyocr.events.jobs"
            return {0}

    class KafkaClient:
        async def fetch_all_metadata(self) -> Metadata:
            return Metadata()

    class Producer:
        client = KafkaClient()

    class Response:
        status_code = 200

    class Client:
        async def get(self, url: str, **kwargs: object) -> Response:
            assert url == "http://hps/health/ready"
            return Response()

    write_heartbeat(tmp_path)
    probes = (
        PostgresReadinessProbe(Pool()),
        ObjectStorageReadinessProbe(Storage()),
        KafkaReadinessProbe(Producer(), "monkeyocr.events.jobs"),
        HTTPStatusReadinessProbe(Client(), "http://hps/health/ready"),
        SandboxHeartbeatReadinessProbe(str(tmp_path)),
    )

    await asyncio.gather(*(probe() for probe in probes))


@pytest.mark.asyncio
async def test_sandbox_heartbeat_probe_rejects_stale_daemon(tmp_path) -> None:
    write_heartbeat(tmp_path, now=time.time() - 60)

    with pytest.raises(RuntimeError, match="stale"):
        await SandboxHeartbeatReadinessProbe(str(tmp_path), max_age_seconds=5)()

import hashlib

import httpx
import pytest
from uuid6 import uuid7

from src.config import Settings
from src.container import create_memory_container
from src.contexts.ocr.domain.models import Job, JobEvent, JobState
from src.main import create_app
from src.shared.api import InternalStatusCode


PNG = b"\x89PNG\r\n\x1a\n" + b"api-image"


class LimitedJobEvents:
    def __init__(self, delegate, limit: int = 100) -> None:
        self.delegate = delegate
        self.limit = limit

    async def list_after(self, job_id, sequence):
        return (await self.delegate.list_after(job_id, sequence))[: self.limit]

    async def wait_after(self, job_id, sequence, timeout_seconds):
        return (await self.delegate.wait_after(job_id, sequence, timeout_seconds))[
            : self.limit
        ]


@pytest.mark.asyncio
async def test_all_controlled_json_responses_use_envelope_and_http_200() -> None:
    settings = Settings(environment="test")
    container = create_memory_container(settings)
    app = create_app(settings=settings, container=container)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        invalid = await client.post("/v1/uploads", json={})
        missing = await client.get("/legacy/process")

    assert invalid.status_code == 200
    assert invalid.json()["internal_code"] == InternalStatusCode.COMMON_INVALID_ARGUMENT
    assert set(invalid.json()) == {
        "internal_code",
        "message",
        "data",
        "timestamp",
        "request_id",
        "error_reason",
    }
    assert "code" not in invalid.json()
    assert missing.status_code == 200
    assert missing.json()["internal_code"] == InternalStatusCode.COMMON_RESOURCE_NOT_FOUND


@pytest.mark.asyncio
async def test_upload_job_and_sse_contract() -> None:
    settings = Settings(environment="test", sse_heartbeat_seconds=0.01)
    container = create_memory_container(settings)
    app = create_app(settings=settings, container=container)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        created_upload = (await client.post(
            "/v1/uploads",
            json={
                "filename": "invoice.png",
                "size_bytes": len(PNG),
                "content_type": "image/png",
                "sha256": hashlib.sha256(PNG).hexdigest(),
            },
        )).json()["data"]
        await container.storage.put_bytes(
            created_upload["object_key"], PNG, content_type="image/png"
        )
        completed = await client.post(
            f"/v1/uploads/{created_upload['upload_id']}/complete",
            json={"sha256": hashlib.sha256(PNG).hexdigest(), "parts": []},
        )
        created_job = (await client.post(
            "/v1/jobs", json={"upload_id": created_upload["upload_id"]}
        )).json()["data"]
        await client.post(f"/v1/jobs/{created_job['job_id']}/cancel")
        stream = await client.get(f"/v1/jobs/{created_job['job_id']}/events")

    assert completed.status_code == 200
    assert stream.status_code == 200
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert '"internal_code":0' in stream.text
    assert "event: job.cancelled" in stream.text


def test_openapi_does_not_advertise_422() -> None:
    app = create_app(container=create_memory_container())
    schema = app.openapi()
    assert all(
        "422" not in operation.get("responses", {})
        for path in schema["paths"].values()
        for operation in path.values()
        if isinstance(operation, dict)
    )


@pytest.mark.asyncio
async def test_sse_replay_continues_past_a_terminal_event_from_an_old_attempt() -> None:
    settings = Settings(environment="test")
    container = create_memory_container(settings)
    job = Job(
        owner_id=settings.dev_api_key_id,
        upload_id=uuid7(),
        request_id="first-request",
    )
    await container.jobs.add(job)
    job.fail("first_failure")
    await container.jobs.save(job)
    await container.events.append(
        JobEvent(
            job_id=job.id,
            event_type="job.failed",
            state=job.state,
            progress=job.progress,
            request_id=job.request_id,
            payload={"attempt": 1},
        )
    )
    job.retry("second-request")
    await container.jobs.save(job)
    await container.events.append(
        JobEvent(
            job_id=job.id,
            event_type="job.retrying",
            state=job.state,
            progress=job.progress,
            request_id=job.request_id,
            payload={"attempt": 2},
        )
    )
    job.fail("second_failure")
    await container.jobs.save(job)
    await container.events.append(
        JobEvent(
            job_id=job.id,
            event_type="job.failed",
            state=job.state,
            progress=job.progress,
            request_id=job.request_id,
            payload={"attempt": 2},
        )
    )

    app = create_app(settings=settings, container=container)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(f"/v1/jobs/{job.id}/events")

    assert response.status_code == 200
    assert response.text.count("event: job.failed") == 2
    assert response.text.index("event: job.retrying") > response.text.index(
        "event: job.failed"
    )


@pytest.mark.asyncio
async def test_sse_replay_crosses_batch_boundary_after_old_attempt_terminal() -> None:
    settings = Settings(environment="test")
    container = create_memory_container(settings)
    job = Job(
        owner_id=settings.dev_api_key_id,
        upload_id=uuid7(),
        request_id="second-request",
    )
    await container.jobs.add(job)
    for index in range(99):
        await container.events.append(
            JobEvent(
                job_id=job.id,
                event_type="page.running",
                state=JobState.RUNNING,
                progress=index / 100,
                request_id="first-request",
                payload={"attempt": 1, "page_number": index + 1},
            )
        )
    await container.events.append(
        JobEvent(
            job_id=job.id,
            event_type="job.failed",
            state=JobState.FAILED,
            progress=0.99,
            request_id="first-request",
            payload={"attempt": 1, "internal_code": 50001},
        )
    )
    await container.events.append(
        JobEvent(
            job_id=job.id,
            event_type="job.retrying",
            state=JobState.RETRYING,
            progress=0,
            request_id="second-request",
            payload={"attempt": 2},
        )
    )
    await container.events.append(
        JobEvent(
            job_id=job.id,
            event_type="job.succeeded",
            state=JobState.SUCCEEDED,
            progress=1,
            request_id="second-request",
            payload={"attempt": 2},
        )
    )
    job.attempt = 2
    job.state = JobState.SUCCEEDED
    await container.jobs.save(job)
    container.events = LimitedJobEvents(container.events)

    app = create_app(settings=settings, container=container)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(f"/v1/jobs/{job.id}/events")

    assert response.status_code == 200
    assert "event: job.retrying" in response.text
    assert response.text.rstrip().endswith("}")
    assert "event: job.succeeded" in response.text

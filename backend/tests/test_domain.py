from uuid6 import uuid7

import pytest

from src.contexts.ocr.domain.models import Job, JobState, Page, PageState


def make_job() -> Job:
    return Job(owner_id="owner", upload_id=uuid7(), request_id="request")


def test_job_state_machine_and_retry_reuse_successful_pages() -> None:
    job = make_job()
    job.begin_preprocessing()
    job.set_pages(
        [Page(page_number=1, input_object_key="p1"), Page(page_number=2, input_object_key="p2")]
    )
    job.begin_running()
    job.pages[0].start()
    job.pages[0].succeed(
        markdown="done",
        structured={},
        result_object_key="result-1",
        result_sha256="a" * 64,
        visualization_object_key=None,
    )
    job.pages[1].start()
    job.pages[1].fail("engine_unavailable")
    job.fail("engine_unavailable")

    job.retry("retry-request")

    assert job.state is JobState.RETRYING
    assert job.attempt == 2
    assert job.started_at is None
    assert job.pages[0].state is PageState.SUCCEEDED
    assert job.pages[0].result_object_key == "result-1"
    assert job.pages[1].state is PageState.PENDING
    assert job.pages[1].result_object_key is None


def test_invalid_domain_transition_is_rejected() -> None:
    job = make_job()
    with pytest.raises(ValueError):
        job.begin_running()


def test_cancelled_job_can_be_requeued() -> None:
    job = make_job()
    job.request_cancel()
    job.cancel()

    job.retry("retry-request")

    assert job.state is JobState.RETRYING
    assert job.attempt == 2

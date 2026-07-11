import { describe, expect, it } from "vitest";
import { mergeJobEvent, normalizeProgress, type OcrJob } from "./ocr";

describe("OCR job state", () => {
  it("infers and clamps page progress", () => {
    expect(normalizeProgress({ completed_pages: 3, total_pages: 4 }).percent).toBe(75);
    expect(normalizeProgress({ percent: 120 }).percent).toBe(100);
  });

  it("applies a streamed checkpoint without losing job metadata", () => {
    const job: OcrJob = {
      job_id: "job-1",
      filename: "sample.pdf",
      status: "running",
      progress: normalizeProgress({ completed_pages: 1, total_pages: 3 }),
      attempt: 1,
      created_at: "2026-07-11T00:00:00Z",
      updated_at: "2026-07-11T00:00:00Z",
    };
    const updated = mergeJobEvent(job, {
      event_type: "page.completed",
      job_id: "job-1",
      progress: { completed_pages: 2 },
      occurred_at: "2026-07-11T00:01:00Z",
    });

    expect(updated.filename).toBe("sample.pdf");
    expect(updated.progress.completed_pages).toBe(2);
    expect(updated.progress.percent).toBeCloseTo(66.67, 1);
  });

  it("ignores terminal events from an earlier retry attempt", () => {
    const job: OcrJob = {
      job_id: "job-1",
      filename: "sample.pdf",
      status: "retrying",
      progress: normalizeProgress({ completed_pages: 1, total_pages: 3 }),
      attempt: 2,
      created_at: "2026-07-11T00:00:00Z",
      updated_at: "2026-07-11T00:02:00Z",
    };

    const updated = mergeJobEvent(job, {
      event_type: "job.failed",
      job_id: "job-1",
      status: "failed",
      attempt: 1,
      occurred_at: "2026-07-11T00:01:00Z",
    });

    expect(updated).toBe(job);
    expect(updated.status).toBe("retrying");
  });
});

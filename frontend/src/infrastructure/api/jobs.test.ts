import { describe, expect, it } from "vitest";
import { normalizeJob } from "./jobs";

describe("job DTO normalization", () => {
  it("converts the backend progress ratio to a UI percentage", () => {
    const job = normalizeJob({
      job_id: "019-job",
      upload_id: "019-upload",
      status: "running",
      attempt: 1,
      progress: 0.625,
      completed_pages: 5,
      total_pages: 8,
      created_at: "2026-07-11T00:00:00Z",
      updated_at: "2026-07-11T00:01:00Z",
    });

    expect(job.progress.percent).toBe(62.5);
    expect(job.progress.completed_pages).toBe(5);
    expect(job.filename).toContain("019-job");
  });
});

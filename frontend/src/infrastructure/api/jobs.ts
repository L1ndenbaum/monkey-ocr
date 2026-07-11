import type { JobArtifact, OcrJob, PaginatedJobs } from "../../domain/ocr";
import { normalizeProgress } from "../../domain/ocr";
import { apiRequest, objectStorageClient } from "./client";

type UnknownRecord = Record<string, unknown>;

function record(value: unknown): UnknownRecord {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("服务返回了无效的任务数据");
  }
  return value as UnknownRecord;
}

function text(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function numberValue(value: unknown, fallback = 0): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function normalizeJob(value: unknown): OcrJob {
  const source = record(value);
  const jobId = text(source.job_id || source.id);
  const rawProgress = numberValue(source.progress);
  const progress =
    typeof source.progress === "object" && source.progress !== null
      ? (source.progress as Partial<OcrJob["progress"]>)
      : {
          completed_pages: numberValue(source.completed_pages),
          total_pages: numberValue(source.total_pages),
          percent:
            source.progress_percent !== undefined
              ? numberValue(source.progress_percent)
              : rawProgress <= 1
                ? rawProgress * 100
                : rawProgress,
        };
  const createdAt = text(source.created_at, new Date().toISOString());

  return {
    job_id: jobId,
    upload_id: text(source.upload_id) || undefined,
    filename: text(source.filename || source.original_filename, `任务 ${jobId.slice(0, 8)}`),
    status: text(source.status, "queued") as OcrJob["status"],
    progress: normalizeProgress(progress),
    attempt: numberValue(source.attempt || source.attempt_no, 1),
    internal_code:
      source.internal_code === undefined ? undefined : numberValue(source.internal_code),
    created_at: createdAt,
    updated_at: text(source.updated_at, createdAt),
    error_message: text(source.error_message) || null,
    error_reason: text(source.error_reason) || null,
    input_sha256: text(source.input_sha256) || undefined,
    engine_name: text(source.engine_name) || undefined,
    engine_version: text(source.engine_version) || undefined,
    model_name: text(source.model_name) || undefined,
  };
}

function unwrapJob(value: unknown): unknown {
  const source = record(value);
  return source.job ?? source;
}

export async function createJob(uploadId: string): Promise<OcrJob> {
  const payload = await apiRequest<unknown>({
    method: "POST",
    url: "/v1/jobs",
    headers: { "Idempotency-Key": `monkeyocr:create:${uploadId}` },
    data: { upload_id: uploadId },
  });
  return normalizeJob(unwrapJob(payload));
}

export async function listJobs(page = 1, pageSize = 50): Promise<PaginatedJobs> {
  const payload = await apiRequest<unknown>({
    method: "GET",
    url: "/v1/jobs",
    params: { page, page_size: pageSize },
  });

  if (Array.isArray(payload)) {
    return { items: payload.map(normalizeJob), total: payload.length, page, page_size: pageSize };
  }
  const source = record(payload);
  const items = Array.isArray(source.items)
    ? source.items
    : Array.isArray(source.jobs)
      ? source.jobs
      : [];
  return {
    items: items.map(normalizeJob),
    total: numberValue(source.total, items.length),
    page: numberValue(source.page, page),
    page_size: numberValue(source.page_size, pageSize),
  };
}

export async function getJob(jobId: string): Promise<OcrJob> {
  const payload = await apiRequest<unknown>({
    method: "GET",
    url: `/v1/jobs/${encodeURIComponent(jobId)}`,
  });
  return normalizeJob(unwrapJob(payload));
}

export async function cancelJob(jobId: string): Promise<OcrJob> {
  const payload = await apiRequest<unknown>({
    method: "POST",
    url: `/v1/jobs/${encodeURIComponent(jobId)}/cancel`,
  });
  return normalizeJob(unwrapJob(payload));
}

export async function retryJob(jobId: string): Promise<OcrJob> {
  const payload = await apiRequest<unknown>({
    method: "POST",
    url: `/v1/jobs/${encodeURIComponent(jobId)}/retry`,
  });
  return normalizeJob(unwrapJob(payload));
}

function normalizeArtifact(value: unknown): JobArtifact {
  const source = record(value);
  const objectKey = text(source.object_key);
  const name = text(source.name || source.filename) || objectKey.split("/").pop() || "result";
  return {
    artifact_id: text(source.artifact_id || source.id) || objectKey,
    kind: text(source.kind || source.artifact_type, "file"),
    name,
    mime_type: text(source.mime_type || source.content_type, "application/octet-stream"),
    size_bytes: numberValue(source.size_bytes || source.size),
    download_url: text(source.download_url || source.presigned_url || source.url),
    page_no:
      source.page_no == null && source.page_number == null
        ? null
        : numberValue(source.page_no ?? source.page_number),
    sha256: text(source.sha256) || undefined,
  };
}

export async function listArtifacts(jobId: string): Promise<JobArtifact[]> {
  const payload = await apiRequest<unknown>({
    method: "GET",
    url: `/v1/jobs/${encodeURIComponent(jobId)}/artifacts`,
  });
  if (Array.isArray(payload)) return payload.map(normalizeArtifact);
  const source = record(payload);
  const items = Array.isArray(source.items)
    ? source.items
    : Array.isArray(source.artifacts)
      ? source.artifacts
      : [];
  return items.map(normalizeArtifact);
}

export async function loadTextArtifact(artifact: JobArtifact): Promise<string> {
  const response = await objectStorageClient.get<string>(artifact.download_url, {
    responseType: "text",
  });
  return response.data;
}

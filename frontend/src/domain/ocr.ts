export type JobStatus =
  | "uploading"
  | "queued"
  | "preprocessing"
  | "running"
  | "assembling"
  | "cancel_requested"
  | "cancelled"
  | "retrying"
  | "failed"
  | "succeeded";

export interface JobProgress {
  completed_pages: number;
  total_pages: number;
  percent: number;
  current_page?: number | null;
}

export interface OcrJob {
  job_id: string;
  upload_id?: string;
  filename: string;
  status: JobStatus;
  progress: JobProgress;
  attempt: number;
  internal_code?: number;
  created_at: string;
  updated_at: string;
  error_message?: string | null;
  error_reason?: string | null;
  input_sha256?: string;
  engine_name?: string;
  engine_version?: string;
  model_name?: string;
}

export interface JobPageEvent {
  page_no: number;
  status: string;
}

export interface JobEvent {
  event_id?: string | number;
  event_type: string;
  job_id: string;
  status?: JobStatus;
  attempt?: number;
  internal_code?: number;
  progress?: Partial<JobProgress>;
  page?: JobPageEvent;
  occurred_at: string;
  message?: string;
  payload?: Record<string, unknown>;
}

export type ArtifactKind =
  | "markdown"
  | "json"
  | "manifest"
  | "page_image"
  | "visualization"
  | string;

export interface JobArtifact {
  artifact_id: string;
  kind: ArtifactKind;
  name: string;
  mime_type: string;
  size_bytes: number;
  download_url: string;
  page_no?: number | null;
  sha256?: string;
}

export interface UploadPartDescriptor {
  part_number: number;
  upload_url: string;
  start_byte?: number;
  end_byte?: number;
  headers?: Record<string, string>;
}

export interface UploadSession {
  upload_id: string;
  object_key?: string;
  upload_url?: string;
  upload_headers?: Record<string, string>;
  multipart_upload_id?: string;
  part_size_bytes?: number;
  parts?: UploadPartDescriptor[];
}

export interface CompletedUpload {
  upload_id: string;
  status: string;
  sha256?: string;
}

export interface PaginatedJobs {
  items: OcrJob[];
  total: number;
  page: number;
  page_size: number;
}

export const ACTIVE_JOB_STATUSES = new Set<JobStatus>([
  "queued",
  "preprocessing",
  "running",
  "assembling",
  "cancel_requested",
  "retrying",
]);

export function isActiveJob(status: JobStatus): boolean {
  return ACTIVE_JOB_STATUSES.has(status);
}

export function isTerminalJob(status: JobStatus): boolean {
  return status === "succeeded" || status === "failed" || status === "cancelled";
}

export function normalizeProgress(progress: Partial<JobProgress> | undefined): JobProgress {
  const completed = Math.max(0, Number(progress?.completed_pages ?? 0));
  const total = Math.max(0, Number(progress?.total_pages ?? 0));
  const inferredPercent = total > 0 ? (completed / total) * 100 : 0;
  return {
    completed_pages: completed,
    total_pages: total,
    percent: Math.min(100, Math.max(0, Number(progress?.percent ?? inferredPercent))),
    current_page: progress?.current_page ?? null,
  };
}

export function mergeJobEvent(job: OcrJob, event: JobEvent): OcrJob {
  if (event.attempt !== undefined && event.attempt < job.attempt) {
    return job;
  }
  const progress: Partial<JobProgress> = { ...job.progress, ...event.progress };
  if (
    event.progress &&
    event.progress.percent === undefined &&
    (event.progress.completed_pages !== undefined || event.progress.total_pages !== undefined)
  ) {
    progress.percent = undefined;
  }
  if (
    event.progress?.percent !== undefined &&
    event.progress.completed_pages === undefined &&
    job.progress.total_pages > 0
  ) {
    progress.completed_pages = Math.round(
      (event.progress.percent / 100) * job.progress.total_pages,
    );
  }
  return {
    ...job,
    attempt: event.attempt ?? job.attempt,
    internal_code: event.internal_code ?? job.internal_code,
    status: event.status ?? job.status,
    progress: normalizeProgress(progress),
    updated_at: event.occurred_at || job.updated_at,
    error_message:
      event.event_type === "job.failed" && event.message ? event.message : job.error_message,
  };
}

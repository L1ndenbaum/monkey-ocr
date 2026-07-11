import type {
  CompletedUpload,
  UploadPartDescriptor,
  UploadSession,
} from "../../domain/ocr";
import { apiRequest, objectStorageClient } from "./client";

export type UploadStage = "hashing" | "creating" | "uploading" | "verifying";

export interface UploadProgress {
  stage: UploadStage;
  percent: number;
  uploaded_bytes?: number;
  total_bytes?: number;
}

export interface UploadDocumentResult {
  session: UploadSession;
  completed: CompletedUpload;
  sha256: string;
}

interface CompletedPart {
  part_number: number;
  etag: string;
}

export function maximumUploadBytes(): number {
  const configured = Number(import.meta.env.VITE_MAX_UPLOAD_BYTES || 100 * 1024 * 1024);
  return Number.isFinite(configured) && configured > 0 ? configured : 100 * 1024 * 1024;
}

export async function sha256File(
  file: File,
  onProgress?: (progress: UploadProgress) => void,
): Promise<string> {
  onProgress?.({ stage: "hashing", percent: 2, total_bytes: file.size });
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  const value = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
  onProgress?.({ stage: "hashing", percent: 100, total_bytes: file.size });
  return value;
}

export async function createUploadSession(file: File, sha256: string): Promise<UploadSession> {
  return apiRequest<UploadSession>({
    method: "POST",
    url: "/v1/uploads",
    data: {
      filename: file.name,
      size_bytes: file.size,
      content_type: file.type || "application/octet-stream",
      sha256,
    },
  });
}

export async function completeUploadSession(
  session: UploadSession,
  sha256: string,
  parts: CompletedPart[],
): Promise<CompletedUpload> {
  return apiRequest<CompletedUpload>({
    method: "POST",
    url: `/v1/uploads/${encodeURIComponent(session.upload_id)}/complete`,
    data: {
      sha256,
      multipart_upload_id: session.multipart_upload_id,
      parts,
    },
  });
}

function partBounds(
  descriptor: UploadPartDescriptor,
  index: number,
  session: UploadSession,
  file: File,
): [number, number] {
  const defaultPartSize = Number(
    session.part_size_bytes || import.meta.env.VITE_UPLOAD_PART_SIZE_BYTES || 8 * 1024 * 1024,
  );
  const start = descriptor.start_byte ?? index * defaultPartSize;
  const end = descriptor.end_byte ?? Math.min(file.size, start + defaultPartSize);
  return [start, Math.min(file.size, end)];
}

async function uploadParts(
  file: File,
  session: UploadSession,
  onProgress?: (progress: UploadProgress) => void,
): Promise<CompletedPart[]> {
  if (session.parts?.length) {
    const completed: CompletedPart[] = [];
    let uploadedBefore = 0;

    for (const [index, part] of session.parts.entries()) {
      const [start, end] = partBounds(part, index, session, file);
      const body = file.slice(start, end);
      const response = await objectStorageClient.put(part.upload_url, body, {
        headers: part.headers,
        onUploadProgress: ({ loaded }) => {
          const uploaded = Math.min(file.size, uploadedBefore + loaded);
          onProgress?.({
            stage: "uploading",
            percent: file.size ? (uploaded / file.size) * 100 : 100,
            uploaded_bytes: uploaded,
            total_bytes: file.size,
          });
        },
      });
      completed.push({
        part_number: part.part_number,
        etag: String(response.headers.etag || "").replaceAll('"', ""),
      });
      uploadedBefore += body.size;
    }
    return completed;
  }

  if (!session.upload_url) {
    throw new Error("上传会话没有提供预签名地址");
  }

  await objectStorageClient.put(session.upload_url, file, {
    headers: session.upload_headers,
    onUploadProgress: ({ loaded }) => {
      onProgress?.({
        stage: "uploading",
        percent: file.size ? (loaded / file.size) * 100 : 100,
        uploaded_bytes: loaded,
        total_bytes: file.size,
      });
    },
  });
  return [];
}

export async function uploadDocument(
  file: File,
  onProgress?: (progress: UploadProgress) => void,
): Promise<UploadDocumentResult> {
  const maxBytes = maximumUploadBytes();
  if (file.size > maxBytes) {
    throw new Error(`文件超过前端允许的大小（${Math.floor(maxBytes / 1024 / 1024)} MiB）`);
  }
  const sha256 = await sha256File(file, onProgress);
  onProgress?.({ stage: "creating", percent: 0, total_bytes: file.size });
  const session = await createUploadSession(file, sha256);
  const completedParts = await uploadParts(file, session, onProgress);
  onProgress?.({ stage: "verifying", percent: 0, total_bytes: file.size });
  const completed = await completeUploadSession(session, sha256, completedParts);
  onProgress?.({ stage: "verifying", percent: 100, total_bytes: file.size });
  return { session, completed, sha256 };
}

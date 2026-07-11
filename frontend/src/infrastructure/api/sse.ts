import {
  ApiBusinessError,
  ApiProtocolError,
  ApiTransportError,
  assertApiEnvelope,
  InternalStatusCode,
  isAllowedHttpStatus,
} from "../../domain/api";
import type { JobEvent } from "../../domain/ocr";
import { clearApiKey, getApiKey } from "../auth/apiKeyStore";
import { gatewayBaseUrl } from "./client";

export interface SseMessage {
  id?: string;
  event?: string;
  data: string;
}

export interface JobEventSubscription {
  close: () => void;
  getLastEventId: () => string | undefined;
}

interface SubscribeOptions {
  lastEventId?: string;
  onEvent: (event: JobEvent, eventId?: string) => void;
  onConnectionChange?: (state: "connecting" | "open" | "reconnecting" | "closed") => void;
  onError?: (error: unknown) => void;
}

function normalizeJobEvent(value: unknown): JobEvent {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new ApiProtocolError("SSE 事件 DTO 格式无效");
  }
  const source = value as Record<string, unknown>;
  const payload =
    typeof source.payload === "object" && source.payload !== null && !Array.isArray(source.payload)
      ? (source.payload as Record<string, unknown>)
      : {};
  const rawProgress = Number(source.progress ?? 0);
  const attempt = Number(payload.attempt);
  const internalCode = Number(payload.internal_code);
  const percent = Number.isFinite(rawProgress)
    ? rawProgress <= 1
      ? rawProgress * 100
      : rawProgress
    : 0;
  const totalPages = Number(payload.total_pages);
  const pageNumber = Number(payload.page_number);

  return {
    event_id:
      typeof source.event_id === "number" || typeof source.event_id === "string"
        ? source.event_id
        : undefined,
    event_type: typeof source.event_type === "string" ? source.event_type : "job.updated",
    job_id: typeof source.job_id === "string" ? source.job_id : "",
    status: typeof source.status === "string" ? (source.status as JobEvent["status"]) : undefined,
    attempt: Number.isFinite(attempt) ? attempt : undefined,
    internal_code: Number.isFinite(internalCode) ? internalCode : undefined,
    progress: {
      percent,
      total_pages: Number.isFinite(totalPages) ? totalPages : undefined,
      current_page: Number.isFinite(pageNumber) ? pageNumber : undefined,
    },
    occurred_at:
      typeof source.occurred_at === "string" ? source.occurred_at : new Date().toISOString(),
    message: typeof payload.error_reason === "string" ? payload.error_reason : undefined,
    payload,
  };
}

export function parseSseBlock(block: string): SseMessage | null {
  let id: string | undefined;
  let event: string | undefined;
  const data: string[] = [];
  for (const rawLine of block.split(/\r?\n/)) {
    if (!rawLine || rawLine.startsWith(":")) continue;
    const delimiter = rawLine.indexOf(":");
    const field = delimiter === -1 ? rawLine : rawLine.slice(0, delimiter);
    const value = delimiter === -1 ? "" : rawLine.slice(delimiter + 1).replace(/^ /, "");
    if (field === "id") id = value;
    if (field === "event") event = value;
    if (field === "data") data.push(value);
  }
  return data.length ? { id, event, data: data.join("\n") } : null;
}

async function readErrorResponse(response: Response): Promise<never> {
  if (!isAllowedHttpStatus(response.status)) {
    throw new ApiProtocolError(`SSE 返回了不允许的 HTTP 状态 ${response.status}`, response.status);
  }
  let envelope;
  try {
    envelope = assertApiEnvelope<unknown>(await response.json());
  } catch (error) {
    throw new ApiTransportError("SSE 连接返回了无效响应", {
      httpStatus: response.status,
      cause: error,
    });
  }
  if (response.status === 200) {
    if (
      envelope.internal_code === InternalStatusCode.USER_UNAUTHORIZED ||
      envelope.internal_code === InternalStatusCode.API_KEY_REVOKED
    ) {
      clearApiKey();
    }
    throw new ApiBusinessError(envelope);
  }
  throw new ApiTransportError(envelope.message, {
    httpStatus: response.status,
    internalCode: envelope.internal_code,
    requestId: envelope.request_id,
  });
}

export function subscribeJobEvents(jobId: string, options: SubscribeOptions): JobEventSubscription {
  let stopped = false;
  let activeController: AbortController | null = null;
  let lastEventId = options.lastEventId;
  let reconnectAttempt = 0;
  const configuredRetry = Number(import.meta.env.VITE_SSE_RETRY_MS || 2_000);
  const retryBaseMs = Number.isFinite(configuredRetry)
    ? Math.max(250, configuredRetry)
    : 2_000;

  const connect = async (): Promise<void> => {
    if (stopped) return;
    options.onConnectionChange?.(reconnectAttempt ? "reconnecting" : "connecting");
    const controller = new AbortController();
    activeController = controller;
    const apiKey = getApiKey();
    const headers: HeadersInit = { Accept: "text/event-stream" };
    if (apiKey) headers.Authorization = `Bearer ${apiKey}`;
    if (lastEventId) headers["Last-Event-ID"] = lastEventId;

    try {
      const response = await fetch(
        `${gatewayBaseUrl}/v1/jobs/${encodeURIComponent(jobId)}/events`,
        { headers, signal: controller.signal, cache: "no-store" },
      );
      const contentType = response.headers.get("content-type") || "";
      if (response.status !== 200 || !contentType.includes("text/event-stream")) {
        await readErrorResponse(response);
      }
      if (!response.body) throw new ApiTransportError("浏览器无法读取 SSE 数据流");

      reconnectAttempt = 0;
      options.onConnectionChange?.("open");
      const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
      let buffer = "";
      let lastEventWasTerminal = false;
      while (!stopped) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += value;
        const blocks = buffer.split(/\r?\n\r?\n/);
        buffer = blocks.pop() || "";
        for (const block of blocks) {
          const message = parseSseBlock(block);
          if (!message) continue;
          const envelope = assertApiEnvelope<JobEvent>(JSON.parse(message.data));
          if (envelope.internal_code !== InternalStatusCode.SUCCESS) {
            throw new ApiBusinessError(envelope);
          }
          if (message.id) lastEventId = message.id;
          const event = normalizeJobEvent(envelope.data);
          options.onEvent(event, message.id);
          lastEventWasTerminal =
            event.status === "succeeded" ||
            event.status === "failed" ||
            event.status === "cancelled";
        }
      }
      if (lastEventWasTerminal) {
        stopped = true;
        options.onConnectionChange?.("closed");
        return;
      }
      if (!stopped) throw new ApiTransportError("SSE 数据流已断开");
    } catch (error) {
      if (stopped || (error instanceof DOMException && error.name === "AbortError")) return;
      options.onError?.(error);
      if (error instanceof ApiBusinessError || error instanceof ApiProtocolError) {
        stopped = true;
        options.onConnectionChange?.("closed");
        return;
      }
      options.onConnectionChange?.("reconnecting");
      reconnectAttempt += 1;
      const delay = Math.min(30_000, retryBaseMs * 2 ** Math.min(reconnectAttempt - 1, 4));
      window.setTimeout(() => void connect(), delay);
    }
  };

  void connect();
  return {
    close: () => {
      stopped = true;
      activeController?.abort();
      options.onConnectionChange?.("closed");
    },
    getLastEventId: () => lastEventId,
  };
}

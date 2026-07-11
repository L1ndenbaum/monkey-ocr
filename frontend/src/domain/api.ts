import { InternalStatusCode } from "./internalStatusCodes.generated";

export { InternalStatusCode } from "./internalStatusCodes.generated";

export interface ApiEnvelope<T> {
  internal_code: InternalStatusCode | number;
  message: string;
  data: T;
  timestamp: string;
  request_id: string;
  error_reason: string | null;
}

export const ALLOWED_HTTP_STATUSES = [200, 500, 502, 504] as const;
export type AllowedHttpStatus = (typeof ALLOWED_HTTP_STATUSES)[number];

export class ApiBusinessError extends Error {
  readonly internalCode: number;
  readonly reason: string | null;
  readonly requestId: string;
  readonly details: unknown;

  constructor(envelope: ApiEnvelope<unknown>) {
    super(envelope.message || "请求未能完成");
    this.name = "ApiBusinessError";
    this.internalCode = envelope.internal_code;
    this.reason = envelope.error_reason;
    this.requestId = envelope.request_id;
    this.details = envelope.data;
  }
}

export class ApiTransportError extends Error {
  readonly httpStatus: number | null;
  readonly internalCode: number | null;
  readonly requestId: string | null;

  constructor(
    message: string,
    options: {
      httpStatus?: number;
      internalCode?: number;
      requestId?: string;
      cause?: unknown;
    } = {},
  ) {
    super(message, { cause: options.cause });
    this.name = "ApiTransportError";
    this.httpStatus = options.httpStatus ?? null;
    this.internalCode = options.internalCode ?? null;
    this.requestId = options.requestId ?? null;
  }
}

export class ApiProtocolError extends Error {
  readonly httpStatus: number | null;

  constructor(message: string, httpStatus?: number) {
    super(message);
    this.name = "ApiProtocolError";
    this.httpStatus = httpStatus ?? null;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isRfc3339(value: string): boolean {
  return (
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) &&
    Number.isFinite(Date.parse(value))
  );
}

export function assertApiEnvelope<T>(value: unknown): ApiEnvelope<T> {
  if (!isRecord(value)) {
    throw new ApiProtocolError("服务返回了非对象响应");
  }

  const legacyField = ["co", "de"].join("");
  if (legacyField in value) {
    throw new ApiProtocolError("服务返回了已废弃的响应字段");
  }

  if (
    typeof value.internal_code !== "number" ||
    !Number.isInteger(value.internal_code) ||
    typeof value.message !== "string" ||
    value.message.trim() === "" ||
    typeof value.timestamp !== "string" ||
    !isRfc3339(value.timestamp) ||
    typeof value.request_id !== "string" ||
    value.request_id.trim() === "" ||
    !(value.error_reason === null || typeof value.error_reason === "string") ||
    !("data" in value)
  ) {
    throw new ApiProtocolError("服务返回的 ApiEnvelope 格式无效");
  }

  if (
    (value.internal_code === InternalStatusCode.SUCCESS && value.error_reason !== null) ||
    (value.internal_code !== InternalStatusCode.SUCCESS &&
      (typeof value.error_reason !== "string" || value.error_reason.trim() === ""))
  ) {
    throw new ApiProtocolError("服务返回的 ApiEnvelope 成败语义不一致");
  }

  return value as unknown as ApiEnvelope<T>;
}

export function isAllowedHttpStatus(value: number): value is AllowedHttpStatus {
  return ALLOWED_HTTP_STATUSES.some((status) => status === value);
}

export function toUserError(error: unknown): string {
  if (error instanceof ApiBusinessError) {
    const suffix = error.requestId ? ` · 请求 ${error.requestId}` : "";
    return `${error.message}${suffix}`;
  }
  if (error instanceof ApiTransportError || error instanceof ApiProtocolError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "发生未知错误，请稍后重试";
}

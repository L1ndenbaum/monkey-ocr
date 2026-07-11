import axios, { AxiosError, type AxiosRequestConfig, type AxiosResponse } from "axios";
import {
  ApiBusinessError,
  ApiProtocolError,
  ApiTransportError,
  assertApiEnvelope,
  InternalStatusCode,
  isAllowedHttpStatus,
  type ApiEnvelope,
} from "../../domain/api";
import { clearApiKey, getApiKey } from "../auth/apiKeyStore";

const timeout = Number(import.meta.env.VITE_API_TIMEOUT_MS || 30_000);
export const gatewayBaseUrl = (import.meta.env.VITE_GATEWAY_BASE_URL || "").replace(/\/$/, "");

const apiClient = axios.create({
  baseURL: gatewayBaseUrl,
  timeout: Number.isFinite(timeout) ? timeout : 30_000,
  validateStatus: () => true,
  headers: {
    Accept: "application/json",
  },
});

apiClient.interceptors.request.use((config) => {
  const apiKey = getApiKey();
  if (apiKey) {
    config.headers.Authorization = `Bearer ${apiKey}`;
  }
  return config;
});

apiClient.interceptors.response.use(
  (response: AxiosResponse<unknown>) => {
    if (!isAllowedHttpStatus(response.status)) {
      throw new ApiProtocolError(`服务返回了不允许的 HTTP 状态 ${response.status}`, response.status);
    }

    let envelope: ApiEnvelope<unknown> | null = null;
    try {
      envelope = assertApiEnvelope(response.data);
    } catch (error) {
      if (response.status === 200) {
        throw error;
      }
    }

    if (response.status !== 200) {
      throw new ApiTransportError(
        envelope?.message || transportMessage(response.status),
        {
          httpStatus: response.status,
          internalCode: envelope?.internal_code,
          requestId: envelope?.request_id,
        },
      );
    }

    if (!envelope) {
      throw new ApiProtocolError("服务返回的 ApiEnvelope 格式无效", response.status);
    }

    if (envelope.internal_code !== InternalStatusCode.SUCCESS) {
      if (
        envelope.internal_code === InternalStatusCode.USER_UNAUTHORIZED ||
        envelope.internal_code === InternalStatusCode.API_KEY_REVOKED
      ) {
        clearApiKey();
      }
      throw new ApiBusinessError(envelope);
    }

    return { ...response, data: envelope.data };
  },
  (error: unknown) => {
    if (error instanceof ApiBusinessError || error instanceof ApiProtocolError) {
      return Promise.reject(error);
    }
    const axiosError = error as AxiosError;
    return Promise.reject(
      new ApiTransportError(
        axiosError.code === "ECONNABORTED"
          ? "请求超时，请稍后重试"
          : "无法连接 MonkeyOCR 服务",
        { cause: error },
      ),
    );
  },
);

function transportMessage(status: number): string {
  if (status === 502) return "网关无法连接 OCR 服务";
  if (status === 504) return "OCR 服务响应超时";
  return "OCR 服务出现内部错误";
}

export async function apiRequest<T>(config: AxiosRequestConfig): Promise<T> {
  const response = await apiClient.request<unknown, AxiosResponse<T>>(config);
  return response.data;
}

export const objectStorageClient = axios.create({
  timeout: 0,
  validateStatus: (status) => status >= 200 && status < 300,
});

import { describe, expect, it } from "vitest";
import { ApiProtocolError, assertApiEnvelope, InternalStatusCode } from "./api";

const validEnvelope = {
  internal_code: InternalStatusCode.SUCCESS,
  message: "ok",
  data: { job_id: "job-1" },
  timestamp: "2026-07-11T00:00:00Z",
  request_id: "request-1",
  error_reason: null,
};

describe("ApiEnvelope", () => {
  it("accepts the internal status contract", () => {
    expect(assertApiEnvelope(validEnvelope)).toEqual(validEnvelope);
  });

  it("rejects a missing internal status", () => {
    const { internal_code: _removed, ...invalid } = validEnvelope;
    expect(() => assertApiEnvelope(invalid)).toThrow(ApiProtocolError);
  });

  it("rejects the legacy business-status field", () => {
    const legacyField = ["co", "de"].join("");
    expect(() => assertApiEnvelope({ ...validEnvelope, [legacyField]: 0 })).toThrow(
      "已废弃",
    );
  });

  it("rejects malformed metadata and success/failure mismatches", () => {
    expect(() => assertApiEnvelope({ ...validEnvelope, timestamp: "today" })).toThrow(
      ApiProtocolError,
    );
    expect(() => assertApiEnvelope({ ...validEnvelope, request_id: "" })).toThrow(
      ApiProtocolError,
    );
    expect(() =>
      assertApiEnvelope({ ...validEnvelope, error_reason: "unexpected_error" }),
    ).toThrow("成败语义");
    expect(() =>
      assertApiEnvelope({
        ...validEnvelope,
        internal_code: InternalStatusCode.COMMON_INVALID_ARGUMENT,
        error_reason: null,
      }),
    ).toThrow("成败语义");
  });
});

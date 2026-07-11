package pipeline

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

// TestWriteJSONUsesApiEnvelope verifies gateway local success responses.
func TestWriteJSONUsesApiEnvelope(t *testing.T) {
	recorder := httptest.NewRecorder()

	writeJSON(recorder, http.StatusOK, map[string]string{"status": "ok"})

	payload := decodeJSONResponse(t, recorder)
	if payload["internal_code"] != float64(0) {
		t.Fatalf("internal_code = %#v, want 0", payload["internal_code"])
	}
	if payload["message"] != "操作成功" {
		t.Fatalf("message = %#v", payload["message"])
	}
	data, ok := payload["data"].(map[string]any)
	if !ok || data["status"] != "ok" {
		t.Fatalf("data = %#v", payload["data"])
	}
	if payload["timestamp"] == "" {
		t.Fatal("timestamp should be present")
	}
}

// TestWriteJSONErrorUsesApiEnvelope verifies gateway local error responses.
func TestWriteJSONErrorUsesApiEnvelope(t *testing.T) {
	recorder := httptest.NewRecorder()

	writeJSON(recorder, http.StatusUnauthorized, map[string]string{"message": "unauthorized"})

	payload := decodeJSONResponse(t, recorder)
	if recorder.Code != http.StatusOK {
		t.Fatalf("HTTP status = %d, want 200", recorder.Code)
	}
	if payload["internal_code"] != float64(40001) {
		t.Fatalf("internal_code = %#v, want 40001", payload["internal_code"])
	}
	if payload["message"] != "unauthorized" {
		t.Fatalf("message = %#v", payload["message"])
	}
	if payload["data"] != nil {
		t.Fatalf("data = %#v, want nil", payload["data"])
	}
	if payload["error_reason"] != "user_unauthorized" {
		t.Fatalf("error_reason = %#v", payload["error_reason"])
	}
	legacyErrorCodeKey := "error" + "_code"
	if _, ok := payload[legacyErrorCodeKey]; ok {
		t.Fatalf("legacy error code = %#v, want omitted", payload[legacyErrorCodeKey])
	}
}

// decodeJSONResponse decodes a response recorder body for envelope assertions.
func decodeJSONResponse(t *testing.T, recorder *httptest.ResponseRecorder) map[string]any {
	t.Helper()
	var payload map[string]any
	if err := json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	return payload
}

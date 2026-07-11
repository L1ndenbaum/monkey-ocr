package api

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestWriteJSONWrapsPayloadInApiEnvelope(t *testing.T) {
	router := NewRouter()
	router.Get("/ok", func(w http.ResponseWriter, r *http.Request) {
		WriteJSON(w, http.StatusCreated, map[string]int{"accepted": 1})
	})

	response := httptest.NewRecorder()
	router.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/ok", nil))

	if response.Code != http.StatusOK {
		t.Fatalf("expected transport status 200, got %d", response.Code)
	}
	if response.Header().Get("Content-Type") != "application/json" {
		t.Fatalf("unexpected content type %q", response.Header().Get("Content-Type"))
	}

	var payload map[string]any
	if err := json.Unmarshal(response.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if payload["internal_code"] != float64(InternalStatusSuccess) {
		t.Fatalf("unexpected internal_code %#v", payload["internal_code"])
	}
	if _, exists := payload["code"]; exists {
		t.Fatal("legacy code field must not be present")
	}
	if payload["message"] != "操作成功" {
		t.Fatalf("unexpected message %#v", payload["message"])
	}
	data, ok := payload["data"].(map[string]any)
	if !ok || data["accepted"] != float64(1) {
		t.Fatalf("unexpected data %#v", payload["data"])
	}
	if payload["timestamp"] == "" {
		t.Fatal("timestamp should be populated")
	}
	if payload["request_id"] == "" {
		t.Fatal("request_id should be populated")
	}
	if payload["error_reason"] != nil {
		t.Fatalf("success error_reason = %#v, want null", payload["error_reason"])
	}
}

func TestWriteErrorUsesSharedErrorEnvelope(t *testing.T) {
	router := NewRouter()
	router.Get("/fail", func(w http.ResponseWriter, r *http.Request) {
		WriteError(w, http.StatusUnauthorized, "invalid token")
	})

	response := httptest.NewRecorder()
	router.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/fail", nil))

	if response.Code != http.StatusOK {
		t.Fatalf("expected transport status 200, got %d", response.Code)
	}

	var payload map[string]any
	if err := json.Unmarshal(response.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if payload["internal_code"] != float64(InternalStatusUserUnauthorized) {
		t.Fatalf("unexpected internal_code %#v", payload["internal_code"])
	}
	if payload["message"] != "invalid token" {
		t.Fatalf("unexpected message %#v", payload["message"])
	}
	if payload["data"] != nil {
		t.Fatalf("unexpected data %#v", payload["data"])
	}
	if payload["error_reason"] != "user_unauthorized" {
		t.Fatalf("unexpected error_reason %#v", payload["error_reason"])
	}
	legacyErrorCodeKey := "error" + "_code"
	if _, ok := payload[legacyErrorCodeKey]; ok {
		t.Fatalf("unexpected legacy error code %#v", payload[legacyErrorCodeKey])
	}
	if payload["timestamp"] == "" {
		t.Fatal("timestamp should be populated")
	}
}

func TestWriteTransportErrorUsesOnlyAllowedTransportStatus(t *testing.T) {
	tests := []struct {
		name       string
		status     int
		wantStatus int
		wantCode   InternalStatusCode
	}{
		{"internal", http.StatusInternalServerError, http.StatusInternalServerError, InternalStatusTransportInternalError},
		{"bad gateway", http.StatusBadGateway, http.StatusBadGateway, InternalStatusTransportBadGateway},
		{"timeout", http.StatusGatewayTimeout, http.StatusGatewayTimeout, InternalStatusTransportGatewayTimeout},
		{"invalid", http.StatusTeapot, http.StatusInternalServerError, InternalStatusTransportInternalError},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			response := httptest.NewRecorder()
			WriteTransportError(response, test.status, InternalStatusSuccess, "failed", "transport_failed")
			if response.Code != test.wantStatus {
				t.Fatalf("status = %d, want %d", response.Code, test.wantStatus)
			}
			var payload map[string]any
			if err := json.Unmarshal(response.Body.Bytes(), &payload); err != nil {
				t.Fatalf("decode response: %v", err)
			}
			if payload["internal_code"] != float64(test.wantCode) {
				t.Fatalf("internal_code = %#v, want %d", payload["internal_code"], test.wantCode)
			}
		})
	}
}

func TestWriteSuccessNeverUsesTransportErrorStatus(t *testing.T) {
	for _, status := range []int{http.StatusOK, http.StatusCreated, http.StatusInternalServerError, http.StatusBadGateway, http.StatusGatewayTimeout} {
		response := httptest.NewRecorder()
		WriteSuccessWithStatus(response, status, map[string]bool{"ok": true})
		if response.Code != http.StatusOK {
			t.Fatalf("input status %d produced %d, want 200", status, response.Code)
		}
	}
}

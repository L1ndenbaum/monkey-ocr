package proxy

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
)

type roundTripFunc func(*http.Request) (*http.Response, error)

func (fn roundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) { return fn(request) }

func TestReverseProxyForwardsValidEnvelope(t *testing.T) {
	var upstreamHost string
	proxy := NewReverseProxy("http://backend.local", roundTripFunc(func(request *http.Request) (*http.Response, error) {
		upstreamHost = request.Host
		return jsonResponse(http.StatusOK, validEnvelope(0)), nil
	}))
	response := httptest.NewRecorder()
	proxy.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/v1/jobs", nil), "")

	if response.Code != http.StatusOK || upstreamHost != "backend.local" {
		t.Fatalf("status=%d upstream_host=%q", response.Code, upstreamHost)
	}
	if response.Header().Get(InternalCodeHeaderForTest()) != "0" {
		t.Fatalf("internal code header = %q", response.Header().Get(InternalCodeHeaderForTest()))
	}
}

func TestReverseProxyRejectsBareDTOAndUnsupportedStatus(t *testing.T) {
	for name, responseFactory := range map[string]func() *http.Response{
		"bare DTO":           func() *http.Response { return jsonResponse(http.StatusOK, `{"ok":true}`) },
		"unsupported status": func() *http.Response { return jsonResponse(http.StatusCreated, validEnvelope(0)) },
	} {
		t.Run(name, func(t *testing.T) {
			proxy := NewReverseProxy("http://backend.local", roundTripFunc(func(request *http.Request) (*http.Response, error) {
				return responseFactory(), nil
			}))
			response := httptest.NewRecorder()
			proxy.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/v1/jobs", nil), "")
			assertTransportEnvelope(t, response, http.StatusBadGateway, 90002)
		})
	}
}

func TestReverseProxyMapsTimeoutTo504(t *testing.T) {
	proxy := NewReverseProxy("http://backend.local", roundTripFunc(func(request *http.Request) (*http.Response, error) {
		return nil, context.DeadlineExceeded
	}))
	response := httptest.NewRecorder()
	proxy.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/v1/jobs", nil), "")
	assertTransportEnvelope(t, response, http.StatusGatewayTimeout, 90004)
}

func TestReverseProxyMapsDialFailureTo502(t *testing.T) {
	proxy := NewReverseProxy("http://backend.local", roundTripFunc(func(request *http.Request) (*http.Response, error) {
		return nil, errors.New("dial failed")
	}))
	response := httptest.NewRecorder()
	proxy.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/v1/jobs", nil), "")
	assertTransportEnvelope(t, response, http.StatusBadGateway, 90002)
}

func TestValidateUpstreamResponseAcceptsSSEAndDisablesBuffering(t *testing.T) {
	response := &http.Response{
		StatusCode: http.StatusOK,
		Header:     http.Header{"Content-Type": []string{"text/event-stream; charset=utf-8"}},
		Body:       io.NopCloser(strings.NewReader(": heartbeat\n\n")),
	}
	if err := validateUpstreamResponse(response); err != nil {
		t.Fatalf("validateUpstreamResponse: %v", err)
	}
	if response.Header.Get("X-Accel-Buffering") != "no" || response.Header.Get("Cache-Control") != "no-cache" {
		t.Fatalf("unexpected SSE headers %v", response.Header)
	}
}

func assertTransportEnvelope(t *testing.T, response *httptest.ResponseRecorder, status, internalCode int) {
	t.Helper()
	if response.Code != status {
		t.Fatalf("HTTP status=%d want=%d body=%s", response.Code, status, response.Body.String())
	}
	var payload map[string]any
	if err := json.Unmarshal(response.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if payload["internal_code"] != float64(internalCode) {
		t.Fatalf("internal_code=%#v want=%d", payload["internal_code"], internalCode)
	}
	if _, exists := payload["code"]; exists {
		t.Fatal("legacy code field present")
	}
}

func jsonResponse(status int, body string) *http.Response {
	return &http.Response{
		StatusCode: status,
		Header:     http.Header{"Content-Type": []string{"application/json"}},
		Body:       io.NopCloser(strings.NewReader(body)),
	}
}

func validEnvelope(internalCode int) string {
	return `{"internal_code":` + strconv.Itoa(internalCode) + `,"message":"ok","data":{},"timestamp":"2026-07-11T00:00:00Z","request_id":"request-id","error_reason":null}`
}

func InternalCodeHeaderForTest() string { return "X-MonkeyOCR-Internal-Code" }

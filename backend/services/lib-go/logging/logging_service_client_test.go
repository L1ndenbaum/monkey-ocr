package logging

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"sync"
	"testing"
	"time"
)

func TestLoggingServiceClientEmitsEventToLoggingService(t *testing.T) {
	t.Helper()

	var capturedPath string
	var capturedToken string
	var capturedRequestID string
	var capturedPayload logEventIngestRequest

	transport := roundTripFunc(func(r *http.Request) (*http.Response, error) {
		capturedPath = r.URL.Path
		capturedToken = r.Header.Get("X-Logging-Service-Token")
		capturedRequestID = r.Header.Get("X-Request-ID")
		if err := json.NewDecoder(r.Body).Decode(&capturedPayload); err != nil {
			t.Fatalf("decode payload: %v", err)
		}
		return &http.Response{
			StatusCode: http.StatusOK,
			Header:     make(http.Header),
			Body:       io.NopCloser(strings.NewReader(successLoggingEnvelope)),
		}, nil
	})

	client := NewLoggingServiceClient(LoggingServiceClientConfig{
		BaseURL: "http://logging-service:13004",
		Token:   "service-token",
		Client:  &http.Client{Transport: transport},
	})
	event := LogEvent{
		Timestamp: time.Date(2026, 5, 16, 15, 22, 0, 0, time.FixedZone("CST", 8*3600)),
		Level:     LogLevelInfo,
		Service:   "monkeyocr-gateway",
		Message:   "gateway request",
		TraceID:   "req-1",
		Metadata: struct {
			RequestID string `json:"request_id"`
		}{RequestID: "req-1"},
	}

	if err := client.Emit(context.Background(), event); err != nil {
		t.Fatalf("emit event: %v", err)
	}
	closeCtx, closeCancel := context.WithTimeout(context.Background(), time.Second)
	defer closeCancel()
	if err := client.Close(closeCtx); err != nil {
		t.Fatalf("close client: %v", err)
	}

	if capturedPath != "/v1/log-events" {
		t.Fatalf("path = %q, want /v1/log-events", capturedPath)
	}
	if capturedToken != "service-token" {
		t.Fatalf("token header = %q, want service-token", capturedToken)
	}
	if capturedRequestID != "req-1" {
		t.Fatalf("request id header = %q, want req-1", capturedRequestID)
	}
	if capturedPayload.Event.Service != "monkeyocr-gateway" {
		t.Fatalf("service = %q, want monkeyocr-gateway", capturedPayload.Event.Service)
	}
	if capturedPayload.Event.TraceID != "req-1" {
		t.Fatalf("trace id = %q, want req-1", capturedPayload.Event.TraceID)
	}
	if capturedPayload.Event.EventID == "" {
		t.Fatal("event_id was not assigned before delivery")
	}
}

func TestLoggingServiceClientDrainsQueuedEventsOnClose(t *testing.T) {
	recorder := &recordingTransport{}
	client := NewLoggingServiceClient(LoggingServiceClientConfig{
		BaseURL:   "http://logging-service:13004",
		Client:    &http.Client{Transport: recorder},
		QueueSize: 2,
	})

	if err := client.Emit(context.Background(), testLogEvent("req-1")); err != nil {
		t.Fatalf("emit first event: %v", err)
	}
	if err := client.Emit(context.Background(), testLogEvent("req-2")); err != nil {
		t.Fatalf("emit second event: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	if err := client.Close(ctx); err != nil {
		t.Fatalf("close client: %v", err)
	}
	if got := recorder.Count(); got != 2 {
		t.Fatalf("delivered events = %d, want 2", got)
	}
}

func TestLoggingServiceClientDropsWhenQueueIsFullWithoutBlocking(t *testing.T) {
	started := make(chan struct{})
	unblock := make(chan struct{})
	recorder := &recordingTransport{block: unblock, started: started}
	client := NewLoggingServiceClient(LoggingServiceClientConfig{
		BaseURL:   "http://logging-service:13004",
		Client:    &http.Client{Transport: recorder},
		QueueSize: 1,
		Timeout:   time.Second,
	})

	_ = client.Emit(context.Background(), testLogEvent("req-1"))
	<-started
	_ = client.Emit(context.Background(), testLogEvent("req-2"))
	start := time.Now()
	_ = client.Emit(context.Background(), testLogEvent("req-3"))
	if elapsed := time.Since(start); elapsed > 50*time.Millisecond {
		t.Fatalf("Emit blocked for %s on full queue", elapsed)
	}

	close(unblock)
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	if err := client.Close(ctx); err != nil {
		t.Fatalf("close client: %v", err)
	}
	if got := recorder.Count(); got > 2 {
		t.Fatalf("delivered events = %d, want at most 2 after one drop", got)
	}
}

func TestLoggingServiceClientUsesTimeoutContextForDelivery(t *testing.T) {
	observed := make(chan error, 1)
	client := NewLoggingServiceClient(LoggingServiceClientConfig{
		BaseURL: "http://logging-service:13004",
		Client: &http.Client{Transport: roundTripFunc(func(request *http.Request) (*http.Response, error) {
			<-request.Context().Done()
			observed <- request.Context().Err()
			return nil, request.Context().Err()
		})},
		QueueSize: 1,
		Timeout:   10 * time.Millisecond,
	})

	_ = client.Emit(context.Background(), testLogEvent("req-slow"))

	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	if err := client.Close(ctx); err != nil {
		t.Fatalf("close client: %v", err)
	}

	select {
	case err := <-observed:
		if err != context.DeadlineExceeded {
			t.Fatalf("delivery context error = %v, want deadline exceeded", err)
		}
	default:
		t.Fatal("transport did not observe delivery timeout")
	}
}

func testLogEvent(traceID string) LogEvent {
	return LogEvent{
		Timestamp: time.Date(2026, 5, 16, 15, 22, 0, 0, time.FixedZone("CST", 8*3600)),
		Level:     LogLevelInfo,
		Service:   "monkeyocr-gateway",
		Message:   "gateway request",
		TraceID:   traceID,
		Metadata: struct {
			RequestID string `json:"request_id"`
		}{RequestID: traceID},
	}
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (fn roundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) {
	return fn(request)
}

type recordingTransport struct {
	mu      sync.Mutex
	count   int
	block   <-chan struct{}
	started chan struct{}
}

func (transport *recordingTransport) RoundTrip(_ *http.Request) (*http.Response, error) {
	if transport.started != nil {
		select {
		case <-transport.started:
		default:
			close(transport.started)
		}
	}
	if transport.block != nil {
		<-transport.block
	}
	transport.mu.Lock()
	transport.count++
	transport.mu.Unlock()
	return &http.Response{
		StatusCode: http.StatusOK,
		Header:     make(http.Header),
		Body:       io.NopCloser(strings.NewReader(successLoggingEnvelope)),
	}, nil
}

const successLoggingEnvelope = `{"internal_code":0,"message":"操作成功","data":{"accepted":1},"timestamp":"2026-07-11T00:00:00Z","request_id":"req-1","error_reason":null}`

func (transport *recordingTransport) Count() int {
	transport.mu.Lock()
	defer transport.mu.Unlock()
	return transport.count
}

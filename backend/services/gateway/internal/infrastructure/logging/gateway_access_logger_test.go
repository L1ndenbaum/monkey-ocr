package logging

import (
	"context"
	domainlogging "monkeyocr-gateway/internal/domain/logging"
	"sync"
	"testing"
	"time"

	sharedlogging "monkeyocr-services-lib-go/logging"
)

type captureEmitter struct {
	mu     sync.Mutex
	events []sharedlogging.LogEvent
}

func (emitter *captureEmitter) Emit(_ context.Context, event sharedlogging.LogEvent) error {
	emitter.mu.Lock()
	defer emitter.mu.Unlock()
	emitter.events = append(emitter.events, event)
	return nil
}

func (emitter *captureEmitter) Count() int {
	emitter.mu.Lock()
	defer emitter.mu.Unlock()
	return len(emitter.events)
}

func (emitter *captureEmitter) Event(index int) sharedlogging.LogEvent {
	emitter.mu.Lock()
	defer emitter.mu.Unlock()
	return emitter.events[index]
}

func TestAsyncAccessLoggerConvertsAccessLogEventToSharedLogEvent(t *testing.T) {
	emitter := &captureEmitter{}
	logger := NewGatewayAccessLogger(GatewayAccessLoggerConfig{
		Emitter: emitter,
	})

	logger.Emit(testAccessLogEvent("req-1"))

	if emitter.Count() != 1 {
		t.Fatalf("events = %d, want 1", emitter.Count())
	}
	event := emitter.Event(0)
	if event.TraceID != "req-1" || event.Service != "monkeyocr-gateway" || event.Message != "gateway request" {
		t.Fatalf("converted event identity mismatch: %#v", event)
	}
	metadata, ok := event.Metadata.(domainlogging.AccessLogMetadata)
	if !ok {
		t.Fatalf("metadata type = %T, want gateway access log metadata", event.Metadata)
	}
	if metadata.RequestID != "req-1" {
		t.Fatalf("metadata request id = %q, want req-1", metadata.RequestID)
	}
}

func TestAsyncAccessLoggerDelegatesClose(t *testing.T) {
	emitter := &closeableCaptureEmitter{}
	logger := NewGatewayAccessLogger(GatewayAccessLoggerConfig{
		Emitter: emitter,
	})

	closeCtx, closeCancel := context.WithTimeout(context.Background(), time.Second)
	defer closeCancel()
	if err := logger.Close(closeCtx); err != nil {
		t.Fatalf("close logger: %v", err)
	}
	if !emitter.closed {
		t.Fatal("expected wrapper to delegate Close to the underlying emitter")
	}
}

type closeableCaptureEmitter struct {
	captureEmitter
	closed bool
}

func (emitter *closeableCaptureEmitter) Close(_ context.Context) error {
	emitter.closed = true
	return nil
}

func testAccessLogEvent(requestID string) domainlogging.AccessLogEvent {
	return domainlogging.AccessLogEvent{
		Timestamp: time.Date(2026, 5, 16, 15, 22, 0, 0, time.UTC),
		Level:     sharedlogging.LogLevelInfo,
		Service:   "monkeyocr-gateway",
		Message:   "gateway request",
		TraceID:   requestID,
		Metadata: domainlogging.AccessLogMetadata{
			RequestID: requestID,
		},
	}
}

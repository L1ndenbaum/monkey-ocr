package logging

import (
	"context"
	"testing"
	"time"
)

type captureEmitter struct {
	events []LogEvent
}

func (emitter *captureEmitter) Emit(_ context.Context, event LogEvent) error {
	emitter.events = append(emitter.events, event)
	return nil
}

func TestAppLoggerInfoBuildsServiceEvent(t *testing.T) {
	emitter := &captureEmitter{}
	logger := NewAppLogger(AppLoggerConfig{
		Service: "monkeyocr-backend",
		Emitter: emitter,
		Now: func() time.Time {
			return time.Date(2026, 5, 16, 15, 30, 0, 0, time.FixedZone("CST", 8*3600))
		},
	})

	if err := logger.Info(context.Background(), "user created", "req-1", map[string]any{
		"logger":  "monkeyocr.tests",
		"user_id": "user-1",
	}); err != nil {
		t.Fatalf("emit info: %v", err)
	}

	if len(emitter.events) != 1 {
		t.Fatalf("events = %d, want 1", len(emitter.events))
	}
	event := emitter.events[0]
	if event.Level != LogLevelInfo {
		t.Fatalf("level = %q, want %q", event.Level, LogLevelInfo)
	}
	if event.Service != "monkeyocr-backend" {
		t.Fatalf("service = %q, want monkeyocr-backend", event.Service)
	}
	if event.Message != "user created" || event.TraceID != "req-1" {
		t.Fatalf("event identity mismatch: %#v", event)
	}
}

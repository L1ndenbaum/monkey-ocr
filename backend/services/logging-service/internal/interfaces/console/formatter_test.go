package console

import (
	"strings"
	"testing"
	"time"

	domain "monkeyocr-logging-service/internal/domain/logging"
)

func TestFormatterUsesConfiguredSeparatorAndMessageJSON(t *testing.T) {
	event := domain.LogEvent{
		Timestamp: time.Date(2026, 5, 12, 10, 20, 30, 123000000, time.UTC),
		Level:     domain.LogLevelInfo,
		Service:   "payment-service",
		Message:   "payment succeeded",
		TraceID:   "abc",
		Metadata:  map[string]any{"order_id": "o_123", "amount": float64(100)},
	}

	line, err := FormatLine(event, false)
	if err != nil {
		t.Fatalf("FormatLine returned error: %v", err)
	}

	parts := strings.Split(line, Separator)
	if len(parts) != 4 {
		t.Fatalf("expected 4 separated parts, got %d in %q", len(parts), line)
	}
	if parts[0] != "2026-05-12T10:20:30.123Z" {
		t.Fatalf("unexpected timestamp part: %q", parts[0])
	}
	if parts[1] != "INFO   " {
		t.Fatalf("unexpected level part: %q", parts[1])
	}
	if parts[2] != "payment-service               " {
		t.Fatalf("unexpected service part: %q", parts[2])
	}
	if !strings.Contains(parts[3], `"timestamp":"2026-05-12T10:20:30.123Z"`) {
		t.Fatalf("message json missing timestamp: %q", parts[3])
	}
	if !strings.Contains(parts[3], `"level":"INFO"`) {
		t.Fatalf("message json missing level: %q", parts[3])
	}
	if !strings.Contains(parts[3], `"service":"payment-service"`) {
		t.Fatalf("message json missing service: %q", parts[3])
	}
	if !strings.Contains(parts[3], `"message":"payment succeeded"`) {
		t.Fatalf("message json missing message: %q", parts[3])
	}
	if !strings.Contains(parts[3], `"trace_id":"abc"`) {
		t.Fatalf("message json missing trace id: %q", parts[3])
	}
	if !strings.Contains(parts[3], `"metadata":{"amount":100,"order_id":"o_123"}`) {
		t.Fatalf("message json missing metadata: %q", parts[3])
	}
}

// TestFormatterPreservesEventTimestampOffset ensures console output keeps producer offsets.
func TestFormatterPreservesEventTimestampOffset(t *testing.T) {
	event := domain.LogEvent{
		Timestamp: time.Date(2026, 5, 16, 15, 22, 52, 742000000, time.FixedZone("CST", 8*3600)),
		Level:     domain.LogLevelInfo,
		Service:   "monkeyocr-gateway",
		Message:   "gateway request",
		TraceID:   "req-1",
		Metadata:  map[string]any{},
	}

	line, err := FormatLine(event, false)
	if err != nil {
		t.Fatalf("FormatLine returned error: %v", err)
	}

	parts := strings.Split(line, Separator)
	if parts[0] != "2026-05-16T15:22:52.742+08:00" {
		t.Fatalf("unexpected timestamp part: %q", parts[0])
	}
	if !strings.Contains(parts[3], `"timestamp":"2026-05-16T15:22:52.742+08:00"`) {
		t.Fatalf("message json did not preserve timestamp offset: %q", parts[3])
	}
}

func TestFormatterAlignsWarningLevelAndTruncatesLongService(t *testing.T) {
	event := domain.LogEvent{
		Timestamp: time.Date(2026, 5, 12, 10, 20, 30, 0, time.UTC),
		Level:     domain.LogLevelWarning,
		Service:   "medical_backend:very.long.service.module.name",
		Message:   "slow query",
		TraceID:   "trace-1",
		Metadata:  map[string]any{},
	}

	line, err := FormatLine(event, false)
	if err != nil {
		t.Fatalf("FormatLine returned error: %v", err)
	}

	parts := strings.Split(line, Separator)
	if len(parts) != 4 {
		t.Fatalf("expected 4 separated parts, got %d in %q", len(parts), line)
	}
	if parts[1] != "WARNING" {
		t.Fatalf("unexpected level part: %q", parts[1])
	}
	if parts[2] != "medical_backend:very.long.s..." {
		t.Fatalf("unexpected service part: %q", parts[2])
	}
	if len([]rune(parts[2])) != 30 {
		t.Fatalf("service part length = %d, want 30", len([]rune(parts[2])))
	}
}

func TestFormatterAppliesAuditColor(t *testing.T) {
	event := domain.LogEvent{
		Timestamp: time.Date(2026, 5, 12, 10, 20, 30, 0, time.UTC),
		Level:     domain.LogLevelAudit,
		Service:   "access-service",
		Message:   "role changed",
		TraceID:   "req-1",
		Metadata:  map[string]any{},
	}

	line, err := FormatLine(event, true)
	if err != nil {
		t.Fatalf("FormatLine returned error: %v", err)
	}

	if !strings.Contains(line, "\x1b[38;5;208mAUDIT  \x1b[0m") {
		t.Fatalf("audit level was not colored orange: %q", line)
	}
}

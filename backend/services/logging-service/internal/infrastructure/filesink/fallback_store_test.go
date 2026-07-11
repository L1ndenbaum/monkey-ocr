package filesink

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"

	domain "monkeyocr-logging-service/internal/domain/logging"
)

type recordingPublisher struct {
	mu     sync.Mutex
	err    error
	events []domain.LogEvent
}

func (publisher *recordingPublisher) Publish(_ context.Context, events []domain.LogEvent) error {
	publisher.mu.Lock()
	defer publisher.mu.Unlock()

	publisher.events = append(publisher.events, events...)
	return publisher.err
}

func (publisher *recordingPublisher) count() int {
	publisher.mu.Lock()
	defer publisher.mu.Unlock()

	return len(publisher.events)
}

func TestKafkaFallbackStorePartitionsRegularAndErrorAuditEvents(t *testing.T) {
	dir := t.TempDir()
	regularPath := filepath.Join(dir, "kafka_invalid_temp_events.jsonl")
	errorAuditPath := filepath.Join(dir, "kafka_invalid_temp_error_audit_events.jsonl")
	store := NewKafkaFallbackStore(regularPath, errorAuditPath)

	events := []domain.LogEvent{
		testEvent(domain.LogLevelInfo, "info-1"),
		testEvent(domain.LogLevelWarning, "warning-1"),
		testEvent(domain.LogLevelError, "error-1"),
		testEvent(domain.LogLevelAudit, "audit-1"),
	}
	if err := store.WriteBatch(context.Background(), events); err != nil {
		t.Fatalf("WriteBatch returned error: %v", err)
	}

	if got := countJSONLines(t, regularPath); got != 2 {
		t.Fatalf("regular fallback lines = %d, want 2", got)
	}
	if got := countJSONLines(t, errorAuditPath); got != 2 {
		t.Fatalf("error/audit fallback lines = %d, want 2", got)
	}
}

func TestKafkaFallbackStoreReplaysFilesToKafkaAndClearsThem(t *testing.T) {
	dir := t.TempDir()
	regularPath := filepath.Join(dir, "kafka_invalid_temp_events.jsonl")
	errorAuditPath := filepath.Join(dir, "kafka_invalid_temp_error_audit_events.jsonl")
	store := NewKafkaFallbackStore(regularPath, errorAuditPath)
	publisher := &recordingPublisher{}

	if err := store.WriteBatch(context.Background(), []domain.LogEvent{
		testEvent(domain.LogLevelInfo, "info-1"),
		testEvent(domain.LogLevelError, "error-1"),
	}); err != nil {
		t.Fatalf("WriteBatch returned error: %v", err)
	}
	if err := store.ReplayOnce(context.Background(), publisher); err != nil {
		t.Fatalf("ReplayOnce returned error: %v", err)
	}

	if publisher.count() != 2 {
		t.Fatalf("replayed events = %d, want 2", publisher.count())
	}
	if got := countJSONLines(t, regularPath); got != 0 {
		t.Fatalf("regular fallback lines after replay = %d, want 0", got)
	}
	if got := countJSONLines(t, errorAuditPath); got != 0 {
		t.Fatalf("error/audit fallback lines after replay = %d, want 0", got)
	}
}

func TestKafkaFallbackStoreKeepsFilesWhenReplayPublishFails(t *testing.T) {
	dir := t.TempDir()
	regularPath := filepath.Join(dir, "kafka_invalid_temp_events.jsonl")
	errorAuditPath := filepath.Join(dir, "kafka_invalid_temp_error_audit_events.jsonl")
	store := NewKafkaFallbackStore(regularPath, errorAuditPath)
	publisher := &recordingPublisher{err: errors.New("kafka unavailable")}

	if err := store.WriteBatch(context.Background(), []domain.LogEvent{
		testEvent(domain.LogLevelInfo, "info-1"),
	}); err != nil {
		t.Fatalf("WriteBatch returned error: %v", err)
	}
	if err := store.ReplayOnce(context.Background(), publisher); err == nil {
		t.Fatal("ReplayOnce returned nil error, want kafka error")
	}

	if got := countJSONLines(t, regularPath); got != 1 {
		t.Fatalf("regular fallback lines after failed replay = %d, want 1", got)
	}
}

func testEvent(level domain.LogLevel, message string) domain.LogEvent {
	return domain.LogEvent{
		EventID:   "00000000-0000-4000-8000-000000000001",
		Timestamp: time.Date(2026, 5, 18, 12, 0, 0, 0, time.UTC),
		Level:     level,
		Service:   "monkeyocr-backend",
		Message:   message,
		TraceID:   "req-1",
		Metadata:  map[string]any{},
	}
}

func countJSONLines(t *testing.T, path string) int {
	t.Helper()

	file, err := os.Open(path)
	if errors.Is(err, os.ErrNotExist) {
		return 0
	}
	if err != nil {
		t.Fatalf("open %s: %v", path, err)
	}
	defer file.Close()

	scanner := bufio.NewScanner(file)
	count := 0
	for scanner.Scan() {
		var event domain.LogEvent
		if err := json.Unmarshal(scanner.Bytes(), &event); err != nil {
			t.Fatalf("decode line in %s: %v", path, err)
		}
		count++
	}
	if err := scanner.Err(); err != nil {
		t.Fatalf("scan %s: %v", path, err)
	}
	return count
}

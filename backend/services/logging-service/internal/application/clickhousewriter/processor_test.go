package clickhousewriter

import (
	"context"
	"encoding/json"
	"errors"
	"testing"
	"time"

	domain "monkeyocr-logging-service/internal/domain/logging"
)

type recordingInserter struct {
	err    error
	events []domain.LogEvent
}

func (inserter *recordingInserter) InsertEvents(_ context.Context, events []domain.LogEvent) error {
	inserter.events = append(inserter.events, events...)
	return inserter.err
}

type recordingCommitter struct {
	messages []Message
}

func (committer *recordingCommitter) Commit(_ context.Context, messages []Message) error {
	committer.messages = append(committer.messages, messages...)
	return nil
}

func TestProcessBatchInsertsEventsAndCommitsOffsetsAfterSuccess(t *testing.T) {
	inserter := &recordingInserter{}
	committer := &recordingCommitter{}
	messages := []Message{{Value: marshalEvent(t, testWriterEvent("event-1"))}}

	if err := ProcessBatch(context.Background(), messages, inserter, committer); err != nil {
		t.Fatalf("ProcessBatch returned error: %v", err)
	}

	if len(inserter.events) != 1 {
		t.Fatalf("inserted events = %d, want 1", len(inserter.events))
	}
	if len(committer.messages) != 1 {
		t.Fatalf("committed messages = %d, want 1", len(committer.messages))
	}
}

func TestProcessBatchDoesNotCommitOffsetsWhenInsertFails(t *testing.T) {
	inserter := &recordingInserter{err: errors.New("clickhouse unavailable")}
	committer := &recordingCommitter{}
	messages := []Message{{Value: marshalEvent(t, testWriterEvent("event-1"))}}

	if err := ProcessBatch(context.Background(), messages, inserter, committer); err == nil {
		t.Fatal("ProcessBatch returned nil error, want insert error")
	}

	if len(committer.messages) != 0 {
		t.Fatalf("committed messages after insert failure = %d, want 0", len(committer.messages))
	}
}

func marshalEvent(t *testing.T, event domain.LogEvent) []byte {
	t.Helper()

	payload, err := json.Marshal(event)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	return payload
}

func testWriterEvent(eventID string) domain.LogEvent {
	return domain.LogEvent{
		EventID:   eventID,
		Timestamp: time.Date(2026, 5, 18, 12, 0, 0, 0, time.UTC),
		Level:     domain.LogLevelInfo,
		Service:   "monkeyocr-backend",
		Message:   "backend request",
		TraceID:   "req-1",
		Metadata:  map[string]any{},
	}
}

package logging

import (
	"context"
	"errors"
	"sync"
	"testing"
	"time"

	domain "monkeyocr-logging-service/internal/domain/logging"
)

type recordingSink struct {
	mu      sync.Mutex
	batches [][]domain.LogEvent
}

func (sink *recordingSink) WriteBatch(_ context.Context, events []domain.LogEvent) error {
	sink.mu.Lock()
	defer sink.mu.Unlock()

	copied := append([]domain.LogEvent(nil), events...)
	sink.batches = append(sink.batches, copied)
	return nil
}

func (sink *recordingSink) count() int {
	sink.mu.Lock()
	defer sink.mu.Unlock()

	count := 0
	for _, batch := range sink.batches {
		count += len(batch)
	}
	return count
}

func (sink *recordingSink) events() []domain.LogEvent {
	sink.mu.Lock()
	defer sink.mu.Unlock()

	var events []domain.LogEvent
	for _, batch := range sink.batches {
		events = append(events, batch...)
	}
	return events
}

type recordingPublisher struct {
	mu      sync.Mutex
	err     error
	batches [][]domain.LogEvent
}

func (publisher *recordingPublisher) Publish(_ context.Context, events []domain.LogEvent) error {
	publisher.mu.Lock()
	defer publisher.mu.Unlock()

	copied := append([]domain.LogEvent(nil), events...)
	publisher.batches = append(publisher.batches, copied)
	return publisher.err
}

func (publisher *recordingPublisher) count() int {
	publisher.mu.Lock()
	defer publisher.mu.Unlock()

	count := 0
	for _, batch := range publisher.batches {
		count += len(batch)
	}
	return count
}

func (publisher *recordingPublisher) events() []domain.LogEvent {
	publisher.mu.Lock()
	defer publisher.mu.Unlock()

	var events []domain.LogEvent
	for _, batch := range publisher.batches {
		events = append(events, batch...)
	}
	return events
}

func TestServiceFlushesQueuedEventsOnInterval(t *testing.T) {
	sink := &recordingSink{}
	service := NewService(Config{
		FlushInterval: 25 * time.Millisecond,
		QueueSize:     10,
	}, []BatchSink{sink}, nil)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	service.Start(ctx)

	err := service.Ingest(ctx, []domain.LogEvent{
		{Timestamp: time.Now().UTC(), Level: domain.LogLevelInfo, Service: "backend", Message: "one", TraceID: "req-1", Metadata: map[string]any{}},
		{Timestamp: time.Now().UTC(), Level: domain.LogLevelError, Service: "backend", Message: "two", TraceID: "req-2", Metadata: map[string]any{}},
	})
	if err != nil {
		t.Fatalf("Ingest returned error: %v", err)
	}

	deadline := time.After(500 * time.Millisecond)
	for sink.count() < 2 {
		select {
		case <-deadline:
			t.Fatalf("expected 2 flushed events, got %d", sink.count())
		default:
			time.Sleep(10 * time.Millisecond)
		}
	}
}

func TestServiceAssignsEventIDBeforePublishing(t *testing.T) {
	publisher := &recordingPublisher{}
	service := NewServiceWithFallback(Config{
		FlushInterval: 25 * time.Millisecond,
		QueueSize:     10,
	}, nil, nil, publisher)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	service.Start(ctx)

	err := service.Ingest(ctx, []domain.LogEvent{
		{Timestamp: time.Now().UTC(), Level: domain.LogLevelInfo, Service: "backend", Message: "one", TraceID: "req-1", Metadata: map[string]any{}},
	})
	if err != nil {
		t.Fatalf("Ingest returned error: %v", err)
	}

	deadline := time.After(500 * time.Millisecond)
	for publisher.count() < 1 {
		select {
		case <-deadline:
			t.Fatal("expected event to be published")
		default:
			time.Sleep(10 * time.Millisecond)
		}
	}
	if eventID := publisher.events()[0].EventID; eventID == "" {
		t.Fatal("published event_id is empty")
	}
}

func TestServiceWritesFallbackOnlyWhenKafkaPublishFails(t *testing.T) {
	publisher := &recordingPublisher{err: errors.New("kafka unavailable")}
	fallback := &recordingSink{}
	service := NewServiceWithFallback(Config{
		FlushInterval: 25 * time.Millisecond,
		QueueSize:     10,
	}, nil, fallback, publisher)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	service.Start(ctx)

	err := service.Ingest(ctx, []domain.LogEvent{
		{Timestamp: time.Now().UTC(), Level: domain.LogLevelInfo, Service: "backend", Message: "one", TraceID: "req-1", Metadata: map[string]any{}},
	})
	if err != nil {
		t.Fatalf("Ingest returned error: %v", err)
	}

	deadline := time.After(500 * time.Millisecond)
	for fallback.count() < 1 {
		select {
		case <-deadline:
			t.Fatalf("expected fallback event after kafka failure, got %d", fallback.count())
		default:
			time.Sleep(10 * time.Millisecond)
		}
	}
	if publisher.count() != 1 {
		t.Fatalf("publisher events = %d, want 1 attempted event", publisher.count())
	}
}

func TestServiceDoesNotWriteFallbackWhenKafkaPublishSucceeds(t *testing.T) {
	publisher := &recordingPublisher{}
	fallback := &recordingSink{}
	service := NewServiceWithFallback(Config{
		FlushInterval: 25 * time.Millisecond,
		QueueSize:     10,
	}, nil, fallback, publisher)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	service.Start(ctx)

	err := service.Ingest(ctx, []domain.LogEvent{
		{Timestamp: time.Now().UTC(), Level: domain.LogLevelInfo, Service: "backend", Message: "one", TraceID: "req-1", Metadata: map[string]any{}},
	})
	if err != nil {
		t.Fatalf("Ingest returned error: %v", err)
	}

	deadline := time.After(500 * time.Millisecond)
	for publisher.count() < 1 {
		select {
		case <-deadline:
			t.Fatal("expected event to be published")
		default:
			time.Sleep(10 * time.Millisecond)
		}
	}
	if fallback.count() != 0 {
		t.Fatalf("fallback events = %d, want 0", fallback.count())
	}
}

func TestServiceShutdownDrainsQueuedEventsBeforeReturning(t *testing.T) {
	publisher := &recordingPublisher{}
	fallback := &recordingSink{}
	service := NewServiceWithFallback(Config{
		FlushInterval: time.Hour,
		QueueSize:     10,
	}, nil, fallback, publisher)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	service.Start(ctx)

	err := service.Ingest(ctx, []domain.LogEvent{
		{Timestamp: time.Now().UTC(), Level: domain.LogLevelInfo, Service: "backend", Message: "queued", TraceID: "req-queued", Metadata: map[string]any{}},
	})
	if err != nil {
		t.Fatalf("Ingest returned error: %v", err)
	}

	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), time.Second)
	defer shutdownCancel()
	if err := service.Shutdown(shutdownCtx); err != nil {
		t.Fatalf("Shutdown returned error: %v", err)
	}
	if publisher.count() != 1 {
		t.Fatalf("published events after shutdown = %d, want 1", publisher.count())
	}
	if fallback.count() != 0 {
		t.Fatalf("fallback events after successful shutdown publish = %d, want 0", fallback.count())
	}
}

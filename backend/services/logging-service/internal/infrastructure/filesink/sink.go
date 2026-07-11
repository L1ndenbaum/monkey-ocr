package filesink

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"sync"
	"time"

	domain "monkeyocr-logging-service/internal/domain/logging"
)

// Filter decides whether a sink should persist a specific event.
type Filter func(domain.LogEvent) bool

// Sink appends filtered log events to a JSONL file.
type Sink struct {
	path   string
	filter Filter
	mu     sync.Mutex
}

// Publisher sends recovered fallback events back to Kafka.
type Publisher interface {
	Publish(context.Context, []domain.LogEvent) error
}

// KafkaFallbackStore stores events only when Kafka publishing is unavailable.
type KafkaFallbackStore struct {
	regularPath    string
	errorAuditPath string
	mu             sync.Mutex
}

// NewKafkaFallbackStore creates the two temporary files used while Kafka is down.
func NewKafkaFallbackStore(regularPath, errorAuditPath string) *KafkaFallbackStore {
	return &KafkaFallbackStore{
		regularPath:    regularPath,
		errorAuditPath: errorAuditPath,
	}
}

// WriteBatch partitions failed Kafka events into regular and error/audit files.
func (store *KafkaFallbackStore) WriteBatch(ctx context.Context, events []domain.LogEvent) error {
	store.mu.Lock()
	defer store.mu.Unlock()

	var regularEvents []domain.LogEvent
	var errorAuditEvents []domain.LogEvent
	for _, event := range events {
		if ErrorAndAuditOnly(event) {
			errorAuditEvents = append(errorAuditEvents, event)
			continue
		}
		regularEvents = append(regularEvents, event)
	}

	if err := appendEvents(ctx, store.regularPath, regularEvents); err != nil {
		return err
	}
	return appendEvents(ctx, store.errorAuditPath, errorAuditEvents)
}

// ReplayOnce publishes each temporary file back to Kafka and clears it on success.
func (store *KafkaFallbackStore) ReplayOnce(ctx context.Context, publisher Publisher) error {
	if publisher == nil {
		return nil
	}

	store.mu.Lock()
	defer store.mu.Unlock()

	if err := store.replayFile(ctx, store.regularPath, publisher); err != nil {
		return err
	}
	return store.replayFile(ctx, store.errorAuditPath, publisher)
}

// StartReplay launches a background loop that retries temporary file replay.
func (store *KafkaFallbackStore) StartReplay(ctx context.Context, publisher Publisher, interval time.Duration) {
	if interval <= 0 {
		interval = 5 * time.Second
	}
	go func() {
		ticker := time.NewTicker(interval)
		defer ticker.Stop()
		for {
			select {
			case <-ticker.C:
				_ = store.ReplayOnce(ctx, publisher)
			case <-ctx.Done():
				return
			}
		}
	}()
}

func (store *KafkaFallbackStore) replayFile(ctx context.Context, path string, publisher Publisher) error {
	events, err := readEvents(path)
	if err != nil {
		return err
	}
	if len(events) == 0 {
		return nil
	}
	if err := publisher.Publish(ctx, events); err != nil {
		return err
	}
	return truncateFile(path)
}

func appendEvents(_ context.Context, path string, events []domain.LogEvent) error {
	if len(events) == 0 {
		return nil
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	file, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		return err
	}
	defer file.Close()

	encoder := json.NewEncoder(file)
	for _, event := range events {
		if err := encoder.Encode(event); err != nil {
			return err
		}
	}
	return nil
}

func readEvents(path string) ([]domain.LogEvent, error) {
	file, err := os.Open(path)
	if errors.Is(err, os.ErrNotExist) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	defer file.Close()

	var events []domain.LogEvent
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		if len(scanner.Bytes()) == 0 {
			continue
		}
		var event domain.LogEvent
		if err := json.Unmarshal(scanner.Bytes(), &event); err != nil {
			return nil, err
		}
		events = append(events, event)
	}
	if err := scanner.Err(); err != nil {
		return nil, err
	}
	return events, nil
}

func truncateFile(path string) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	return os.WriteFile(path, nil, 0o644)
}

// New creates a file sink for the target path and optional filter.
func New(path string, filter Filter) *Sink {
	return &Sink{path: path, filter: filter}
}

// ErrorAndAuditOnly keeps ERROR and AUDIT events for durable local archive.
func ErrorAndAuditOnly(event domain.LogEvent) bool {
	return event.Level == domain.LogLevelError || event.Level == domain.LogLevelAudit
}

// AllEvents keeps every event, which is useful for the local spool file.
func AllEvents(domain.LogEvent) bool {
	return true
}

// WriteBatch filters a batch and appends the selected events as JSON lines.
func (sink *Sink) WriteBatch(_ context.Context, events []domain.LogEvent) error {
	filtered := make([]domain.LogEvent, 0, len(events))
	for _, event := range events {
		if sink.filter == nil || sink.filter(event) {
			filtered = append(filtered, event)
		}
	}
	if len(filtered) == 0 {
		return nil
	}

	sink.mu.Lock()
	defer sink.mu.Unlock()

	if err := os.MkdirAll(filepath.Dir(sink.path), 0o755); err != nil {
		return err
	}
	file, err := os.OpenFile(sink.path, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		return err
	}
	defer file.Close()

	encoder := json.NewEncoder(file)
	for _, event := range filtered {
		if err := encoder.Encode(event); err != nil {
			return err
		}
	}
	return nil
}

package clickhousewriter

import (
	"context"
	"encoding/json"

	domain "monkeyocr-logging-service/internal/domain/logging"
)

// Message is the Kafka payload and offset handle consumed by the writer.
type Message struct {
	Value  []byte
	Handle any
}

// Inserter persists a decoded log batch to ClickHouse.
type Inserter interface {
	InsertEvents(context.Context, []domain.LogEvent) error
}

// Committer commits Kafka offsets only after ClickHouse insert succeeds.
type Committer interface {
	Commit(context.Context, []Message) error
}

// ProcessBatch decodes Kafka messages, writes them to ClickHouse, then commits offsets.
func ProcessBatch(
	ctx context.Context,
	messages []Message,
	inserter Inserter,
	committer Committer,
) error {
	if len(messages) == 0 {
		return nil
	}

	events := make([]domain.LogEvent, 0, len(messages))
	for _, message := range messages {
		var event domain.LogEvent
		if err := json.Unmarshal(message.Value, &event); err != nil {
			return err
		}
		events = append(events, event)
	}

	if err := inserter.InsertEvents(ctx, events); err != nil {
		return err
	}
	return committer.Commit(ctx, messages)
}

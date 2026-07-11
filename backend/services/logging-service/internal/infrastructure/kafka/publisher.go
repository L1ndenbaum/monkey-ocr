package kafka

import (
	"context"
	"encoding/json"

	domain "monkeyocr-logging-service/internal/domain/logging"
	sharedkafka "monkeyocr-services-lib-go/mq/kafka"
)

// Publisher adapts logging-domain events to the shared KafkaPublisher base.
type Publisher struct {
	base *sharedkafka.KafkaPublisher
}

// NewPublisher creates a Kafka publisher for the configured brokers and topic.
func NewPublisher(brokers []string, topic string) *Publisher {
	return &Publisher{
		base: sharedkafka.NewKafkaPublisher(sharedkafka.Config{
			Brokers: brokers,
			Topic:   topic,
		}),
	}
}

// Check verifies that a broker is reachable and the configured topic is visible.
func (publisher *Publisher) Check(ctx context.Context) error {
	return publisher.base.Check(ctx)
}

// Publish serializes a batch of events and sends them as Kafka messages.
func (publisher *Publisher) Publish(ctx context.Context, events []domain.LogEvent) error {
	if len(events) == 0 {
		return nil
	}

	messages := make([]sharedkafka.Message, 0, len(events))
	for _, event := range events {
		payload, err := json.Marshal(event)
		if err != nil {
			return err
		}
		messages = append(messages, sharedkafka.Message{
			Key:   []byte(event.TraceID),
			Value: payload,
			Time:  event.Timestamp,
		})
	}
	return publisher.base.Publish(ctx, messages)
}

// Close releases the underlying Kafka writer.
func (publisher *Publisher) Close() error {
	return publisher.base.Close()
}

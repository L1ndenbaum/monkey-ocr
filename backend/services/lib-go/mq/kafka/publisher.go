package kafka

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	segmentio "github.com/segmentio/kafka-go"
)

// Config defines the shared Kafka publisher connection and topic settings.
type Config struct {
	Brokers      []string
	Topic        string
	BatchTimeout time.Duration
}

// Message is the transport-neutral message shape accepted by KafkaPublisher.
type Message struct {
	Key   []byte
	Value []byte
	Time  time.Time
}

// KafkaPublisher owns the kafka-go writer shared by service-specific publishers.
type KafkaPublisher struct {
	brokers []string
	topic   string
	writer  *segmentio.Writer
}

// NewKafkaPublisher creates a Kafka publisher for the configured brokers and topic.
func NewKafkaPublisher(cfg Config) *KafkaPublisher {
	batchTimeout := cfg.BatchTimeout
	if batchTimeout <= 0 {
		batchTimeout = 100 * time.Millisecond
	}

	return &KafkaPublisher{
		brokers: cfg.Brokers,
		topic:   cfg.Topic,
		writer: &segmentio.Writer{
			Addr:         segmentio.TCP(cfg.Brokers...),
			Topic:        cfg.Topic,
			RequiredAcks: segmentio.RequireOne,
			Balancer:     &segmentio.Hash{},
			BatchTimeout: batchTimeout,
		},
	}
}

// Check verifies that a broker is reachable and the configured topic is visible.
func (publisher *KafkaPublisher) Check(ctx context.Context) error {
	if len(publisher.brokers) == 0 {
		return errors.New("kafka brokers are required")
	}
	if strings.TrimSpace(publisher.topic) == "" {
		return errors.New("kafka topic is required")
	}

	var failures []string
	for _, broker := range publisher.brokers {
		broker = strings.TrimSpace(broker)
		if broker == "" {
			continue
		}

		conn, err := segmentio.DialContext(ctx, "tcp", broker)
		if err != nil {
			failures = append(failures, fmt.Sprintf("%s: %v", broker, err))
			continue
		}

		partitions, readErr := conn.ReadPartitions(publisher.topic)
		closeErr := conn.Close()
		if readErr != nil {
			failures = append(failures, fmt.Sprintf("%s topic %q: %v", broker, publisher.topic, readErr))
			continue
		}
		if closeErr != nil {
			failures = append(failures, fmt.Sprintf("%s close: %v", broker, closeErr))
			continue
		}
		if len(partitions) == 0 {
			failures = append(failures, fmt.Sprintf("%s topic %q has no partitions", broker, publisher.topic))
			continue
		}
		return nil
	}

	if len(failures) == 0 {
		return errors.New("kafka brokers are required")
	}
	return fmt.Errorf("kafka startup check failed for topic %q: %s", publisher.topic, strings.Join(failures, "; "))
}

// Publish sends a batch of already-serialized messages to Kafka.
func (publisher *KafkaPublisher) Publish(ctx context.Context, messages []Message) error {
	if len(messages) == 0 {
		return nil
	}

	kafkaMessages := make([]segmentio.Message, 0, len(messages))
	for _, message := range messages {
		kafkaMessages = append(kafkaMessages, segmentio.Message{
			Key:   message.Key,
			Value: message.Value,
			Time:  message.Time,
		})
	}
	return publisher.writer.WriteMessages(ctx, kafkaMessages...)
}

// Close releases the underlying Kafka writer.
func (publisher *KafkaPublisher) Close() error {
	return publisher.writer.Close()
}

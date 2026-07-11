package kafka

import (
	"context"
	"strings"
	"testing"
)

func TestKafkaPublisherCheckRejectsMissingBrokers(t *testing.T) {
	publisher := NewKafkaPublisher(Config{Topic: "monkeyocr.events.logging.v1"})
	defer publisher.Close()

	err := publisher.Check(context.Background())
	if err == nil {
		t.Fatal("expected missing brokers to be rejected")
	}
	if !strings.Contains(err.Error(), "brokers") {
		t.Fatalf("expected broker error, got %v", err)
	}
}

func TestKafkaPublisherCheckRejectsMissingTopic(t *testing.T) {
	publisher := NewKafkaPublisher(Config{Brokers: []string{"kafka:9092"}})
	defer publisher.Close()

	err := publisher.Check(context.Background())
	if err == nil {
		t.Fatal("expected missing topic to be rejected")
	}
	if !strings.Contains(err.Error(), "topic") {
		t.Fatalf("expected topic error, got %v", err)
	}
}

func TestKafkaPublisherRejectsBlankBrokers(t *testing.T) {
	publisher := NewKafkaPublisher(Config{
		Brokers: []string{" ", "\t"},
		Topic:   "monkeyocr.events.logging.v1",
	})
	defer publisher.Close()

	err := publisher.Check(context.Background())
	if err == nil {
		t.Fatal("expected blank brokers to be rejected")
	}
	if !strings.Contains(err.Error(), "brokers") {
		t.Fatalf("expected broker error, got %v", err)
	}
}

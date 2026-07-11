package kafka

import (
	"context"
	"strings"
	"testing"
)

func TestCheckRejectsMissingKafkaConfig(t *testing.T) {
	publisher := NewPublisher(nil, "")
	defer publisher.Close()

	err := publisher.Check(context.Background())
	if err == nil {
		t.Fatal("expected startup check to reject missing config")
	}
	if !strings.Contains(err.Error(), "brokers") {
		t.Fatalf("expected error to mention brokers, got %v", err)
	}
}

func TestCheckRejectsMissingKafkaTopic(t *testing.T) {
	publisher := NewPublisher([]string{"kafka:9092"}, "")
	defer publisher.Close()

	err := publisher.Check(context.Background())
	if err == nil {
		t.Fatal("expected startup check to reject missing topic")
	}
	if !strings.Contains(err.Error(), "topic") {
		t.Fatalf("expected error to mention topic, got %v", err)
	}
}

func TestCheckRejectsBlankKafkaBrokers(t *testing.T) {
	publisher := NewPublisher([]string{" ", "\t"}, "monkeyocr.events.logging.v1")
	defer publisher.Close()

	err := publisher.Check(context.Background())
	if err == nil {
		t.Fatal("expected startup check to reject blank brokers")
	}
	if !strings.Contains(err.Error(), "brokers") {
		t.Fatalf("expected error to mention brokers, got %v", err)
	}
}

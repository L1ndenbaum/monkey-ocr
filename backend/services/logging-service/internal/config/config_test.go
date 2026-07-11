package config

import (
	"reflect"
	"testing"
	"time"
)

func TestLoadDoesNotExposeKafkaOptionalSwitch(t *testing.T) {
	configType := reflect.TypeOf(Load())
	if _, ok := configType.FieldByName("Kafka" + "Enabled"); ok {
		t.Fatal("Config must not expose Kafka enabled switch because Kafka is required")
	}
}

func TestLoadReadsKafkaBrokersAndTopic(t *testing.T) {
	t.Setenv("LOGGING_KAFKA_BROKERS", "kafka-a:9092,kafka-b:9092")
	t.Setenv("LOGGING_KAFKA_TOPIC", "monkeyocr.events.logging.v1")

	cfg := Load()

	if !reflect.DeepEqual(cfg.KafkaBrokers, []string{"kafka-a:9092", "kafka-b:9092"}) {
		t.Fatalf("unexpected brokers: %#v", cfg.KafkaBrokers)
	}
	if cfg.KafkaTopic != "monkeyocr.events.logging.v1" {
		t.Fatalf("unexpected topic: %q", cfg.KafkaTopic)
	}
}

func TestLoadUsesKafkaInvalidTempFileDefaults(t *testing.T) {
	cfg := Load()

	if cfg.SpoolFile != "/var/lib/logging-service/spool/kafka_invalid_temp_events.jsonl" {
		t.Fatalf("unexpected spool file: %q", cfg.SpoolFile)
	}
	if cfg.ErrorAuditFile != "/var/lib/logging-service/archive/kafka_invalid_temp_error_audit_events.jsonl" {
		t.Fatalf("unexpected error audit file: %q", cfg.ErrorAuditFile)
	}
}

func TestLoadReadsHTTPTimeouts(t *testing.T) {
	t.Setenv("LOGGING_SERVICE_READ_HEADER_TIMEOUT", "2s")
	t.Setenv("LOGGING_SERVICE_READ_TIMEOUT", "7s")
	t.Setenv("LOGGING_SERVICE_WRITE_TIMEOUT", "8s")
	t.Setenv("LOGGING_SERVICE_IDLE_TIMEOUT", "9s")
	t.Setenv("LOGGING_SERVICE_SHUTDOWN_TIMEOUT", "10s")

	cfg := Load()

	if cfg.ReadHeaderTimeout != 2*time.Second {
		t.Fatalf("unexpected read header timeout: %s", cfg.ReadHeaderTimeout)
	}
	if cfg.ReadTimeout != 7*time.Second {
		t.Fatalf("unexpected read timeout: %s", cfg.ReadTimeout)
	}
	if cfg.WriteTimeout != 8*time.Second {
		t.Fatalf("unexpected write timeout: %s", cfg.WriteTimeout)
	}
	if cfg.IdleTimeout != 9*time.Second {
		t.Fatalf("unexpected idle timeout: %s", cfg.IdleTimeout)
	}
	if cfg.ShutdownTimeout != 10*time.Second {
		t.Fatalf("unexpected shutdown timeout: %s", cfg.ShutdownTimeout)
	}
}

func TestLoadUsesSafeHTTPTimeoutDefaults(t *testing.T) {
	cfg := Load()

	if cfg.ReadHeaderTimeout <= 0 {
		t.Fatal("read header timeout must be enabled")
	}
	if cfg.ReadTimeout <= 0 {
		t.Fatal("read timeout must be enabled")
	}
	if cfg.WriteTimeout <= 0 {
		t.Fatal("write timeout must be enabled")
	}
	if cfg.IdleTimeout <= 0 {
		t.Fatal("idle timeout must be enabled")
	}
	if cfg.ShutdownTimeout <= 0 {
		t.Fatal("shutdown timeout must be enabled")
	}
}

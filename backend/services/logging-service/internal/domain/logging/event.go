package logging

import (
	"errors"
	"fmt"
	"strings"
	"time"
)

// LogLevel is the severity value exchanged through the logging-service contract.
type LogLevel string

const (
	// LogLevelDebug describes diagnostic events with the lowest severity.
	LogLevelDebug LogLevel = "DEBUG"
	// LogLevelInfo describes normal operational events.
	LogLevelInfo LogLevel = "INFO"
	// LogLevelWarning describes recoverable abnormal events.
	LogLevelWarning LogLevel = "WARNING"
	// LogLevelError describes failed operations that should be persisted.
	LogLevelError LogLevel = "ERROR"
	// LogLevelAudit describes audit-relevant events that should be persisted.
	LogLevelAudit LogLevel = "AUDIT"
)

var validLevels = map[LogLevel]struct{}{
	LogLevelDebug:   {},
	LogLevelInfo:    {},
	LogLevelWarning: {},
	LogLevelError:   {},
	LogLevelAudit:   {},
}

// LogEvent is the canonical event record accepted from backend services.
type LogEvent struct {
	EventID   string         `json:"event_id"`
	Timestamp time.Time      `json:"timestamp"`
	Level     LogLevel       `json:"level"`
	Service   string         `json:"service"`
	Message   string         `json:"message"`
	TraceID   string         `json:"trace_id"`
	Metadata  map[string]any `json:"metadata"`
}

// Validate checks that the level is part of the v1 logging contract.
func (level LogLevel) Validate() error {
	if _, ok := validLevels[level]; ok {
		return nil
	}
	return fmt.Errorf("invalid log level %q", level)
}

// ValidateEvent verifies the fields required before an event enters the batch pipeline.
func ValidateEvent(event LogEvent) error {
	if strings.TrimSpace(event.EventID) == "" {
		return errors.New("event_id is required")
	}
	if event.Timestamp.IsZero() {
		return errors.New("timestamp is required")
	}
	if err := event.Level.Validate(); err != nil {
		return err
	}
	if strings.TrimSpace(event.Service) == "" {
		return errors.New("service is required")
	}
	if strings.TrimSpace(event.Message) == "" {
		return errors.New("message is required")
	}
	if event.Metadata == nil {
		return errors.New("metadata is required")
	}
	return nil
}

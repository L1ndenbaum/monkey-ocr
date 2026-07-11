package logging

import "time"

// LogLevel is the severity value exchanged with logging-service.
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

// LogEvent is the canonical event record accepted by logging-service.
type LogEvent struct {
	EventID   string    `json:"event_id"`
	Timestamp time.Time `json:"timestamp"`
	Level     LogLevel  `json:"level"`
	Service   string    `json:"service"`
	Message   string    `json:"message"`
	TraceID   string    `json:"trace_id"`
	Metadata  any       `json:"metadata"`
}

type logEventIngestRequest struct {
	Event LogEvent `json:"event"`
}

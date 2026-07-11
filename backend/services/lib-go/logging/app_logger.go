package logging

import (
	"context"
	"time"
)

// AppLoggerConfig configures an application-facing service logger.
type AppLoggerConfig struct {
	Service string
	Emitter Emitter
	Now     func() time.Time
}

// AppLogger is a small facade for module code that emits service log events.
type AppLogger struct {
	service string
	emitter Emitter
	now     func() time.Time
}

// NewAppLogger creates an application-facing logger facade.
func NewAppLogger(config AppLoggerConfig) *AppLogger {
	now := config.Now
	if now == nil {
		now = time.Now
	}
	return &AppLogger{
		service: config.Service,
		emitter: config.Emitter,
		now:     now,
	}
}

// Debug emits a DEBUG service event.
func (logger *AppLogger) Debug(ctx context.Context, message string, traceID string, metadata map[string]any) error {
	return logger.emit(ctx, LogLevelDebug, message, traceID, metadata)
}

// Info emits an INFO service event.
func (logger *AppLogger) Info(ctx context.Context, message string, traceID string, metadata map[string]any) error {
	return logger.emit(ctx, LogLevelInfo, message, traceID, metadata)
}

// Warning emits a WARNING service event.
func (logger *AppLogger) Warning(ctx context.Context, message string, traceID string, metadata map[string]any) error {
	return logger.emit(ctx, LogLevelWarning, message, traceID, metadata)
}

// Error emits an ERROR service event.
func (logger *AppLogger) Error(ctx context.Context, message string, traceID string, metadata map[string]any) error {
	return logger.emit(ctx, LogLevelError, message, traceID, metadata)
}

// emit builds a LogEvent and delegates delivery to the configured emitter.
func (logger *AppLogger) emit(ctx context.Context, level LogLevel, message string, traceID string, metadata map[string]any) error {
	if logger.emitter == nil {
		return nil
	}
	if metadata == nil {
		metadata = map[string]any{}
	}
	return logger.emitter.Emit(ctx, LogEvent{
		Timestamp: logger.now(),
		Level:     level,
		Service:   logger.service,
		Message:   message,
		TraceID:   traceID,
		Metadata:  metadata,
	})
}

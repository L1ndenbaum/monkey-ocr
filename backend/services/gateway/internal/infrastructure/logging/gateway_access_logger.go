package logging

import (
	"context"
	"monkeyocr-gateway/internal/domain/logging"

	sharedlogging "monkeyocr-services-lib-go/logging"
)

// GatewayAccessLoggerConfig controls asynchronous gateway access log delivery.
type GatewayAccessLoggerConfig struct {
	Emitter sharedlogging.Emitter
}

// GatewayAccessLogger buffers access log events and delivers them from a worker.
type GatewayAccessLogger struct {
	emitter sharedlogging.Emitter
}

// NewGatewayAccessLogger creates a gateway access log adapter.
func NewGatewayAccessLogger(config GatewayAccessLoggerConfig) *GatewayAccessLogger {
	return &GatewayAccessLogger{emitter: config.Emitter}
}

// Emit converts one gateway access log event to the shared logging contract.
func (logger *GatewayAccessLogger) Emit(event logging.AccessLogEvent) {
	if logger.emitter == nil {
		return
	}
	_ = logger.emitter.Emit(context.Background(), event.ToLogEvent())
}

// Close delegates draining to close-capable logging emitters.
func (logger *GatewayAccessLogger) Close(ctx context.Context) error {
	closer, ok := logger.emitter.(interface {
		Close(context.Context) error
	})
	if !ok {
		return nil
	}
	return closer.Close(ctx)
}

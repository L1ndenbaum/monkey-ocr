package console

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"strings"

	domain "monkeyocr-logging-service/internal/domain/logging"
)

// Separator is the plain-text delimiter used by logging-service console output.
const Separator = "   |   "

const reset = "\x1b[0m"

const (
	levelWidth   = 7
	serviceWidth = 30
	ellipsis     = "..."
)

var levelColors = map[domain.LogLevel]string{
	domain.LogLevelDebug:   "\x1b[32m",
	domain.LogLevelInfo:    "\x1b[37m",
	domain.LogLevelWarning: "\x1b[33m",
	domain.LogLevelError:   "\x1b[31m",
	domain.LogLevelAudit:   "\x1b[38;5;208m",
}

// FormatLine renders one event as timestamp, level, service, and JSON message fields.
func FormatLine(event domain.LogEvent, color bool) (string, error) {
	message, err := json.Marshal(event)
	if err != nil {
		return "", err
	}

	level := padRight(string(event.Level), levelWidth)
	if color {
		if colorCode, ok := levelColors[event.Level]; ok {
			level = colorCode + level + reset
		}
	}
	service := formatService(event.Service)

	return strings.Join([]string{
		event.Timestamp.Format("2006-01-02T15:04:05.000Z07:00"),
		level,
		service,
		string(message),
	}, Separator), nil
}

// padRight left-aligns value to width using spaces.
func padRight(value string, width int) string {
	length := len([]rune(value))
	if length >= width {
		return value
	}
	return value + strings.Repeat(" ", width-length)
}

// formatService left-aligns service names and truncates long values with ellipsis.
func formatService(service string) string {
	runes := []rune(service)
	if len(runes) > serviceWidth {
		prefixWidth := serviceWidth - len([]rune(ellipsis))
		return string(runes[:prefixWidth]) + ellipsis
	}
	return padRight(service, serviceWidth)
}

// Sink writes formatted events to a console writer.
type Sink struct {
	Writer io.Writer
	Color  bool
}

// WriteBatch prints each event in the batch using the console formatter.
func (sink *Sink) WriteBatch(_ context.Context, events []domain.LogEvent) error {
	for _, event := range events {
		line, err := FormatLine(event, sink.Color)
		if err != nil {
			return err
		}
		if _, err := fmt.Fprintln(sink.Writer, line); err != nil {
			return err
		}
	}
	return nil
}

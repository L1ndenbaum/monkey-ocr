package deps

import "monkeyocr-gateway/internal/domain/logging"

// AccessLogger accepts completed gateway access log events.
type AccessLogger interface {
	Emit(logging.AccessLogEvent)
}

package httpapi

import domain "monkeyocr-logging-service/internal/domain/logging"

// logEventIngestRequest mirrors the v1 single-event JSON envelope.
type logEventIngestRequest struct {
	Event domain.LogEvent `json:"event"`
}

// logEventBatchIngestRequest mirrors the v1 batch JSON envelope.
type logEventBatchIngestRequest struct {
	Events []domain.LogEvent `json:"events"`
}

package httpapi

import (
	"net/http"

	applogging "monkeyocr-logging-service/internal/application/logging"
	domain "monkeyocr-logging-service/internal/domain/logging"
	sharedhttp "monkeyocr-services-lib-go/http/api"
)

// Handler exposes the HTTP API used by backend services to emit log events.
type Handler struct {
	service      *applogging.Service
	serviceToken string
}

// NewHandler binds the application service and shared service token to HTTP handlers.
func NewHandler(service *applogging.Service, serviceToken string) *Handler {
	return &Handler{service: service, serviceToken: serviceToken}
}

// HandleHealth reports process liveness.
func (handler *Handler) HandleHealth(w http.ResponseWriter, r *http.Request) {
	sharedhttp.WriteJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

// HandleLogEvent accepts one LogEvent and enqueues it for batched processing.
func (handler *Handler) HandleLogEvent(w http.ResponseWriter, r *http.Request) {
	var request logEventIngestRequest
	if !sharedhttp.DecodeJSON(w, r, &request, sharedhttp.DefaultJSONBodyLimit) {
		return
	}

	if err := handler.service.Ingest(r.Context(), []domain.LogEvent{request.Event}); err != nil {
		sharedhttp.WriteBusinessError(w, sharedhttp.InternalStatusCommonInvalidArgument, "日志事件无效", "invalid_log_event")
		return
	}

	sharedhttp.WriteJSON(w, http.StatusOK, map[string]int{"accepted": 1})
}

// HandleLogEventBatch accepts multiple LogEvent records in one request.
func (handler *Handler) HandleLogEventBatch(w http.ResponseWriter, r *http.Request) {
	var request logEventBatchIngestRequest
	if !sharedhttp.DecodeJSON(w, r, &request, sharedhttp.DefaultJSONBodyLimit) {
		return
	}

	if err := handler.service.Ingest(r.Context(), request.Events); err != nil {
		sharedhttp.WriteBusinessError(w, sharedhttp.InternalStatusCommonInvalidArgument, "日志事件批次无效", "invalid_log_event_batch")
		return
	}

	sharedhttp.WriteJSON(w, http.StatusOK, map[string]int{"accepted": len(request.Events)})
}

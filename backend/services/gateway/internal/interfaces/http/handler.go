package httpapi

import (
	appgateway "monkeyocr-gateway/internal/application/pipeline"
	"net/http"
)

// Handler adapts incoming HTTP requests to the application gateway pipeline.
type Handler struct {
	pipeline *appgateway.Pipeline
}

// NewHandler creates thin HTTP handlers backed by the application pipeline.
func NewHandler(pipeline *appgateway.Pipeline) *Handler {
	return &Handler{pipeline: pipeline}
}

// HandleHealth adapts the gateway-local health route.
func (handler *Handler) HandleHealth(w http.ResponseWriter, r *http.Request) {
	handler.pipeline.HandleHealth(NewResponseRecorder(w), r)
}

// HandleProxy adapts all upstream gateway routes.
func (handler *Handler) HandleProxy(w http.ResponseWriter, r *http.Request) {
	handler.pipeline.HandleProxy(NewResponseRecorder(w), r)
}

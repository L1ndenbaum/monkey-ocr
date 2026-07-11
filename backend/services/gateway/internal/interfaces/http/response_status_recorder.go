package httpapi

import (
	"net/http"
	"strconv"

	sharedapi "monkeyocr-services-lib-go/http/api"
)

// ResponseStatusRecorder captures the final response status while preserving HTTP interfaces.
type ResponseStatusRecorder struct {
	http.ResponseWriter
	status       int
	internalCode int
	hasCode      bool
}

// NewResponseRecorder wraps a ResponseWriter for gateway pipeline status capture.
func NewResponseRecorder(w http.ResponseWriter) *ResponseStatusRecorder {
	return &ResponseStatusRecorder{ResponseWriter: w}
}

// Unwrap exposes the underlying ResponseWriter to net/http response controllers.
func (recorder *ResponseStatusRecorder) Unwrap() http.ResponseWriter {
	return recorder.ResponseWriter
}

// Flush forwards streaming flushes for SSE and other long-lived responses.
func (recorder *ResponseStatusRecorder) Flush() {
	if flusher, ok := recorder.ResponseWriter.(http.Flusher); ok {
		flusher.Flush()
	}
}

// WriteHeader records the final HTTP response status.
func (recorder *ResponseStatusRecorder) WriteHeader(status int) {
	if raw := recorder.Header().Get(sharedapi.InternalCodeHeader); raw != "" {
		if internalCode, err := strconv.Atoi(raw); err == nil {
			recorder.internalCode = internalCode
			recorder.hasCode = true
		}
		recorder.Header().Del(sharedapi.InternalCodeHeader)
	}
	recorder.status = status
	recorder.ResponseWriter.WriteHeader(status)
}

// Write records an implicit 200 status before writing the body.
func (recorder *ResponseStatusRecorder) Write(data []byte) (int, error) {
	if recorder.status == 0 {
		recorder.status = http.StatusOK
	}
	return recorder.ResponseWriter.Write(data)
}

// Status returns the recorded status, defaulting to 200 for untouched responses.
func (recorder *ResponseStatusRecorder) Status() int {
	if recorder.status == 0 {
		return http.StatusOK
	}
	return recorder.status
}

// InternalCode returns the business status captured before the private
// correlation header is removed from the public response.
func (recorder *ResponseStatusRecorder) InternalCode() (int, bool) {
	return recorder.internalCode, recorder.hasCode
}

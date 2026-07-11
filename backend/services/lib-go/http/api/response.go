package api

import (
	"encoding/json"
	"net/http"
	"strconv"
	"time"

	sharedheaders "monkeyocr-services-lib-go/http/headers"
)

// InternalCodeHeader is used inside the process so gateway access logging can
// capture the business status without buffering response bodies. The gateway
// response recorder removes it before sending public responses.
const InternalCodeHeader = "X-MonkeyOCR-Internal-Code"

// WriteJSON is the compatibility name for writing a successful response. The
// supplied HTTP status is normalized to the allowed transport status set.
func WriteJSON(w http.ResponseWriter, status int, payload any) {
	WriteSuccessWithStatus(w, status, payload)
}

// WriteSuccess writes an HTTP 200 success envelope.
func WriteSuccess(w http.ResponseWriter, payload any) {
	WriteSuccessWithStatus(w, http.StatusOK, payload)
}

// WriteSuccessWithStatus writes a success envelope over HTTP 200. The status
// argument exists only for source compatibility with conventional HTTP
// handlers; a successful ApiEnvelope may never use a transport-error status.
func WriteSuccessWithStatus(w http.ResponseWriter, status int, payload any) {
	writeEnvelope(w, http.StatusOK, ApiEnvelope[any]{
		InternalCode: InternalStatusSuccess,
		Message:      "操作成功",
		Data:         payload,
		Timestamp:    time.Now().UTC().Format(time.RFC3339Nano),
		RequestID:    requestIDFromWriter(w),
		ErrorReason:  nil,
	})
}

// WriteBusinessError writes a controlled business result over HTTP 200.
func WriteBusinessError(w http.ResponseWriter, internalCode InternalStatusCode, message, reason string) {
	writeEnvelope(w, http.StatusOK, ApiEnvelope[any]{
		InternalCode: internalCode,
		Message:      message,
		Data:         nil,
		Timestamp:    time.Now().UTC().Format(time.RFC3339Nano),
		RequestID:    requestIDFromWriter(w),
		ErrorReason:  reasonPointer(reason),
	})
}

// WriteTransportError writes one of the three permitted transport failures.
func WriteTransportError(w http.ResponseWriter, status int, internalCode InternalStatusCode, message, reason string) {
	switch status {
	case http.StatusBadGateway:
		internalCode = InternalStatusTransportBadGateway
	case http.StatusGatewayTimeout:
		internalCode = InternalStatusTransportGatewayTimeout
	case http.StatusInternalServerError:
		internalCode = InternalStatusTransportInternalError
	default:
		status = http.StatusInternalServerError
		internalCode = InternalStatusTransportInternalError
	}
	writeEnvelope(w, status, ApiEnvelope[any]{
		InternalCode: internalCode,
		Message:      message,
		Data:         nil,
		Timestamp:    time.Now().UTC().Format(time.RFC3339Nano),
		RequestID:    requestIDFromWriter(w),
		ErrorReason:  reasonPointer(reason),
	})
}

// WriteError maps legacy HTTP-oriented call sites onto the transport/business
// split. New code should use WriteBusinessError or WriteTransportError.
func WriteError(w http.ResponseWriter, status int, message string) {
	switch status {
	case http.StatusInternalServerError:
		WriteTransportError(w, status, InternalStatusTransportInternalError, "服务内部错误", "transport_internal_error")
	case http.StatusBadGateway:
		WriteTransportError(w, status, InternalStatusTransportBadGateway, "上游服务不可用", "transport_bad_gateway")
	case http.StatusGatewayTimeout:
		WriteTransportError(w, status, InternalStatusTransportGatewayTimeout, "上游服务超时", "transport_gateway_timeout")
	case http.StatusUnauthorized, http.StatusForbidden:
		WriteBusinessError(w, InternalStatusUserUnauthorized, message, "user_unauthorized")
	case http.StatusTooManyRequests:
		WriteBusinessError(w, InternalStatusAPIKeyRateLimited, message, "api_key_rate_limited")
	case http.StatusNotFound:
		WriteBusinessError(w, InternalStatusCommonResourceNotFound, message, "resource_not_found")
	case http.StatusConflict:
		WriteBusinessError(w, InternalStatusCommonStateConflict, message, "state_conflict")
	case http.StatusRequestEntityTooLarge:
		WriteBusinessError(w, InternalStatusUploadFileTooLarge, message, "upload_file_too_large")
	default:
		WriteBusinessError(w, InternalStatusCommonInvalidArgument, message, "invalid_argument")
	}
}

func writeEnvelope(w http.ResponseWriter, status int, payload ApiEnvelope[any]) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set(InternalCodeHeader, strconv.Itoa(int(payload.InternalCode)))
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}

func requestIDFromWriter(w http.ResponseWriter) string {
	return w.Header().Get(sharedheaders.HeaderXRequestID)
}

func reasonPointer(reason string) *string {
	if reason == "" {
		return nil
	}
	return &reason
}

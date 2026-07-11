package api

import (
	"encoding/json"
	"errors"
	"strings"
	"time"
)

// ParseEnvelope validates and decodes the shared wire contract. It deliberately
// rejects the legacy "code" field even when internal_code is also present.
func ParseEnvelope(body []byte) (ApiEnvelope[json.RawMessage], error) {
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(body, &fields); err != nil {
		return ApiEnvelope[json.RawMessage]{}, err
	}
	if _, exists := fields["code"]; exists {
		return ApiEnvelope[json.RawMessage]{}, errors.New("legacy code field is forbidden")
	}
	for _, field := range []string{"internal_code", "message", "data", "timestamp", "request_id", "error_reason"} {
		if _, exists := fields[field]; !exists {
			return ApiEnvelope[json.RawMessage]{}, errors.New("missing envelope field " + field)
		}
	}
	var envelope ApiEnvelope[json.RawMessage]
	if err := json.Unmarshal(body, &envelope); err != nil {
		return ApiEnvelope[json.RawMessage]{}, err
	}
	if strings.TrimSpace(envelope.Message) == "" || strings.TrimSpace(envelope.RequestID) == "" {
		return ApiEnvelope[json.RawMessage]{}, errors.New("message and request_id are required")
	}
	if _, err := time.Parse(time.RFC3339Nano, envelope.Timestamp); err != nil {
		return ApiEnvelope[json.RawMessage]{}, errors.New("invalid envelope timestamp")
	}
	if envelope.InternalCode == InternalStatusSuccess && envelope.ErrorReason != nil {
		return ApiEnvelope[json.RawMessage]{}, errors.New("success error_reason must be null")
	}
	if envelope.InternalCode != InternalStatusSuccess && (envelope.ErrorReason == nil || strings.TrimSpace(*envelope.ErrorReason) == "") {
		return ApiEnvelope[json.RawMessage]{}, errors.New("failure error_reason is required")
	}
	return envelope, nil
}

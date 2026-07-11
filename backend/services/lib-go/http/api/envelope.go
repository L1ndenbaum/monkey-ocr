package api

// ApiEnvelope is the shared JSON response contract for all service APIs.
// InternalCode must never be renamed to the ambiguous field name "code".
type ApiEnvelope[T any] struct {
	InternalCode InternalStatusCode `json:"internal_code"`
	Message      string             `json:"message"`
	Data         T                  `json:"data"`
	Timestamp    string             `json:"timestamp"`
	RequestID    string             `json:"request_id"`
	ErrorReason  *string            `json:"error_reason"`
}

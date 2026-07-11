package api

import (
	"encoding/json"
	"errors"
	"net/http"
)

// DefaultJSONBodyLimit is the shared default max JSON body size for service APIs.
const DefaultJSONBodyLimit int64 = 1 << 20

// DecodeJSONOptions configures bounded JSON request decoding.
type DecodeJSONOptions struct {
	MaxBytes              int64
	DisallowUnknownFields bool
}

// DecodeJSON reads a bounded JSON request body into target.
func DecodeJSON(w http.ResponseWriter, r *http.Request, target any, maxBytes int64) bool {
	if err := DecodeJSONWithOptions(w, r, target, DecodeJSONOptions{MaxBytes: maxBytes}); err != nil {
		var maxBytesError *http.MaxBytesError
		if errors.As(err, &maxBytesError) {
			WriteBusinessError(w, InternalStatusUploadFileTooLarge, "请求体过大", "request_body_too_large")
			return false
		}
		WriteBusinessError(w, InternalStatusCommonInvalidArgument, "请求 JSON 无效", "invalid_json")
		return false
	}
	return true
}

// DecodeJSONWithOptions reads a bounded JSON request body and returns decode errors to the caller.
func DecodeJSONWithOptions(w http.ResponseWriter, r *http.Request, target any, options DecodeJSONOptions) error {
	maxBytes := options.MaxBytes
	if maxBytes <= 0 {
		maxBytes = DefaultJSONBodyLimit
	}

	body := http.MaxBytesReader(w, r.Body, maxBytes)
	defer body.Close()

	decoder := json.NewDecoder(body)
	if options.DisallowUnknownFields {
		decoder.DisallowUnknownFields()
	}
	return decoder.Decode(target)
}

// DecodeJSONStrict reads a bounded JSON request body and rejects unknown JSON object fields.
func DecodeJSONStrict(w http.ResponseWriter, r *http.Request, target any, maxBytes int64) error {
	return DecodeJSONWithOptions(w, r, target, DecodeJSONOptions{
		MaxBytes:              maxBytes,
		DisallowUnknownFields: true,
	})
}

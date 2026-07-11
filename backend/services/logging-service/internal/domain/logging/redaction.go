package logging

import "strings"

const redactedValue = "[REDACTED]"

// RedactEvent removes secrets and OCR document content before an event enters
// any console, file, Kafka, or ClickHouse sink.
func RedactEvent(event LogEvent) LogEvent {
	event.Metadata = redactMap(event.Metadata)
	return event
}

func redactMap(input map[string]any) map[string]any {
	if input == nil {
		return nil
	}
	output := make(map[string]any, len(input))
	for key, value := range input {
		if isSensitiveMetadataKey(key) {
			output[key] = redactedValue
			continue
		}
		output[key] = redactValue(value)
	}
	return output
}

func redactValue(value any) any {
	switch typed := value.(type) {
	case map[string]any:
		return redactMap(typed)
	case []any:
		output := make([]any, len(typed))
		for index, item := range typed {
			output[index] = redactValue(item)
		}
		return output
	default:
		return value
	}
}

func isSensitiveMetadataKey(key string) bool {
	normalized := strings.ToLower(strings.NewReplacer("-", "_", " ", "_").Replace(strings.TrimSpace(key)))
	if normalized == "api_key_id" || normalized == "api_key_fingerprint" || normalized == "content_type" {
		return false
	}
	if normalized == "authorization" || normalized == "api_key" || normalized == "presigned_url" ||
		normalized == "ocr_text" || normalized == "markdown" || normalized == "document_content" || normalized == "content" {
		return true
	}
	return strings.Contains(normalized, "password") || strings.Contains(normalized, "secret") ||
		strings.Contains(normalized, "token")
}

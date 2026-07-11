package logging

import "testing"

func TestRedactEventRemovesSecretsAndOCRContentRecursively(t *testing.T) {
	event := RedactEvent(LogEvent{Metadata: map[string]any{
		"authorization":       "Bearer secret",
		"api_key_fingerprint": "safe-fingerprint",
		"nested": map[string]any{
			"presigned_url": "https://storage.example/signed",
			"ocr_text":      "private document",
			"content_type":  "application/pdf",
		},
	}})
	if event.Metadata["authorization"] != redactedValue {
		t.Fatalf("authorization = %#v", event.Metadata["authorization"])
	}
	if event.Metadata["api_key_fingerprint"] != "safe-fingerprint" {
		t.Fatalf("fingerprint = %#v", event.Metadata["api_key_fingerprint"])
	}
	nested := event.Metadata["nested"].(map[string]any)
	if nested["presigned_url"] != redactedValue || nested["ocr_text"] != redactedValue {
		t.Fatalf("nested metadata = %#v", nested)
	}
	if nested["content_type"] != "application/pdf" {
		t.Fatalf("content_type = %#v", nested["content_type"])
	}
}

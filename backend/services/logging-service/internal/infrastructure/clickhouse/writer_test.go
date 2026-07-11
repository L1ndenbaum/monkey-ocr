package clickhouse

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/url"
	"testing"
	"time"

	domain "monkeyocr-logging-service/internal/domain/logging"
)

type capturedInsert struct {
	body        []byte
	contentType string
	query       url.Values
	username    string
	password    string
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (roundTrip roundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) {
	return roundTrip(request)
}

func TestHTTPWriterPromotesOperationalMetadataIntoClickHouseColumns(t *testing.T) {
	var captured capturedInsert
	client := &http.Client{Transport: roundTripFunc(func(request *http.Request) (*http.Response, error) {
		body, _ := io.ReadAll(request.Body)
		username, password, _ := request.BasicAuth()
		captured = capturedInsert{
			body:        body,
			contentType: request.Header.Get("Content-Type"),
			query:       request.URL.Query(),
			username:    username,
			password:    password,
		}
		return &http.Response{
			StatusCode: http.StatusOK,
			Header:     make(http.Header),
			Body:       http.NoBody,
		}, nil
	})}

	now := time.Date(2026, 7, 11, 9, 30, 45, 123_000_000, time.UTC)
	writer := NewHTTPWriter(HTTPWriterConfig{
		BaseURL:  "http://clickhouse:8123",
		Database: "monkeyocr_logging_db",
		Table:    "monkeyocr_logs",
		Username: "monkeyocr_logging",
		Password: "secret",
		Client:   client,
		Now:      func() time.Time { return now },
	})
	event := domain.LogEvent{
		EventID:   "019-event",
		Timestamp: time.Date(2026, 7, 11, 9, 30, 0, 0, time.UTC),
		Level:     domain.LogLevelWarning,
		Service:   "monkeyocr-gateway",
		Message:   "gateway request",
		TraceID:   "trace-1",
		Metadata: map[string]any{
			"request_id":           " request-1 ",
			"http_status_code":     float64(200),
			"internal_code":        float64(40003),
			"internal_status_name": "API_KEY_RATE_LIMITED",
			"path":                 "/v1/jobs",
		},
	}

	if err := writer.InsertEvents(context.Background(), []domain.LogEvent{event}); err != nil {
		t.Fatalf("InsertEvents returned error: %v", err)
	}

	request := captured
	if request.contentType != "application/json" {
		t.Fatalf("content type = %q, want application/json", request.contentType)
	}
	if request.query.Get("database") != "monkeyocr_logging_db" {
		t.Fatalf("database query = %q", request.query.Get("database"))
	}
	if request.query.Get("query") != "INSERT INTO monkeyocr_logs FORMAT JSONEachRow" {
		t.Fatalf("insert query = %q", request.query.Get("query"))
	}
	if request.username != "monkeyocr_logging" || request.password != "secret" {
		t.Fatalf("basic auth = %q/%q", request.username, request.password)
	}

	var row clickHouseLogRow
	if err := json.Unmarshal(request.body, &row); err != nil {
		t.Fatalf("decode JSONEachRow body: %v", err)
	}
	if row.RequestID != "request-1" {
		t.Fatalf("request_id = %q, want request-1", row.RequestID)
	}
	if row.HTTPStatusCode == nil || *row.HTTPStatusCode != 200 {
		t.Fatalf("http_status_code = %v, want 200", row.HTTPStatusCode)
	}
	if row.InternalCode == nil || *row.InternalCode != 40003 {
		t.Fatalf("internal_code = %v, want 40003", row.InternalCode)
	}
	if row.InternalStatusName != "API_KEY_RATE_LIMITED" {
		t.Fatalf("internal_status_name = %q", row.InternalStatusName)
	}
	if row.TraceID != "trace-1" {
		t.Fatalf("trace_id = %q, want trace-1", row.TraceID)
	}

	var metadata map[string]any
	if err := json.Unmarshal([]byte(row.MetadataJSON), &metadata); err != nil {
		t.Fatalf("decode metadata_json: %v", err)
	}
	if metadata["path"] != "/v1/jobs" || metadata["internal_code"] != float64(40003) {
		t.Fatalf("metadata_json lost source metadata: %#v", metadata)
	}
}

func TestMetadataPromotionLeavesInvalidOrMissingNumericValuesNull(t *testing.T) {
	metadata := map[string]any{
		"http_status_code": 70000,
		"internal_code":    -1,
	}

	if value := metadataUint16(metadata, "http_status_code"); value != nil {
		t.Fatalf("out-of-range HTTP status promoted as %d", *value)
	}
	if value := metadataUint32(metadata, "internal_code"); value != nil {
		t.Fatalf("negative internal code promoted as %d", *value)
	}
	if value := metadataUint16(metadata, "missing"); value != nil {
		t.Fatalf("missing metadata promoted as %d", *value)
	}
}

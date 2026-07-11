package clickhouse

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"math"
	"net/http"
	"net/url"
	"strings"
	"time"

	domain "monkeyocr-logging-service/internal/domain/logging"
)

// HTTPWriter inserts log batches into ClickHouse over the HTTP JSONEachRow API.
type HTTPWriter struct {
	baseURL  string
	database string
	table    string
	username string
	password string
	client   *http.Client
	now      func() time.Time
}

// HTTPWriterConfig configures the ClickHouse HTTP insert path.
type HTTPWriterConfig struct {
	BaseURL  string
	Database string
	Table    string
	Username string
	Password string
	Timeout  time.Duration
	Client   *http.Client
	Now      func() time.Time
}

// NewHTTPWriter creates a ClickHouse JSONEachRow batch writer.
func NewHTTPWriter(config HTTPWriterConfig) *HTTPWriter {
	timeout := config.Timeout
	if timeout <= 0 {
		timeout = 5 * time.Second
	}
	client := config.Client
	if client == nil {
		client = &http.Client{Timeout: timeout}
	}
	now := config.Now
	if now == nil {
		now = func() time.Time { return time.Now().UTC() }
	}
	return &HTTPWriter{
		baseURL:  strings.TrimRight(config.BaseURL, "/"),
		database: config.Database,
		table:    config.Table,
		username: config.Username,
		password: config.Password,
		client:   client,
		now:      now,
	}
}

// InsertEvents writes a decoded event batch and returns only after ClickHouse accepts it.
func (writer *HTTPWriter) InsertEvents(ctx context.Context, events []domain.LogEvent) error {
	if len(events) == 0 {
		return nil
	}

	var body bytes.Buffer
	buffered := bufio.NewWriter(&body)
	encoder := json.NewEncoder(buffered)
	for _, event := range events {
		metadata, err := json.Marshal(event.Metadata)
		if err != nil {
			return err
		}
		if err := encoder.Encode(clickHouseLogRow{
			EventID:            event.EventID,
			Timestamp:          formatClickHouseTime(event.Timestamp),
			Level:              string(event.Level),
			Service:            event.Service,
			Message:            event.Message,
			RequestID:          metadataString(event.Metadata, "request_id"),
			TraceID:            event.TraceID,
			HTTPStatusCode:     metadataUint16(event.Metadata, "http_status_code"),
			InternalCode:       metadataUint32(event.Metadata, "internal_code"),
			InternalStatusName: metadataString(event.Metadata, "internal_status_name"),
			MetadataJSON:       string(metadata),
			IngestedAt:         formatClickHouseTime(writer.now()),
		}); err != nil {
			return err
		}
	}
	if err := buffered.Flush(); err != nil {
		return err
	}

	requestURL, err := writer.insertURL()
	if err != nil {
		return err
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, requestURL, &body)
	if err != nil {
		return err
	}
	request.Header.Set("Content-Type", "application/json")
	if writer.username != "" {
		request.SetBasicAuth(writer.username, writer.password)
	}

	response, err := writer.client.Do(request)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode >= http.StatusBadRequest {
		return fmt.Errorf("clickhouse insert returned %d", response.StatusCode)
	}
	return nil
}

func (writer *HTTPWriter) insertURL() (string, error) {
	parsed, err := url.Parse(writer.baseURL)
	if err != nil {
		return "", err
	}
	query := parsed.Query()
	if writer.database != "" {
		query.Set("database", writer.database)
	}
	query.Set("query", fmt.Sprintf("INSERT INTO %s FORMAT JSONEachRow", writer.table))
	parsed.RawQuery = query.Encode()
	return parsed.String(), nil
}

func formatClickHouseTime(value time.Time) string {
	return value.UTC().Format("2006-01-02 15:04:05.000")
}

type clickHouseLogRow struct {
	EventID            string  `json:"event_id"`
	Timestamp          string  `json:"timestamp"`
	Level              string  `json:"level"`
	Service            string  `json:"service"`
	Message            string  `json:"message"`
	RequestID          string  `json:"request_id"`
	TraceID            string  `json:"trace_id"`
	HTTPStatusCode     *uint16 `json:"http_status_code"`
	InternalCode       *uint32 `json:"internal_code"`
	InternalStatusName string  `json:"internal_status_name"`
	MetadataJSON       string  `json:"metadata_json"`
	IngestedAt         string  `json:"ingested_at"`
}

func metadataString(metadata map[string]any, key string) string {
	value, ok := metadata[key].(string)
	if !ok {
		return ""
	}
	return strings.TrimSpace(value)
}

func metadataUint16(metadata map[string]any, key string) *uint16 {
	value, ok := metadataUnsigned(metadata, key, math.MaxUint16)
	if !ok {
		return nil
	}
	converted := uint16(value)
	return &converted
}

func metadataUint32(metadata map[string]any, key string) *uint32 {
	value, ok := metadataUnsigned(metadata, key, math.MaxUint32)
	if !ok {
		return nil
	}
	converted := uint32(value)
	return &converted
}

func metadataUnsigned(metadata map[string]any, key string, maximum uint64) (uint64, bool) {
	value, exists := metadata[key]
	if !exists {
		return 0, false
	}

	var converted uint64
	switch typed := value.(type) {
	case float64:
		if typed < 0 || math.Trunc(typed) != typed || typed > float64(maximum) {
			return 0, false
		}
		converted = uint64(typed)
	case float32:
		if typed < 0 || float32(math.Trunc(float64(typed))) != typed || float64(typed) > float64(maximum) {
			return 0, false
		}
		converted = uint64(typed)
	case int:
		if typed < 0 {
			return 0, false
		}
		converted = uint64(typed)
	case int32:
		if typed < 0 {
			return 0, false
		}
		converted = uint64(typed)
	case int64:
		if typed < 0 {
			return 0, false
		}
		converted = uint64(typed)
	case uint:
		converted = uint64(typed)
	case uint32:
		converted = uint64(typed)
	case uint64:
		converted = typed
	case json.Number:
		parsed, err := typed.Int64()
		if err != nil || parsed < 0 {
			return 0, false
		}
		converted = uint64(parsed)
	default:
		return 0, false
	}
	return converted, converted <= maximum
}

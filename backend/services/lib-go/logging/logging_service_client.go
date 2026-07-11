package logging

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"strings"
	"sync"
	"time"

	sharedapi "monkeyocr-services-lib-go/http/api"
	sharedheaders "monkeyocr-services-lib-go/http/headers"
)

// Emitter sends one LogEvent to a logging sink.
type Emitter interface {
	Emit(context.Context, LogEvent) error
}

// LoggingServiceClientConfig configures the logging-service HTTP client.
type LoggingServiceClientConfig struct {
	BaseURL   string
	Token     string
	Timeout   time.Duration
	QueueSize int
	Client    *http.Client
}

// LoggingServiceClient delivers LogEvent objects to logging-service.
type LoggingServiceClient struct {
	baseURL string
	token   string
	client  *http.Client
	timeout time.Duration
	queue   chan LogEvent
	done    chan struct{}

	mu        sync.RWMutex
	closed    bool
	closeOnce sync.Once
}

// NewLoggingServiceClient creates a reusable HTTP client for logging-service.
func NewLoggingServiceClient(config LoggingServiceClientConfig) *LoggingServiceClient {
	timeout := config.Timeout
	if timeout <= 0 {
		timeout = 2 * time.Second
	}
	queueSize := config.QueueSize
	if queueSize <= 0 {
		queueSize = 4096
	}
	client := config.Client
	if client == nil {
		client = &http.Client{Timeout: timeout}
	}
	loggingClient := &LoggingServiceClient{
		baseURL: strings.TrimRight(config.BaseURL, "/"),
		token:   config.Token,
		client:  client,
		timeout: timeout,
		queue:   make(chan LogEvent, queueSize),
		done:    make(chan struct{}),
	}
	go loggingClient.run()
	return loggingClient
}

// Emit enqueues one event for asynchronous logging-service delivery.
func (client *LoggingServiceClient) Emit(_ context.Context, event LogEvent) error {
	if event.EventID == "" {
		event.EventID = newEventID()
	}
	client.mu.RLock()
	defer client.mu.RUnlock()
	if client.closed {
		log.Printf("logging-service client is closed; dropping trace_id=%s", event.TraceID)
		return nil
	}
	select {
	case client.queue <- event:
	default:
		log.Printf("logging-service client queue is full; dropping trace_id=%s", event.TraceID)
	}
	return nil
}

func newEventID() string {
	var bytes [16]byte
	if _, err := rand.Read(bytes[:]); err != nil {
		return fmt.Sprintf("event-%d", time.Now().UnixNano())
	}
	bytes[6] = (bytes[6] & 0x0f) | 0x40
	bytes[8] = (bytes[8] & 0x3f) | 0x80
	return fmt.Sprintf(
		"%08x-%04x-%04x-%04x-%012x",
		bytes[0:4],
		bytes[4:6],
		bytes[6:8],
		bytes[8:10],
		bytes[10:16],
	)
}

// Close stops accepting events and waits for queued events to drain.
func (client *LoggingServiceClient) Close(ctx context.Context) error {
	client.closeOnce.Do(func() {
		client.mu.Lock()
		client.closed = true
		close(client.queue)
		client.mu.Unlock()
	})

	select {
	case <-client.done:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

func (client *LoggingServiceClient) run() {
	defer close(client.done)
	for event := range client.queue {
		ctx, cancel := context.WithTimeout(context.Background(), client.timeout)
		err := client.post(ctx, event)
		cancel()
		if err != nil && !errors.Is(err, context.Canceled) {
			log.Printf("logging-service emit failed for trace_id=%s: %v", event.TraceID, err)
		}
	}
}

func (client *LoggingServiceClient) post(ctx context.Context, event LogEvent) error {
	payload, err := json.Marshal(logEventIngestRequest{Event: event})
	if err != nil {
		return err
	}

	request, err := http.NewRequestWithContext(
		ctx,
		http.MethodPost,
		client.baseURL+"/v1/log-events",
		bytes.NewReader(payload),
	)
	if err != nil {
		return err
	}
	request.Header.Set("Content-Type", "application/json")
	if client.token != "" {
		request.Header.Set("X-Logging-Service-Token", client.token)
	}
	if event.TraceID != "" {
		request.Header.Set(sharedheaders.HeaderXRequestID, event.TraceID)
	}

	response, err := client.client.Do(request)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK && response.StatusCode != http.StatusInternalServerError &&
		response.StatusCode != http.StatusBadGateway && response.StatusCode != http.StatusGatewayTimeout {
		return fmt.Errorf("logging-service returned unsupported HTTP status %d", response.StatusCode)
	}
	body, err := io.ReadAll(io.LimitReader(response.Body, (1<<20)+1))
	if err != nil || len(body) > 1<<20 {
		return fmt.Errorf("logging-service returned unreadable ApiEnvelope")
	}
	envelope, err := sharedapi.ParseEnvelope(body)
	if err != nil {
		return fmt.Errorf("logging-service returned invalid ApiEnvelope: %w", err)
	}
	if response.StatusCode != http.StatusOK || envelope.InternalCode != sharedapi.InternalStatusSuccess {
		return fmt.Errorf("logging-service failed: http_status=%d internal_code=%d", response.StatusCode, envelope.InternalCode)
	}
	return nil
}

package proxy

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strconv"
	"strings"
	"time"

	sharedhttp "monkeyocr-services-lib-go/http/api"
)

const maxEnvelopeValidationBytes int64 = 16 << 20

var errInvalidUpstreamResponse = errors.New("invalid upstream response")

// ReverseProxy forwards gateway traffic to one configured upstream service.
type ReverseProxy struct {
	defaultBackendURL string
	transport         http.RoundTripper
}

// NewReverseProxy creates a reverse proxy for the configured backend URL.
func NewReverseProxy(backendURL string, transport http.RoundTripper) *ReverseProxy {
	return &ReverseProxy{defaultBackendURL: backendURL, transport: transport}
}

func (proxy *ReverseProxy) newUpstreamProxy(upstreamURL string) (*httputil.ReverseProxy, error) {
	backend, err := url.Parse(upstreamURL)
	if err != nil || (backend.Scheme != "http" && backend.Scheme != "https") || backend.Host == "" {
		return nil, fmt.Errorf("invalid upstream URL")
	}
	upstreamProxy := httputil.NewSingleHostReverseProxy(backend)
	upstreamProxy.FlushInterval = -1
	if proxy.transport != nil {
		upstreamProxy.Transport = proxy.transport
	}
	originalDirector := upstreamProxy.Director
	upstreamProxy.Director = func(req *http.Request) {
		originalDirector(req)
		req.Host = backend.Host
	}
	upstreamProxy.ModifyResponse = validateUpstreamResponse
	upstreamProxy.ErrorHandler = func(w http.ResponseWriter, _ *http.Request, err error) {
		if isTimeout(err) {
			sharedhttp.WriteTransportError(
				w,
				http.StatusGatewayTimeout,
				sharedhttp.InternalStatusTransportGatewayTimeout,
				"上游服务超时",
				"transport_gateway_timeout",
			)
			return
		}
		sharedhttp.WriteTransportError(
			w,
			http.StatusBadGateway,
			sharedhttp.InternalStatusTransportBadGateway,
			"上游服务不可用",
			"transport_bad_gateway",
		)
	}
	return upstreamProxy, nil
}

func validateUpstreamResponse(response *http.Response) error {
	if !isAllowedHTTPStatus(response.StatusCode) {
		return fmt.Errorf("%w: unsupported HTTP status %d", errInvalidUpstreamResponse, response.StatusCode)
	}
	mediaType, _, err := mime.ParseMediaType(response.Header.Get("Content-Type"))
	if err != nil {
		return fmt.Errorf("%w: invalid content type", errInvalidUpstreamResponse)
	}
	if mediaType == "text/event-stream" {
		if response.StatusCode != http.StatusOK {
			return fmt.Errorf("%w: SSE status must be 200", errInvalidUpstreamResponse)
		}
		response.Header.Set("Cache-Control", "no-cache")
		response.Header.Set("X-Accel-Buffering", "no")
		return nil
	}
	if mediaType != "application/json" {
		return fmt.Errorf("%w: upstream must return ApiEnvelope JSON or SSE", errInvalidUpstreamResponse)
	}

	body, err := io.ReadAll(io.LimitReader(response.Body, maxEnvelopeValidationBytes+1))
	if err != nil {
		return fmt.Errorf("%w: read body: %v", errInvalidUpstreamResponse, err)
	}
	_ = response.Body.Close()
	if int64(len(body)) > maxEnvelopeValidationBytes {
		return fmt.Errorf("%w: envelope too large", errInvalidUpstreamResponse)
	}
	internalCode, requestID, err := validateEnvelope(body)
	if err != nil {
		return err
	}
	if response.Request != nil {
		expectedRequestID := strings.TrimSpace(response.Request.Header.Get("X-Request-ID"))
		if expectedRequestID != "" && requestID != expectedRequestID {
			return fmt.Errorf("%w: request_id does not match request", errInvalidUpstreamResponse)
		}
	}
	if !statusMatchesInternalCode(response.StatusCode, internalCode) {
		return fmt.Errorf("%w: HTTP status and internal_code disagree", errInvalidUpstreamResponse)
	}
	response.Body = io.NopCloser(bytes.NewReader(body))
	response.ContentLength = int64(len(body))
	response.Header.Set("Content-Length", strconv.Itoa(len(body)))
	response.Header.Set(sharedhttp.InternalCodeHeader, strconv.Itoa(int(internalCode)))
	return nil
}

func validateEnvelope(body []byte) (sharedhttp.InternalStatusCode, string, error) {
	var envelope map[string]json.RawMessage
	if err := json.Unmarshal(body, &envelope); err != nil {
		return 0, "", fmt.Errorf("%w: invalid JSON", errInvalidUpstreamResponse)
	}
	if _, exists := envelope["code"]; exists {
		return 0, "", fmt.Errorf("%w: legacy code field is forbidden", errInvalidUpstreamResponse)
	}
	required := []string{"internal_code", "message", "data", "timestamp", "request_id", "error_reason"}
	for _, field := range required {
		if _, exists := envelope[field]; !exists {
			return 0, "", fmt.Errorf("%w: missing %s", errInvalidUpstreamResponse, field)
		}
	}
	var internalCode sharedhttp.InternalStatusCode
	if err := json.Unmarshal(envelope["internal_code"], &internalCode); err != nil {
		return 0, "", fmt.Errorf("%w: internal_code is not an integer", errInvalidUpstreamResponse)
	}
	var message, timestamp, requestID string
	if json.Unmarshal(envelope["message"], &message) != nil || strings.TrimSpace(message) == "" {
		return 0, "", fmt.Errorf("%w: invalid message", errInvalidUpstreamResponse)
	}
	if json.Unmarshal(envelope["timestamp"], &timestamp) != nil {
		return 0, "", fmt.Errorf("%w: invalid timestamp", errInvalidUpstreamResponse)
	}
	if _, err := time.Parse(time.RFC3339Nano, timestamp); err != nil {
		return 0, "", fmt.Errorf("%w: invalid timestamp", errInvalidUpstreamResponse)
	}
	if json.Unmarshal(envelope["request_id"], &requestID) != nil || strings.TrimSpace(requestID) == "" {
		return 0, "", fmt.Errorf("%w: invalid request_id", errInvalidUpstreamResponse)
	}
	if internalCode == sharedhttp.InternalStatusSuccess && string(envelope["error_reason"]) != "null" {
		return 0, "", fmt.Errorf("%w: success error_reason must be null", errInvalidUpstreamResponse)
	}
	if internalCode != sharedhttp.InternalStatusSuccess {
		var reason string
		if json.Unmarshal(envelope["error_reason"], &reason) != nil || strings.TrimSpace(reason) == "" {
			return 0, "", fmt.Errorf("%w: failure error_reason must be a non-empty string", errInvalidUpstreamResponse)
		}
	}
	return internalCode, requestID, nil
}

func isAllowedHTTPStatus(status int) bool {
	return status == http.StatusOK || status == http.StatusInternalServerError ||
		status == http.StatusBadGateway || status == http.StatusGatewayTimeout
}

func statusMatchesInternalCode(status int, internalCode sharedhttp.InternalStatusCode) bool {
	switch status {
	case http.StatusOK:
		return internalCode != sharedhttp.InternalStatusTransportInternalError &&
			internalCode != sharedhttp.InternalStatusTransportBadGateway &&
			internalCode != sharedhttp.InternalStatusTransportGatewayTimeout
	case http.StatusInternalServerError:
		return internalCode == sharedhttp.InternalStatusTransportInternalError
	case http.StatusBadGateway:
		return internalCode == sharedhttp.InternalStatusTransportBadGateway
	case http.StatusGatewayTimeout:
		return internalCode == sharedhttp.InternalStatusTransportGatewayTimeout
	default:
		return false
	}
}

func isTimeout(err error) bool {
	if errors.Is(err, context.DeadlineExceeded) {
		return true
	}
	var networkError net.Error
	return errors.As(err, &networkError) && networkError.Timeout()
}

// ServeHTTP forwards the request to the configured upstream.
func (proxy *ReverseProxy) ServeHTTP(w http.ResponseWriter, r *http.Request, upstreamURL string) {
	if upstreamURL == "" {
		upstreamURL = proxy.defaultBackendURL
	}
	upstreamProxy, err := proxy.newUpstreamProxy(upstreamURL)
	if err != nil {
		sharedhttp.WriteTransportError(w, http.StatusInternalServerError, sharedhttp.InternalStatusTransportInternalError, "网关配置无效", "invalid_upstream_configuration")
		return
	}
	upstreamProxy.ServeHTTP(w, r)
}

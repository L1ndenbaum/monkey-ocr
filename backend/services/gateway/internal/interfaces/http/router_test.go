package httpapi

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"monkeyocr-gateway/internal/application/identity_policy"
	appgateway "monkeyocr-gateway/internal/application/pipeline"
	pipeline_deps "monkeyocr-gateway/internal/application/pipeline/deps"
	"monkeyocr-gateway/internal/application/route_policy"
	"monkeyocr-gateway/internal/domain/auth"
	"monkeyocr-gateway/internal/domain/logging"
	"monkeyocr-gateway/internal/domain/rate_limit"
	domainrequestid "monkeyocr-gateway/internal/domain/request_id"
	apikeyinfra "monkeyocr-gateway/internal/infrastructure/apikey"
	proxyinfra "monkeyocr-gateway/internal/infrastructure/proxy"
	sharedapi "monkeyocr-services-lib-go/http/api"
)

type captureAccessLogger struct{ events []logging.AccessLogEvent }

func (logger *captureAccessLogger) Emit(event logging.AccessLogEvent) {
	logger.events = append(logger.events, event)
}

type staticLimiter struct{ decision rate_limit.RateLimitDecision }

func (limiter staticLimiter) GetRateLimitDecision(_ context.Context, _ rate_limit.RateLimitTarget) (rate_limit.RateLimitDecision, error) {
	return limiter.decision, nil
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (fn roundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) { return fn(request) }

type routerTestConfig struct {
	transport           http.RoundTripper
	logger              *captureAccessLogger
	clientIPLimiter     pipeline_deps.ClientIPLimiter
	apiKeyLimiter       pipeline_deps.APIKeyLimiter
	serviceLimiter      pipeline_deps.ServiceLimiter
	corsAllowedOrigins  []string
	maxRequestBodyBytes int64
}

func TestGatewayAuthenticatesAPIKeyAndLogsEnvelopeStatus(t *testing.T) {
	var upstreamRequestID, upstreamAPIKeyFingerprint string
	logger := &captureAccessLogger{}
	router := newTestRouter(t, routerTestConfig{
		logger: logger,
		transport: roundTripFunc(func(request *http.Request) (*http.Response, error) {
			upstreamRequestID = request.Header.Get("X-Request-ID")
			upstreamAPIKeyFingerprint = request.Header.Get("X-API-Key-Fingerprint")
			return jsonResponse(http.StatusOK, successEnvelope(upstreamRequestID)), nil
		}),
		clientIPLimiter: allowedLimiter(),
		apiKeyLimiter:   allowedLimiter(),
		serviceLimiter:  allowedLimiter(),
	})

	request := httptest.NewRequest(http.MethodGet, "/v1/jobs/job-1", nil)
	request.Header.Set("Authorization", "Bearer test-api-key")
	request.Header.Set("X-API-Key-Fingerprint", "attacker")
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200: %s", response.Code, response.Body.String())
	}
	if upstreamRequestID == "" || response.Header().Get("X-Request-ID") != upstreamRequestID {
		t.Fatalf("request id was not propagated: upstream=%q response=%q", upstreamRequestID, response.Header().Get("X-Request-ID"))
	}
	wantFingerprint := fingerprint("test-api-key")
	if upstreamAPIKeyFingerprint != wantFingerprint {
		t.Fatalf("X-API-Key-Fingerprint = %q, want %q", upstreamAPIKeyFingerprint, wantFingerprint)
	}
	if response.Header().Get(sharedapi.InternalCodeHeader) != "" {
		t.Fatal("private internal-code header leaked to public response")
	}
	if len(logger.events) != 1 {
		t.Fatalf("access logs = %d, want 1", len(logger.events))
	}
	metadata := logger.events[0].Metadata
	if metadata.AuthResult != auth.AuthResultFingerprintReady || metadata.APIKeyFingerprint != wantFingerprint {
		t.Fatalf("unexpected auth metadata %#v", metadata)
	}
	if metadata.HTTPStatusCode != http.StatusOK || metadata.InternalCode != int(sharedapi.InternalStatusSuccess) {
		t.Fatalf("unexpected status metadata %#v", metadata)
	}
}

func TestGatewayReturnsBusinessEnvelopeForMissingAPIKey(t *testing.T) {
	upstreamHit := false
	logger := &captureAccessLogger{}
	router := newTestRouter(t, routerTestConfig{
		logger: logger,
		transport: roundTripFunc(func(request *http.Request) (*http.Response, error) {
			upstreamHit = true
			return jsonResponse(http.StatusOK, successEnvelope(request.Header.Get("X-Request-ID"))), nil
		}),
		clientIPLimiter: allowedLimiter(), serviceLimiter: allowedLimiter(),
	})

	response := httptest.NewRecorder()
	router.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/v1/jobs", nil))

	if response.Code != http.StatusOK || !strings.Contains(response.Body.String(), `"internal_code":40001`) {
		t.Fatalf("unexpected response %d %s", response.Code, response.Body.String())
	}
	if upstreamHit {
		t.Fatal("unauthorized request reached upstream")
	}
	if logger.events[0].Metadata.AuthResult != auth.AuthResultMissingAPIKey {
		t.Fatalf("auth result = %q", logger.events[0].Metadata.AuthResult)
	}
}

func TestGatewayRejectsInvalidUpstreamProtocolAs502(t *testing.T) {
	router := newTestRouter(t, routerTestConfig{
		transport: roundTripFunc(func(request *http.Request) (*http.Response, error) {
			return jsonResponse(http.StatusCreated, `{"ok":true}`), nil
		}),
		clientIPLimiter: allowedLimiter(), apiKeyLimiter: allowedLimiter(), serviceLimiter: allowedLimiter(),
	})
	request := httptest.NewRequest(http.MethodGet, "/v1/jobs", nil)
	request.Header.Set("Authorization", "Bearer test-api-key")
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)

	if response.Code != http.StatusBadGateway || !strings.Contains(response.Body.String(), `"internal_code":90002`) {
		t.Fatalf("unexpected response %d %s", response.Code, response.Body.String())
	}
}

func TestGatewayProxiesSSEWithoutBuffering(t *testing.T) {
	router := newTestRouter(t, routerTestConfig{
		transport: roundTripFunc(func(request *http.Request) (*http.Response, error) {
			return &http.Response{
				StatusCode: http.StatusOK,
				Header:     http.Header{"Content-Type": []string{"text/event-stream"}},
				Body:       io.NopCloser(strings.NewReader(": heartbeat\n\n")),
			}, nil
		}),
		clientIPLimiter: allowedLimiter(), apiKeyLimiter: allowedLimiter(), serviceLimiter: allowedLimiter(),
	})
	request := httptest.NewRequest(http.MethodGet, "/v1/jobs/job-1/events", nil)
	request.Header.Set("Authorization", "Bearer test-api-key")
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)

	if response.Code != http.StatusOK || response.Header().Get("X-Accel-Buffering") != "no" {
		t.Fatalf("unexpected SSE response %d headers=%v", response.Code, response.Header())
	}
	if response.Body.String() != ": heartbeat\n\n" {
		t.Fatalf("SSE body = %q", response.Body.String())
	}
}

func TestGatewayRateLimitUsesHTTP200BusinessError(t *testing.T) {
	router := newTestRouter(t, routerTestConfig{
		clientIPLimiter: allowedLimiter(),
		apiKeyLimiter: staticLimiter{decision: rate_limit.RateLimitDecision{
			Allowed: false, Result: "rejected",
		}},
		serviceLimiter: allowedLimiter(),
	})
	request := httptest.NewRequest(http.MethodGet, "/v1/jobs", nil)
	request.Header.Set("Authorization", "Bearer test-api-key")
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)

	if response.Code != http.StatusOK || !strings.Contains(response.Body.String(), `"internal_code":40003`) {
		t.Fatalf("unexpected response %d %s", response.Code, response.Body.String())
	}
}

func TestGatewayCORSPreflightUsesAllowedHTTPStatus(t *testing.T) {
	router := newTestRouter(t, routerTestConfig{corsAllowedOrigins: []string{"http://localhost:13002"}})
	request := httptest.NewRequest(http.MethodOptions, "/v1/jobs", nil)
	request.Header.Set("Origin", "http://localhost:13002")
	request.Header.Set("Access-Control-Request-Method", http.MethodGet)
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)
	if response.Code != http.StatusOK {
		t.Fatalf("preflight status = %d, want 200", response.Code)
	}
}

func TestGatewayRejectsOversizedBodyBeforeProxy(t *testing.T) {
	upstreamHit := false
	router := newTestRouter(t, routerTestConfig{
		maxRequestBodyBytes: 4,
		transport: roundTripFunc(func(request *http.Request) (*http.Response, error) {
			upstreamHit = true
			return jsonResponse(http.StatusOK, successEnvelope(request.Header.Get("X-Request-ID"))), nil
		}),
	})
	request := httptest.NewRequest(http.MethodPost, "/v1/jobs", strings.NewReader("too-large"))
	request.Header.Set("Authorization", "Bearer test-api-key")
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)
	if response.Code != http.StatusOK || !strings.Contains(response.Body.String(), `"internal_code":20005`) {
		t.Fatalf("unexpected response %d %s", response.Code, response.Body.String())
	}
	if upstreamHit {
		t.Fatal("oversized request reached upstream")
	}
}

func newTestRouter(t *testing.T, config routerTestConfig) http.Handler {
	t.Helper()
	digest := sha256.Sum256([]byte("test-api-key"))
	validator, err := apikeyinfra.NewStaticSHA256Validator([]string{"test-key-id=" + hex.EncodeToString(digest[:])})
	if err != nil {
		t.Fatalf("validator: %v", err)
	}
	logger := config.logger
	if logger == nil {
		logger = &captureAccessLogger{}
	}
	pipeline := appgateway.NewPipeline(appgateway.PipelineConfig{
		ServiceName:     "monkeyocr-gateway",
		RoutePolicy:     route_policy.NewDefaultRoutePolicy("http://backend.local"),
		RequestIDPolicy: domainrequestid.RequestIDPolicy{},
		IdentityPolicy:  identity_policy.IdentityPolicy{},
		Location:        time.UTC,
		Now:             time.Now,
	}, pipeline_deps.PipelineDependencies{
		Authenticator:   apikeyinfra.NewAuthenticator(validator),
		ClientIPLimiter: config.clientIPLimiter,
		APIKeyLimiter:   config.apiKeyLimiter,
		ServiceLimiter:  config.serviceLimiter,
		Proxy:           proxyinfra.NewReverseProxy("http://backend.local", config.transport),
		AccessLogger:    logger,
	})
	return NewRouter(NewHandler(pipeline), CORSConfig{
		AllowedOrigins:      config.corsAllowedOrigins,
		MaxRequestBodyBytes: config.maxRequestBodyBytes,
	})
}

func allowedLimiter() staticLimiter {
	return staticLimiter{decision: rate_limit.RateLimitDecision{Allowed: true, Result: "allowed"}}
}

func jsonResponse(status int, body string) *http.Response {
	return &http.Response{
		StatusCode: status,
		Header:     http.Header{"Content-Type": []string{"application/json"}},
		Body:       io.NopCloser(strings.NewReader(body)),
	}
}

func successEnvelope(requestID string) string {
	return fmt.Sprintf(`{"internal_code":0,"message":"操作成功","data":{},"timestamp":"2026-07-11T00:00:00Z","request_id":%q,"error_reason":null}`, requestID)
}

func fingerprint(token string) string {
	digest := sha256.Sum256([]byte(token))
	return hex.EncodeToString(digest[:])
}

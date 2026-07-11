package pipeline

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strconv"
	"testing"
	"time"

	"monkeyocr-gateway/internal/application/identity_policy"
	"monkeyocr-gateway/internal/application/pipeline/deps"
	"monkeyocr-gateway/internal/application/route_policy"
	"monkeyocr-gateway/internal/domain/auth"
	domainidentity "monkeyocr-gateway/internal/domain/identity"
	"monkeyocr-gateway/internal/domain/logging"
	"monkeyocr-gateway/internal/domain/rate_limit"
	"monkeyocr-gateway/internal/domain/request_id"
	sharedapi "monkeyocr-services-lib-go/http/api"
)

type fakeAuthenticator struct {
	identity domainidentity.Identity
	err      error
}

func (authenticator fakeAuthenticator) Authenticate(_ context.Context, _ string) (domainidentity.Identity, error) {
	return authenticator.identity, authenticator.err
}

type fakeLimiter struct{ decision rate_limit.RateLimitDecision }

func (limiter fakeLimiter) GetRateLimitDecision(_ context.Context, _ rate_limit.RateLimitTarget) (rate_limit.RateLimitDecision, error) {
	return limiter.decision, nil
}

type fakeProxy struct {
	hit               bool
	apiKeyFingerprint string
}

func (proxy *fakeProxy) ServeHTTP(w http.ResponseWriter, r *http.Request, _ string) {
	proxy.hit = true
	proxy.apiKeyFingerprint = r.Header.Get("X-API-Key-Fingerprint")
	sharedapi.WriteSuccess(w, map[string]bool{"ok": true})
}

type captureAccessLogger struct{ events []logging.AccessLogEvent }

func (logger *captureAccessLogger) Emit(event logging.AccessLogEvent) {
	logger.events = append(logger.events, event)
}

type testResponseRecorder struct{ *httptest.ResponseRecorder }

func newTestResponseRecorder() *testResponseRecorder {
	return &testResponseRecorder{ResponseRecorder: httptest.NewRecorder()}
}

func (recorder *testResponseRecorder) Status() int {
	if recorder.Code == 0 {
		return http.StatusOK
	}
	return recorder.Code
}

func (recorder *testResponseRecorder) InternalCode() (int, bool) {
	raw := recorder.Header().Get(sharedapi.InternalCodeHeader)
	if raw == "" {
		return 0, false
	}
	value, err := strconv.Atoi(raw)
	return value, err == nil
}

func TestPipelineSkipsSuccessfulHealthProbeAccessLog(t *testing.T) {
	logger := &captureAccessLogger{}
	pipeline := newTestPipeline(fakeAuthenticator{}, &fakeProxy{}, logger)
	response := newTestResponseRecorder()
	pipeline.HandleHealth(response, httptest.NewRequest(http.MethodGet, "/health", nil))
	if response.Code != http.StatusOK {
		t.Fatalf("status = %d", response.Code)
	}
	if len(logger.events) != 0 {
		t.Fatalf("health access logs = %d, want 0", len(logger.events))
	}
}

func TestPipelineRejectsMissingAPIKeyBeforeProxy(t *testing.T) {
	proxy := &fakeProxy{}
	logger := &captureAccessLogger{}
	pipeline := newTestPipeline(fakeAuthenticator{}, proxy, logger)
	response := newTestResponseRecorder()
	pipeline.HandleProxy(response, httptest.NewRequest(http.MethodGet, "/v1/jobs", nil))

	if response.Code != http.StatusOK || proxy.hit {
		t.Fatalf("status=%d proxy_hit=%v", response.Code, proxy.hit)
	}
	if internalCode, ok := response.InternalCode(); !ok || internalCode != int(sharedapi.InternalStatusUserUnauthorized) {
		t.Fatalf("internal_code=%d ok=%v", internalCode, ok)
	}
	if logger.events[0].Metadata.AuthResult != auth.AuthResultMissingAPIKey {
		t.Fatalf("auth result = %q", logger.events[0].Metadata.AuthResult)
	}
}

func TestPipelineForwardsOnlyVerifiedAPIKeyIdentity(t *testing.T) {
	proxy := &fakeProxy{}
	pipeline := newTestPipeline(fakeAuthenticator{identity: domainidentity.Identity{APIKeyFingerprint: "key-1"}}, proxy, &captureAccessLogger{})
	request := httptest.NewRequest(http.MethodGet, "/v1/jobs", nil)
	request.Header.Set("Authorization", "Bearer secret")
	request.Header.Set("X-API-Key-Fingerprint", "attacker")
	response := newTestResponseRecorder()
	pipeline.HandleProxy(response, request)

	if !proxy.hit || proxy.apiKeyFingerprint != "key-1" {
		t.Fatalf("proxy_hit=%v api_key_id=%q", proxy.hit, proxy.apiKeyFingerprint)
	}
}

func TestPipelineRejectsInvalidAPIKeyAsBusinessResult(t *testing.T) {
	proxy := &fakeProxy{}
	logger := &captureAccessLogger{}
	pipeline := newTestPipeline(fakeAuthenticator{err: errors.New("invalid")}, proxy, logger)
	request := httptest.NewRequest(http.MethodGet, "/v1/jobs", nil)
	request.Header.Set("Authorization", "Bearer invalid")
	response := newTestResponseRecorder()
	pipeline.HandleProxy(response, request)

	if response.Code != http.StatusOK || proxy.hit {
		t.Fatalf("status=%d proxy_hit=%v", response.Code, proxy.hit)
	}
	if logger.events[0].Metadata.AuthResult != auth.AuthResultInvalidAPIKey {
		t.Fatalf("auth result = %q", logger.events[0].Metadata.AuthResult)
	}
}

func newTestPipeline(authenticator deps.Authenticator, proxy deps.UpstreamProxy, logger deps.AccessLogger) *Pipeline {
	allowed := fakeLimiter{decision: rate_limit.RateLimitDecision{Allowed: true, Result: "allowed"}}
	return NewPipeline(PipelineConfig{
		ServiceName:     "monkeyocr-gateway",
		RoutePolicy:     route_policy.NewDefaultRoutePolicy("http://backend.local"),
		RequestIDPolicy: request_id.RequestIDPolicy{Generate: func() string { return "request-id" }},
		IdentityPolicy:  identity_policy.IdentityPolicy{},
		Location:        time.UTC,
		Now:             time.Now,
	}, deps.PipelineDependencies{
		Authenticator:   authenticator,
		ClientIPLimiter: allowed,
		APIKeyLimiter:   allowed,
		ServiceLimiter:  allowed,
		Proxy:           proxy,
		AccessLogger:    logger,
	})
}

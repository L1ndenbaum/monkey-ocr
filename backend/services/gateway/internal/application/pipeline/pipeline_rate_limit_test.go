package pipeline

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	"monkeyocr-gateway/internal/application/pipeline/deps"
	domainidentity "monkeyocr-gateway/internal/domain/identity"
	"monkeyocr-gateway/internal/domain/rate_limit"
	sharedapi "monkeyocr-services-lib-go/http/api"
)

type recordingLimiter struct {
	decision rate_limit.RateLimitDecision
	calls    *[]rate_limit.RateLimitTarget
}

func (limiter recordingLimiter) GetRateLimitDecision(_ context.Context, target rate_limit.RateLimitTarget) (rate_limit.RateLimitDecision, error) {
	*limiter.calls = append(*limiter.calls, target)
	return limiter.decision, nil
}

func TestPipelineRunsIPAPIKeyAndServiceLimiters(t *testing.T) {
	calls := []rate_limit.RateLimitTarget{}
	allowed := rate_limit.RateLimitDecision{Allowed: true, Result: "allowed"}
	proxy := &fakeProxy{}
	pipeline := newRateLimitPipeline(
		recordingLimiter{decision: allowed, calls: &calls},
		recordingLimiter{decision: allowed, calls: &calls},
		recordingLimiter{decision: allowed, calls: &calls},
		proxy,
	)
	request := httptest.NewRequest(http.MethodGet, "/v1/jobs", nil)
	request.RemoteAddr = "203.0.113.10:1234"
	request.Header.Set("Authorization", "Bearer secret")
	response := newTestResponseRecorder()
	pipeline.HandleProxy(response, request)

	if !proxy.hit || len(calls) != 3 {
		t.Fatalf("proxy_hit=%v calls=%#v", proxy.hit, calls)
	}
	want := []rate_limit.RateLimitTarget{
		{Scope: rate_limit.RateLimitScopeClientIP, Key: "203.0.113.10"},
		{Scope: rate_limit.RateLimitScopeAPIKey, Key: "key-1"},
		{Scope: rate_limit.RateLimitScopeService, Key: "monkeyocr-backend"},
	}
	for index := range want {
		if calls[index] != want[index] {
			t.Fatalf("call[%d]=%#v want %#v", index, calls[index], want[index])
		}
	}
}

func TestPipelineRateLimitRejectionUsesBusinessStatus(t *testing.T) {
	calls := []rate_limit.RateLimitTarget{}
	allowed := rate_limit.RateLimitDecision{Allowed: true, Result: "allowed"}
	rejected := rate_limit.RateLimitDecision{Allowed: false, Result: "rejected"}
	proxy := &fakeProxy{}
	pipeline := newRateLimitPipeline(
		recordingLimiter{decision: allowed, calls: &calls},
		recordingLimiter{decision: rejected, calls: &calls},
		recordingLimiter{decision: allowed, calls: &calls},
		proxy,
	)
	request := httptest.NewRequest(http.MethodGet, "/v1/jobs", nil)
	request.Header.Set("Authorization", "Bearer secret")
	response := newTestResponseRecorder()
	pipeline.HandleProxy(response, request)

	internalCode, _ := response.InternalCode()
	if response.Code != http.StatusOK || internalCode != int(sharedapi.InternalStatusAPIKeyRateLimited) || proxy.hit {
		t.Fatalf("status=%d internal_code=%d proxy_hit=%v", response.Code, internalCode, proxy.hit)
	}
}

func newRateLimitPipeline(client, apiKey, service deps.RateLimiter, proxy deps.UpstreamProxy) *Pipeline {
	pipeline := newTestPipeline(
		fakeAuthenticator{identity: domainidentity.Identity{APIKeyFingerprint: "key-1"}},
		proxy,
		&captureAccessLogger{},
	)
	pipeline.deps.ClientIPLimiter = client
	pipeline.deps.APIKeyLimiter = apiKey
	pipeline.deps.ServiceLimiter = service
	return pipeline
}

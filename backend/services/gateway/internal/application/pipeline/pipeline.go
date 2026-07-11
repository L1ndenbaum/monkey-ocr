package pipeline

import (
	"context"
	"monkeyocr-gateway/internal/application/identity_policy"
	pipeline_deps "monkeyocr-gateway/internal/application/pipeline/deps"
	"monkeyocr-gateway/internal/application/route_policy"
	"monkeyocr-gateway/internal/domain/auth"
	domain2 "monkeyocr-gateway/internal/domain/identity"
	"monkeyocr-gateway/internal/domain/logging"
	"monkeyocr-gateway/internal/domain/rate_limit"
	"monkeyocr-gateway/internal/domain/request_id"
	"net/http"
	"strings"
	"time"

	sharedapi "monkeyocr-services-lib-go/http/api"
	sharedheaders "monkeyocr-services-lib-go/http/headers"
	sharedlogging "monkeyocr-services-lib-go/logging"
)

// ResponseStatusRecorder is the HTTP response surface the pipeline needs to finalize logs.
type ResponseStatusRecorder interface {
	http.ResponseWriter
	Status() int
	InternalCode() (int, bool)
}

// PipelineConfig configures gateway request orchestration.
type PipelineConfig struct {
	ServiceName     string
	RoutePolicy     route_policy.RoutePolicy
	RequestIDPolicy request_id.RequestIDPolicy
	IdentityPolicy  identity_policy.IdentityPolicy
	Location        *time.Location
	Now             func() time.Time
}

// Pipeline orchestrates request-id, route policy, auth, rate limit, proxy, and access log.
type Pipeline struct {
	serviceName     string
	routePolicy     route_policy.RoutePolicy
	requestIDPolicy request_id.RequestIDPolicy
	identityPolicy  identity_policy.IdentityPolicy
	location        *time.Location
	now             func() time.Time
	deps            pipeline_deps.PipelineDependencies
}

// NewPipeline creates the application gateway pipeline.
func NewPipeline(config PipelineConfig, deps pipeline_deps.PipelineDependencies) *Pipeline {
	serviceName := config.ServiceName
	if serviceName == "" {
		serviceName = "monkeyocr-gateway"
	}
	location := config.Location
	if location == nil {
		location = time.Local
	}
	now := config.Now
	if now == nil {
		now = time.Now
	}
	pipelineDeps := pipeline_deps.PipelineDependencies{
		Authenticator:   deps.Authenticator,
		ClientIPLimiter: deps.ClientIPLimiter,
		APIKeyLimiter:   deps.APIKeyLimiter,
		ServiceLimiter:  deps.ServiceLimiter,
		Proxy:           deps.Proxy,
		AccessLogger:    deps.AccessLogger,
	}
	return &Pipeline{
		serviceName:     serviceName,
		routePolicy:     config.RoutePolicy,
		requestIDPolicy: config.RequestIDPolicy,
		identityPolicy:  config.IdentityPolicy,
		location:        location,
		now:             now,
		deps:            pipelineDeps,
	}
}

func (pipeline *Pipeline) beginRequest(w http.ResponseWriter, r *http.Request, route route_policy.Route) (*logging.AccessLogMetadata, time.Time) {
	start := pipeline.now().In(pipeline.location)
	requestID := pipeline.requestIDPolicy.Resolve(r.Header.Get(request_id.RequestIDHeader))
	r.Header.Set(request_id.RequestIDHeader, requestID)
	w.Header().Set(request_id.RequestIDHeader, requestID)
	userAgent := r.UserAgent()

	metadata := &logging.AccessLogMetadata{
		RequestTimestamp: start.Format(time.RFC3339Nano),
		RequestID:        requestID,
		Method:           r.Method,
		Path:             r.URL.Path,
		QueryPresent:     r.URL.RawQuery != "",
		ClientIP:         sharedheaders.ClientIP(r),
		AuthResult:       "skipped",
		UserAgentType:    classifyUserAgentType(userAgent),
		RateLimitResult:  "skipped",
	}
	if route.UpstreamService != "" {
		service := route.UpstreamService
		metadata.UpstreamService = &service
	}
	return metadata, start
}

func (pipeline *Pipeline) authenticate(r *http.Request, metadata *logging.AccessLogMetadata, route route_policy.Route) (*domain2.Identity, bool) {
	if !route.AuthRequired {
		metadata.AuthResult = auth.AuthResultPublic
		return nil, true
	}
	raw := strings.TrimSpace(r.Header.Get("Authorization"))
	if !strings.HasPrefix(raw, "Bearer ") {
		metadata.AuthResult = auth.AuthResultMissingAPIKey
		reason := "missing API key"
		metadata.RejectReason = &reason
		return nil, false
	}
	if pipeline.deps.Authenticator == nil {
		metadata.AuthResult = auth.AuthResultInvalidAPIKey
		reason := "missing authenticator"
		metadata.RejectReason = &reason
		errorType := "auth_error"
		metadata.ErrorType = &errorType
		return nil, false
	}
	identity, err := pipeline.deps.Authenticator.Authenticate(r.Context(), strings.TrimSpace(strings.TrimPrefix(raw, "Bearer ")))
	if err != nil {
		metadata.AuthResult = auth.AuthResultInvalidAPIKey
		reason := "invalid API key"
		metadata.RejectReason = &reason
		errorType := "auth_error"
		metadata.ErrorType = &errorType
		return nil, false
	}
	metadata.AuthResult = auth.AuthResultFingerprintReady
	metadata.APIKeyFingerprint = identity.APIKeyFingerprint
	return &identity, true
}

func (pipeline *Pipeline) isAllowedByLimiter(
	ctx context.Context,
	metadata *logging.AccessLogMetadata,
	results *pipeline_deps.RateLimitResults,
	limiter pipeline_deps.RateLimiter,
	target rate_limit.RateLimitTarget,
) bool {
	if target.Key == "" || limiter == nil {
		results.SetSkipped(target.Scope)
		metadata.RateLimitResult = results.String()
		return true
	}
	decision, err := limiter.GetRateLimitDecision(ctx, target)
	if err != nil {
		results.Set(target.Scope, "error")
		metadata.RateLimitResult = results.String()
		errorType := "rate_limit_error"
		metadata.ErrorType = &errorType
		// Public rate limits fail closed when Redis is unavailable. This avoids
		// silently removing abuse protection during infrastructure incidents.
		return false
	}
	result := decision.Result
	if result == "" {
		result = "allowed"
	}
	results.Set(target.Scope, result)
	metadata.RateLimitResult = results.String()
	if decision.Allowed {
		return true
	}
	reason := decision.RejectReason
	if reason == "" {
		reason = string(target.Scope) + " rate limit exceeded"
	}
	metadata.RejectReason = &reason
	return false
}

func (pipeline *Pipeline) emitLog(startTime time.Time, metadata *logging.AccessLogMetadata, recorder ResponseStatusRecorder) {
	metadata.HTTPStatusCode = recorder.Status()
	if internalCode, ok := recorder.InternalCode(); ok {
		metadata.InternalCode = internalCode
		metadata.InternalStatusName = internalStatusName(sharedapi.InternalStatusCode(internalCode))
	}
	metadata.RequestElapsedTime = pipeline.now().Sub(startTime).Milliseconds()
	if metadata.HTTPStatusCode >= http.StatusInternalServerError {
		errorType := "upstream_error"
		metadata.ErrorType = &errorType
	}
	if shouldSkipSuccessfulHealthProbeLog(metadata) {
		return
	}
	if pipeline.deps.AccessLogger == nil {
		return
	}
	level := sharedlogging.LogLevelInfo
	if metadata.HTTPStatusCode >= http.StatusInternalServerError {
		level = sharedlogging.LogLevelError
	} else if metadata.InternalCode != int(sharedapi.InternalStatusSuccess) {
		level = sharedlogging.LogLevelWarning
	}
	pipeline.deps.AccessLogger.Emit(logging.AccessLogEvent{
		Timestamp: startTime,
		Level:     level,
		Service:   pipeline.serviceName,
		Message:   "gateway request",
		TraceID:   metadata.RequestID,
		Metadata:  *metadata,
	})
}

// shouldSkipSuccessfulHealthProbeLog keeps routine local health probes out of access logs.
func shouldSkipSuccessfulHealthProbeLog(metadata *logging.AccessLogMetadata) bool {
	return metadata.Path == "/health" &&
		metadata.UpstreamService == nil &&
		metadata.HTTPStatusCode == http.StatusOK &&
		metadata.InternalCode == int(sharedapi.InternalStatusSuccess)
}

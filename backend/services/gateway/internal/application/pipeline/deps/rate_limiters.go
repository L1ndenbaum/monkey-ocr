package deps

import (
	"context"
	"monkeyocr-gateway/internal/domain/rate_limit"
	"strings"
)

type RateLimitResults struct {
	values map[rate_limit.RateLimitScope]string
}

func NewRateLimitResults() *RateLimitResults {
	return &RateLimitResults{values: map[rate_limit.RateLimitScope]string{}}
}

func (results *RateLimitResults) Set(scope rate_limit.RateLimitScope, result string) {
	if scope == "" {
		return
	}
	results.values[scope] = result
}

func (results *RateLimitResults) SetSkipped(scope rate_limit.RateLimitScope) {
	results.Set(scope, "skipped")
}

func (results *RateLimitResults) String() string {
	parts := make([]string, 0, 3)
	for _, scope := range []rate_limit.RateLimitScope{
		rate_limit.RateLimitScopeClientIP,
		rate_limit.RateLimitScopeAPIKey,
		rate_limit.RateLimitScopeService,
	} {
		if value, ok := results.values[scope]; ok {
			parts = append(parts, string(scope)+":"+value)
		}
	}
	if len(parts) == 0 {
		return "skipped"
	}
	return strings.Join(parts, ",")
}

// RateLimiter decides whether a request may enter an upstream service.
type RateLimiter interface {
	GetRateLimitDecision(context.Context, rate_limit.RateLimitTarget) (rate_limit.RateLimitDecision, error)
}

// ClientIPLimiter decides whether a client IP may continue through the gateway.
type ClientIPLimiter interface {
	GetRateLimitDecision(context.Context, rate_limit.RateLimitTarget) (rate_limit.RateLimitDecision, error)
}

// APIKeyLimiter decides whether an authenticated API key may continue through the gateway.
type APIKeyLimiter interface {
	GetRateLimitDecision(context.Context, rate_limit.RateLimitTarget) (rate_limit.RateLimitDecision, error)
}

// ServiceLimiter decides whether a request may enter an upstream service.
type ServiceLimiter interface {
	GetRateLimitDecision(context.Context, rate_limit.RateLimitTarget) (rate_limit.RateLimitDecision, error)
}

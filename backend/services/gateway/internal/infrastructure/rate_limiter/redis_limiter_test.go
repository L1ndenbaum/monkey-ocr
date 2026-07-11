package redis_rate_limiter

import (
	"context"
	"monkeyocr-gateway/internal/domain/rate_limit"
	"strings"
	"testing"
	"time"

	"github.com/redis/go-redis/v9"
)

type evalCall struct {
	script string
	keys   []string
	args   []interface{}
}

type spyRedisClient struct {
	calls  []evalCall
	result interface{}
}

func (client *spyRedisClient) Eval(ctx context.Context, script string, keys []string, args ...interface{}) *redis.Cmd {
	client.calls = append(client.calls, evalCall{script: script, keys: keys, args: args})
	if client.result == nil {
		client.result = []interface{}{int64(1), "allowed", "9"}
	}
	return redis.NewCmdResult(client.result, nil)
}

func TestRedisLimiterDisabledWhenRateOrBurstIsZero(t *testing.T) {
	client := &spyRedisClient{}
	limiter := NewRedisLimiter(client, TokenBucketProfile{
		Scope:         rate_limit.RateLimitScopeService,
		RatePerSecond: 0,
		Burst:         10,
	}, "monkeyocr-gateway:rate", time.Now)

	decision, err := limiter.GetRateLimitDecision(context.Background(), rate_limit.RateLimitTarget{
		Scope: rate_limit.RateLimitScopeService,
		Key:   "monkeyocr-backend",
	})
	if err != nil {
		t.Fatalf("allow: %v", err)
	}
	if !decision.Allowed || decision.Result != "disabled" {
		t.Fatalf("decision = %#v, want disabled allow", decision)
	}
	if len(client.calls) != 0 {
		t.Fatalf("disabled limiter should not call Redis, got %#v", client.calls)
	}
}

func TestRedisLimiterUsesSingleEvalWithTokenBucketArguments(t *testing.T) {
	now := time.Date(2026, 5, 17, 9, 30, 0, 123000000, time.UTC)
	client := &spyRedisClient{result: []interface{}{int64(1), "allowed", "4"}}
	limiter := NewRedisLimiter(client, TokenBucketProfile{
		Scope:         rate_limit.RateLimitScopeService,
		RatePerSecond: 10,
		Burst:         20,
	}, "monkeyocr-gateway:rate", func() time.Time { return now })

	decision, err := limiter.GetRateLimitDecision(context.Background(), rate_limit.RateLimitTarget{
		Scope: rate_limit.RateLimitScopeService,
		Key:   "monkeyocr-backend",
	})
	if err != nil {
		t.Fatalf("allow: %v", err)
	}
	if !decision.Allowed || decision.Result != "allowed" {
		t.Fatalf("decision = %#v, want allowed", decision)
	}
	if len(client.calls) != 1 {
		t.Fatalf("Eval calls = %d, want 1", len(client.calls))
	}
	call := client.calls[0]
	if len(call.keys) != 1 || call.keys[0] != "monkeyocr-gateway:rate:service:monkeyocr-backend" {
		t.Fatalf("keys = %#v", call.keys)
	}
	wantArgs := []interface{}{now.UnixMilli(), 10, 20, int64(4000)}
	if !equalInterfaces(call.args, wantArgs) {
		t.Fatalf("args = %#v, want %#v", call.args, wantArgs)
	}
	if containsRedisCommand(call.script, "INCR") || containsRedisCommand(call.script, "EXPIRE ") {
		t.Fatalf("token bucket script must not use fixed-window INCR/EXPIRE: %s", call.script)
	}
	if !containsRedisCommand(call.script, "PEXPIRE") {
		t.Fatalf("token bucket script should set TTL with PEXPIRE: %s", call.script)
	}
}

func TestRedisLimiterRejectedDecisionDoesNotConsumeTokenInScript(t *testing.T) {
	client := &spyRedisClient{result: []interface{}{int64(0), "rejected", "0"}}
	limiter := NewRedisLimiter(client, TokenBucketProfile{
		Scope:         rate_limit.RateLimitScopeClientIP,
		RatePerSecond: 1,
		Burst:         1,
	}, "monkeyocr-gateway:rate", time.Now)

	decision, err := limiter.GetRateLimitDecision(context.Background(), rate_limit.RateLimitTarget{
		Scope: rate_limit.RateLimitScopeClientIP,
		Key:   "203.0.113.10",
	})
	if err != nil {
		t.Fatalf("allow: %v", err)
	}
	if decision.Allowed || decision.Result != "rejected" {
		t.Fatalf("decision = %#v, want rejected", decision)
	}
	if !containsScriptSnippet(client.calls[0].script, "tokens = tokens - 1") {
		t.Fatalf("script should only consume tokens inside allowed branch: %s", client.calls[0].script)
	}
}

func TestServiceRedisLimiterUsesProfileForRequestedService(t *testing.T) {
	now := time.Date(2026, 5, 17, 10, 0, 0, 0, time.UTC)
	client := &spyRedisClient{result: []interface{}{int64(1), "allowed", "2"}}
	limiter := NewServiceRedisLimiter(
		client,
		map[string]TokenBucketProfile{
			"monkeyocr-backend": {
				Scope:         rate_limit.RateLimitScopeService,
				RatePerSecond: 10,
				Burst:         20,
			},
			"storage-service": {
				Scope:         rate_limit.RateLimitScopeService,
				RatePerSecond: 3,
				Burst:         6,
			},
		},
		TokenBucketProfile{Scope: rate_limit.RateLimitScopeService, RatePerSecond: 1, Burst: 1},
		"monkeyocr-gateway:rate",
		func() time.Time { return now },
	)

	_, err := limiter.GetRateLimitDecision(context.Background(), rate_limit.RateLimitTarget{
		Scope: rate_limit.RateLimitScopeService,
		Key:   "storage-service",
	})
	if err != nil {
		t.Fatalf("allow: %v", err)
	}

	if len(client.calls) != 1 {
		t.Fatalf("Eval calls = %d, want 1", len(client.calls))
	}
	call := client.calls[0]
	wantArgs := []interface{}{now.UnixMilli(), 3, 6, int64(4000)}
	if !equalInterfaces(call.args, wantArgs) {
		t.Fatalf("args = %#v, want %#v", call.args, wantArgs)
	}
	if len(call.keys) != 1 || call.keys[0] != "monkeyocr-gateway:rate:service:storage-service" {
		t.Fatalf("keys = %#v", call.keys)
	}
}

func equalInterfaces(left []interface{}, right []interface{}) bool {
	if len(left) != len(right) {
		return false
	}
	for index := range left {
		if left[index] != right[index] {
			return false
		}
	}
	return true
}

func containsRedisCommand(script string, command string) bool {
	return strings.Contains(strings.ToUpper(script), command)
}

func containsScriptSnippet(script string, snippet string) bool {
	return strings.Contains(script, snippet)
}

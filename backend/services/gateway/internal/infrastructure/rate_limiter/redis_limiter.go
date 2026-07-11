package redis_rate_limiter

import (
	"context"
	"fmt"
	"monkeyocr-gateway/internal/domain/rate_limit"
	"strconv"
	"strings"
	"time"

	"github.com/redis/go-redis/v9"
)

const tokenBucketScript = `
local key = KEYS[1]
local now_ms = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local burst = tonumber(ARGV[3])
local ttl_ms = tonumber(ARGV[4])

local tokens = tonumber(redis.call("HGET", key, "tokens"))
local updated_at_ms = tonumber(redis.call("HGET", key, "updated_at_ms"))

if tokens == nil or updated_at_ms == nil then
	tokens = burst
	updated_at_ms = now_ms
end

local elapsed_ms = now_ms - updated_at_ms
if elapsed_ms < 0 then
	elapsed_ms = 0
end

tokens = math.min(burst, tokens + ((elapsed_ms / 1000) * rate))
updated_at_ms = now_ms

if tokens >= 1 then
	tokens = tokens - 1
	redis.call("HSET", key, "tokens", tokens, "updated_at_ms", updated_at_ms)
	redis.call("PEXPIRE", key, ttl_ms)
	return {1, "allowed", tostring(tokens)}
end

redis.call("HSET", key, "tokens", tokens, "updated_at_ms", updated_at_ms)
redis.call("PEXPIRE", key, ttl_ms)
return {0, "rejected", tostring(tokens)}
`

type scriptRunner interface {
	Eval(ctx context.Context, script string, keys []string, args ...interface{}) *redis.Cmd
}

// TokenBucketProfile configures a Redis token bucket limiter.
type TokenBucketProfile struct {
	Scope         rate_limit.RateLimitScope
	RatePerSecond int
	Burst         int
}

// RedisLimiter applies one token bucket profile through a Redis Lua script.
type RedisLimiter struct {
	client    scriptRunner
	profile   TokenBucketProfile
	keyPrefix string
	now       func() time.Time
}

// ServiceRedisLimiter applies service-specific token bucket profiles using one Redis client.
type ServiceRedisLimiter struct {
	client    scriptRunner
	profiles  map[string]TokenBucketProfile
	fallback  TokenBucketProfile
	keyPrefix string
	now       func() time.Time
}

// NewRedisLimiter creates a Redis-backed token bucket limiter.
func NewRedisLimiter(
	client scriptRunner,
	profile TokenBucketProfile,
	keyPrefix string,
	now func() time.Time,
) *RedisLimiter {
	if keyPrefix == "" {
		keyPrefix = "monkeyocr:gateway:rate"
	}
	if now == nil {
		now = time.Now
	}
	return &RedisLimiter{
		client:    client,
		profile:   profile,
		keyPrefix: keyPrefix,
		now:       now,
	}
}

// NewServiceRedisLimiter creates a Redis limiter that selects profiles by upstream service name.
func NewServiceRedisLimiter(
	client scriptRunner,
	profiles map[string]TokenBucketProfile,
	fallback TokenBucketProfile,
	keyPrefix string,
	now func() time.Time,
) *ServiceRedisLimiter {
	if keyPrefix == "" {
		keyPrefix = "monkeyocr:gateway:rate"
	}
	if now == nil {
		now = time.Now
	}
	copiedProfiles := make(map[string]TokenBucketProfile, len(profiles))
	for service, profile := range profiles {
		if profile.Scope == "" {
			profile.Scope = rate_limit.RateLimitScopeService
		}
		copiedProfiles[service] = profile
	}
	if fallback.Scope == "" {
		fallback.Scope = rate_limit.RateLimitScopeService
	}
	return &ServiceRedisLimiter{
		client:    client,
		profiles:  copiedProfiles,
		fallback:  fallback,
		keyPrefix: keyPrefix,
		now:       now,
	}
}

// GetRateLimitDecision atomically refills and consumes one token for a target.
func (limiter *RedisLimiter) GetRateLimitDecision(ctx context.Context, target rate_limit.RateLimitTarget) (rate_limit.RateLimitDecision, error) {
	if limiter.profile.RatePerSecond <= 0 || limiter.profile.Burst <= 0 {
		return rate_limit.RateLimitDecision{Allowed: true, Result: "disabled"}, nil
	}
	if limiter.client == nil {
		return rate_limit.RateLimitDecision{}, fmt.Errorf("redis limiter client is nil")
	}
	if target.Scope == "" {
		target.Scope = limiter.profile.Scope
	}
	key := limiter.redisKey(target)
	result, err := limiter.client.Eval(
		ctx,
		tokenBucketScript,
		[]string{key},
		limiter.now().UnixMilli(),
		limiter.profile.RatePerSecond,
		limiter.profile.Burst,
		limiter.ttl().Milliseconds(),
	).Result()
	if err != nil {
		return rate_limit.RateLimitDecision{}, err
	}
	return parseTokenBucketResult(result)
}

// GetRateLimitDecision atomically limits one upstream service with that service's profile.
func (limiter *ServiceRedisLimiter) GetRateLimitDecision(ctx context.Context, target rate_limit.RateLimitTarget) (rate_limit.RateLimitDecision, error) {
	if limiter == nil {
		return rate_limit.RateLimitDecision{Allowed: true, Result: "disabled"}, nil
	}
	profile := limiter.fallback
	if selected, ok := limiter.profiles[target.Key]; ok {
		profile = selected
	}
	return NewRedisLimiter(limiter.client, profile, limiter.keyPrefix, limiter.now).
		GetRateLimitDecision(ctx, target)
}

func (limiter *RedisLimiter) redisKey(target rate_limit.RateLimitTarget) string {
	scope := string(target.Scope)
	if scope == "" {
		scope = "unknown"
	}
	return fmt.Sprintf("%s:%s:%s", limiter.keyPrefix, sanitizeRateKey(scope), sanitizeRateKey(target.Key))
}

func (limiter *RedisLimiter) ttl() time.Duration {
	refill := time.Duration((2 * float64(limiter.profile.Burst) / float64(limiter.profile.RatePerSecond)) * float64(time.Second))
	if refill < time.Second {
		return time.Second
	}
	return refill
}

func parseTokenBucketResult(value interface{}) (rate_limit.RateLimitDecision, error) {
	values, ok := value.([]interface{})
	if !ok || len(values) < 2 {
		return rate_limit.RateLimitDecision{}, fmt.Errorf("unexpected redis token bucket result %#v", value)
	}
	allowed, err := asInt64(values[0])
	if err != nil {
		return rate_limit.RateLimitDecision{}, err
	}
	result := fmt.Sprint(values[1])
	if allowed == 1 {
		return rate_limit.RateLimitDecision{Allowed: true, Result: result}, nil
	}
	return rate_limit.RateLimitDecision{Allowed: false, Result: result}, nil
}

func asInt64(value interface{}) (int64, error) {
	switch typed := value.(type) {
	case int64:
		return typed, nil
	case int:
		return int64(typed), nil
	case string:
		return strconv.ParseInt(typed, 10, 64)
	case []byte:
		return strconv.ParseInt(string(typed), 10, 64)
	default:
		return 0, fmt.Errorf("unexpected redis token bucket flag %#v", value)
	}
}

func sanitizeRateKey(value string) string {
	value = strings.TrimSpace(value)
	if value == "" {
		return "unknown"
	}
	replacer := strings.NewReplacer(":", "_", "/", "_", " ", "_")
	return replacer.Replace(value)
}

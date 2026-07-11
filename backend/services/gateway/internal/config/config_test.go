package config

import (
	"reflect"
	"testing"
	"time"
)

// TestTimeLocationResolvesGatewayTimeZone verifies gateway timestamps use the configured IANA zone.
func TestTimeLocationResolvesGatewayTimeZone(t *testing.T) {
	t.Setenv("GATEWAY_TIME_ZONE", "Asia/Shanghai")

	cfg := Load()
	location, err := cfg.TimeLocation()
	if err != nil {
		t.Fatalf("TimeLocation returned error: %v", err)
	}

	got := time.Date(2026, 5, 16, 7, 22, 52, 742470455, time.UTC).
		In(location).
		Format(time.RFC3339Nano)
	if got != "2026-05-16T15:22:52.742470455+08:00" {
		t.Fatalf("localized time = %q", got)
	}
}

// TestLoadReadsAccessLogQueueSize verifies access log buffering is configurable.
func TestLoadReadsAccessLogQueueSize(t *testing.T) {
	t.Setenv("GATEWAY_ACCESS_LOG_QUEUE_SIZE", "128")

	cfg := Load()

	if cfg.AccessLogQueueSize != 128 {
		t.Fatalf("AccessLogQueueSize = %d, want 128", cfg.AccessLogQueueSize)
	}
}

// TestLoadReadsCORSAllowedOrigins verifies browser origins are gateway-owned.
func TestLoadReadsCORSAllowedOrigins(t *testing.T) {
	t.Setenv("GATEWAY_CORS_ORIGINS", " http://localhost:5173, http://localhost:12016 ")

	cfg := Load()

	want := []string{"http://localhost:5173", "http://localhost:12016"}
	if !reflect.DeepEqual(cfg.CORSAllowedOrigins, want) {
		t.Fatalf("CORSAllowedOrigins = %#v, want %#v", cfg.CORSAllowedOrigins, want)
	}
}

// TestLoadReadsGatewayRateLimitProfiles verifies token bucket profiles come from env.
func TestLoadReadsGatewayRateLimitProfiles(t *testing.T) {
	t.Setenv("GATEWAY_CLIENT_IP_RATE", "21")
	t.Setenv("GATEWAY_CLIENT_IP_BURST", "42")
	t.Setenv("GATEWAY_API_KEY_RATE", "11")
	t.Setenv("GATEWAY_API_KEY_BURST", "22")
	t.Setenv("MONKEYOCR_BACKEND_RATE", "7")
	t.Setenv("MONKEYOCR_BACKEND_BURST", "14")

	cfg := Load()

	if cfg.ClientIPRateLimit != (RateLimitProfile{RatePerSecond: 21, Burst: 42}) {
		t.Fatalf("ClientIPRateLimit = %#v", cfg.ClientIPRateLimit)
	}
	if cfg.APIKeyRateLimit != (RateLimitProfile{RatePerSecond: 11, Burst: 22}) {
		t.Fatalf("APIKeyRateLimit = %#v", cfg.APIKeyRateLimit)
	}
	if cfg.ServiceRateLimitProfile("monkeyocr-backend") != (RateLimitProfile{RatePerSecond: 7, Burst: 14}) {
		t.Fatalf("service profile = %#v", cfg.ServiceRateLimitProfile("monkeyocr-backend"))
	}
}

// TestServiceRateLimitEnvPrefixNormalizesServiceNames documents service env naming.
func TestServiceRateLimitEnvPrefixNormalizesServiceNames(t *testing.T) {
	if got := ServiceRateLimitEnvPrefix("monkeyocr-backend"); got != "MONKEYOCR_BACKEND" {
		t.Fatalf("prefix = %q, want MONKEYOCR_BACKEND", got)
	}
}

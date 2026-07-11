package main

import (
	"context"
	"log"
	"monkeyocr-gateway/internal/application/identity_policy"
	appgateway "monkeyocr-gateway/internal/application/pipeline"
	pipeline_deps "monkeyocr-gateway/internal/application/pipeline/deps"
	"monkeyocr-gateway/internal/application/route_policy"
	"monkeyocr-gateway/internal/domain/rate_limit"
	domain2 "monkeyocr-gateway/internal/domain/request_id"
	"net/http"
	"os/signal"
	"syscall"
	"time"

	"github.com/redis/go-redis/v9"

	"monkeyocr-gateway/internal/config"
	apikeyinfra "monkeyocr-gateway/internal/infrastructure/apikey"
	logginginfra "monkeyocr-gateway/internal/infrastructure/logging"
	proxyinfra "monkeyocr-gateway/internal/infrastructure/proxy"
	ratelimitinfra "monkeyocr-gateway/internal/infrastructure/rate_limiter"
	httpapi "monkeyocr-gateway/internal/interfaces/http"
	httpserver "monkeyocr-services-lib-go/http/server"
	sharedlogging "monkeyocr-services-lib-go/logging"
)

// main wires configuration, Redis rate limiting, logging, and the HTTP server lifecycle.
func main() {
	cfg := config.Load()
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	redisOptions, err := redis.ParseURL(cfg.RedisURL)
	if err != nil {
		log.Fatalf("invalid REDIS_URL: %v", err)
	}
	timeLocation, err := cfg.TimeLocation()
	if err != nil {
		log.Fatalf("invalid GATEWAY_TIME_ZONE %q: %v", cfg.TimeZone, err)
	}
	redisClient := redis.NewClient(redisOptions)
	defer redisClient.Close()
	var apiKeyValidator apikeyinfra.Validator
	if len(cfg.APIKeyEmergencyAllowlist) > 0 {
		apiKeyValidator, err = apikeyinfra.NewStaticSHA256Validator(cfg.APIKeyEmergencyAllowlist)
		if err != nil {
			log.Fatalf("invalid GATEWAY_API_KEY_EMERGENCY_SHA256_ALLOWLIST: %v", err)
		}
	}

	loggingClient := sharedlogging.NewLoggingServiceClient(
		sharedlogging.LoggingServiceClientConfig{
			BaseURL:   cfg.LoggingServiceURL,
			Token:     cfg.LoggingServiceToken,
			Timeout:   cfg.LoggingServiceTimeout,
			QueueSize: cfg.AccessLogQueueSize,
		},
	)
	accessLogger := logginginfra.NewGatewayAccessLogger(
		logginginfra.GatewayAccessLoggerConfig{
			Emitter: loggingClient,
		},
	)
	proxyTransport := http.DefaultTransport.(*http.Transport).Clone()
	proxyTransport.ResponseHeaderTimeout = cfg.UpstreamResponseHeaderTimeout

	pipelineDependencies := pipeline_deps.PipelineDependencies{
		Authenticator: apikeyinfra.NewAuthenticator(apiKeyValidator),
		ClientIPLimiter: ratelimitinfra.NewRedisLimiter(
			redisClient,
			ratelimitinfra.TokenBucketProfile{
				Scope:         rate_limit.RateLimitScopeClientIP,
				RatePerSecond: cfg.ClientIPRateLimit.RatePerSecond,
				Burst:         cfg.ClientIPRateLimit.Burst,
			},
			cfg.RateLimitKeyPrefix,
			time.Now,
		),
		APIKeyLimiter: ratelimitinfra.NewRedisLimiter(
			redisClient,
			ratelimitinfra.TokenBucketProfile{
				Scope:         rate_limit.RateLimitScopeAPIKey,
				RatePerSecond: cfg.APIKeyRateLimit.RatePerSecond,
				Burst:         cfg.APIKeyRateLimit.Burst,
			},
			cfg.RateLimitKeyPrefix,
			time.Now,
		),
		ServiceLimiter: ratelimitinfra.NewServiceRedisLimiter(
			redisClient,
			map[string]ratelimitinfra.TokenBucketProfile{
				"monkeyocr-backend": {
					Scope:         rate_limit.RateLimitScopeService,
					RatePerSecond: cfg.ServiceRateLimitProfile("monkeyocr-backend").RatePerSecond,
					Burst:         cfg.ServiceRateLimitProfile("monkeyocr-backend").Burst,
				},
			},
			ratelimitinfra.TokenBucketProfile{Scope: rate_limit.RateLimitScopeService},
			cfg.RateLimitKeyPrefix,
			time.Now,
		),
		Proxy:        proxyinfra.NewReverseProxy(cfg.BackendURL, proxyTransport),
		AccessLogger: accessLogger,
	}
	pipeline := appgateway.NewPipeline(
		appgateway.PipelineConfig{
			ServiceName:     cfg.LoggingServiceName,
			RoutePolicy:     route_policy.NewDefaultRoutePolicy(cfg.BackendURL),
			RequestIDPolicy: domain2.RequestIDPolicy{},
			IdentityPolicy:  identity_policy.IdentityPolicy{},
			Location:        timeLocation,
			Now:             time.Now,
		},
		pipelineDependencies,
	)
	router := httpapi.NewRouter(
		httpapi.NewHandler(pipeline),
		httpapi.CORSConfig{
			AllowedOrigins:      cfg.CORSAllowedOrigins,
			MaxRequestBodyBytes: cfg.MaxRequestBodyBytes,
		},
	)
	server := httpserver.New(cfg.HTTPServerConfig(), router)

	go func() {
		<-ctx.Done()
		shutdownCtx, cancel := context.WithTimeout(context.Background(), cfg.ShutdownTimeout)
		defer cancel()
		if err := server.Shutdown(shutdownCtx); err != nil {
			log.Printf("gateway shutdown failed: %v", err)
		}
		if err := accessLogger.Close(shutdownCtx); err != nil {
			log.Printf("gateway access log drain failed: %v", err)
		}
	}()

	log.Printf("monkeyocr-gateway listening on %s", cfg.Addr)
	if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatal(err)
	}
}

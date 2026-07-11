package config

import (
	"time"

	"monkeyocr-services-lib-go/envconfig"
	httpserver "monkeyocr-services-lib-go/http/server"
)

type Config struct {
	Addr               string
	ServiceToken       string
	MinIORegion        string
	InternalEndpoint   string
	PublicEndpoint     string
	AccessKey          string
	SecretKey          string
	ReadHeaderTimeout  time.Duration
	ReadTimeout        time.Duration
	WriteTimeout       time.Duration
	IdleTimeout        time.Duration
	MaxUploadBodyBytes int64
}

const defaultMaxUploadBodyBytes int64 = 512 << 20

// Load reads environment variables and applies local development defaults.
func Load() Config {
	return Config{
		Addr:               envconfig.String("STORAGE_SERVICE_ADDR", ":13003"),
		ServiceToken:       envconfig.String("STORAGE_SERVICE_TOKEN", ""),
		MinIORegion:        envconfig.String("MINIO_REGION", "us-east-1"),
		InternalEndpoint:   envconfig.String("MINIO_INTERNAL_ENDPOINT", "http://127.0.0.1:13009"),
		PublicEndpoint:     envconfig.String("MINIO_PUBLIC_ENDPOINT", "http://localhost:13009"),
		AccessKey:          envconfig.String("MINIO_ACCESS_KEY", ""),
		SecretKey:          envconfig.String("MINIO_SECRET_KEY", ""),
		ReadHeaderTimeout:  envconfig.Duration("STORAGE_SERVICE_READ_HEADER_TIMEOUT", 5*time.Second),
		ReadTimeout:        envconfig.Duration("STORAGE_SERVICE_READ_TIMEOUT", 30*time.Second),
		WriteTimeout:       envconfig.Duration("STORAGE_SERVICE_WRITE_TIMEOUT", 120*time.Second),
		IdleTimeout:        envconfig.Duration("STORAGE_SERVICE_IDLE_TIMEOUT", 60*time.Second),
		MaxUploadBodyBytes: envconfig.Int64("STORAGE_SERVICE_MAX_UPLOAD_BYTES", defaultMaxUploadBodyBytes),
	}
}

// HTTPServerConfig returns the shared HTTP server settings for this service.
func (cfg Config) HTTPServerConfig() httpserver.Config {
	return httpserver.Config{
		Addr:              cfg.Addr,
		ReadHeaderTimeout: cfg.ReadHeaderTimeout,
		ReadTimeout:       cfg.ReadTimeout,
		WriteTimeout:      cfg.WriteTimeout,
		IdleTimeout:       cfg.IdleTimeout,
	}
}

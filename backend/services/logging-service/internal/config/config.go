package config

import (
	"time"

	"monkeyocr-services-lib-go/envconfig"
	httpserver "monkeyocr-services-lib-go/http/server"
)

// Config is the environment-derived runtime configuration for logging-service.
type Config struct {
	Addr              string
	ServiceToken      string
	DataDir           string
	ConsoleColor      bool
	ReadHeaderTimeout time.Duration
	ReadTimeout       time.Duration
	WriteTimeout      time.Duration
	IdleTimeout       time.Duration
	ShutdownTimeout   time.Duration
	FlushInterval     time.Duration
	ReplayInterval    time.Duration
	QueueSize         int
	MaxBatchSize      int
	KafkaBrokers      []string
	KafkaTopic        string
	SpoolFile         string
	ErrorAuditFile    string
}

// Load reads environment variables and applies local development defaults.
func Load() Config {
	dataDir := envconfig.String("LOGGING_SERVICE_DATA_DIR", "/var/lib/logging-service")
	return Config{
		Addr:              envconfig.String("LOGGING_SERVICE_ADDR", ":13004"),
		ServiceToken:      envconfig.String("LOGGING_SERVICE_TOKEN", ""),
		DataDir:           dataDir,
		ConsoleColor:      envconfig.Bool("LOGGING_CONSOLE_COLOR", true),
		ReadHeaderTimeout: envconfig.Duration("LOGGING_SERVICE_READ_HEADER_TIMEOUT", 5*time.Second),
		ReadTimeout:       envconfig.Duration("LOGGING_SERVICE_READ_TIMEOUT", 10*time.Second),
		WriteTimeout:      envconfig.Duration("LOGGING_SERVICE_WRITE_TIMEOUT", 10*time.Second),
		IdleTimeout:       envconfig.Duration("LOGGING_SERVICE_IDLE_TIMEOUT", 60*time.Second),
		ShutdownTimeout:   envconfig.Duration("LOGGING_SERVICE_SHUTDOWN_TIMEOUT", 10*time.Second),
		FlushInterval:     time.Duration(envconfig.Int("LOGGING_BATCH_FLUSH_MS", 500)) * time.Millisecond,
		ReplayInterval:    envconfig.Duration("LOGGING_KAFKA_REPLAY_INTERVAL", 5*time.Second),
		QueueSize:         envconfig.Int("LOGGING_QUEUE_SIZE", 4096),
		MaxBatchSize:      envconfig.Int("LOGGING_MAX_BATCH_SIZE", 512),
		KafkaBrokers:      envconfig.CSV("LOGGING_KAFKA_BROKERS", "127.0.0.1:13007"),
		KafkaTopic:        envconfig.String("LOGGING_KAFKA_TOPIC", "monkeyocr.events.logging.v1"),
		SpoolFile:         envconfig.String("LOGGING_SPOOL_FILE", dataDir+"/spool/kafka_invalid_temp_events.jsonl"),
		ErrorAuditFile:    envconfig.String("LOGGING_ERROR_AUDIT_FILE", dataDir+"/archive/kafka_invalid_temp_error_audit_events.jsonl"),
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

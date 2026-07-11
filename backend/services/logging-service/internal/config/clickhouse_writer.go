package config

import (
	"fmt"
	"time"

	"monkeyocr-services-lib-go/envconfig"
)

// ClickHouseWriterConfig is the environment-derived config for the Kafka consumer.
type ClickHouseWriterConfig struct {
	KafkaBrokers       []string
	KafkaTopic         string
	KafkaGroupID       string
	ClickHouseHTTPURL  string
	ClickHouseDatabase string
	ClickHouseTable    string
	ClickHouseUser     string
	ClickHousePassword string
	BatchSize          int
	FlushInterval      time.Duration
	HTTPTimeout        time.Duration
}

// LoadClickHouseWriter reads Kafka and ClickHouse settings for clickhouse-writer.
func LoadClickHouseWriter() ClickHouseWriterConfig {
	host := envconfig.String("CLICKHOUSE_HOST", "clickhouse")
	httpPort := envconfig.String("CLICKHOUSE_HTTP_PORT", "13011")
	return ClickHouseWriterConfig{
		KafkaBrokers:       envconfig.CSV("LOGGING_KAFKA_BROKERS", "127.0.0.1:13007"),
		KafkaTopic:         envconfig.String("LOGGING_KAFKA_TOPIC", "monkeyocr.events.logging.v1"),
		KafkaGroupID:       envconfig.String("CLICKHOUSE_WRITER_GROUP_ID", "monkeyocr-logging-clickhouse-writer"),
		ClickHouseHTTPURL:  envconfig.String("CLICKHOUSE_HTTP_URL", fmt.Sprintf("http://%s:%s", host, httpPort)),
		ClickHouseDatabase: envconfig.String("CLICKHOUSE_DATABASE", "monkeyocr_logging_db"),
		ClickHouseTable:    envconfig.String("CLICKHOUSE_LOGS_TABLE", "monkeyocr_logs"),
		ClickHouseUser:     envconfig.String("CLICKHOUSE_USER", "monkeyocr_logging"),
		ClickHousePassword: envconfig.String("CLICKHOUSE_PASSWORD", ""),
		BatchSize:          envconfig.Int("CLICKHOUSE_WRITER_BATCH_SIZE", 500),
		FlushInterval:      envconfig.Duration("CLICKHOUSE_WRITER_FLUSH_INTERVAL", time.Second),
		HTTPTimeout:        envconfig.Duration("CLICKHOUSE_WRITER_HTTP_TIMEOUT", 5*time.Second),
	}
}

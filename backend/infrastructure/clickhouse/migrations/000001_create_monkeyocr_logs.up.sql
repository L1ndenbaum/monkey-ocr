CREATE TABLE IF NOT EXISTS monkeyocr_logs
(
    event_id UUID,
    timestamp DateTime64(3, 'UTC'),
    level LowCardinality(String),
    service LowCardinality(String),
    message String,
    request_id String,
    trace_id String,
    http_status_code Nullable(UInt16),
    internal_code Nullable(UInt32),
    internal_status_name LowCardinality(String),
    metadata_json String,
    ingested_at DateTime64(3, 'UTC')
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(timestamp)
ORDER BY event_id;

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    environment: Literal["dev", "test", "production"] = Field(
        default="dev", validation_alias=AliasChoices("ENVIRONMENT", "MONKEYOCR_ENVIRONMENT")
    )
    host: str = Field(default="0.0.0.0", validation_alias=AliasChoices("BACKEND_HOST", "HOST"))
    port: int = Field(default=13001, validation_alias=AliasChoices("BACKEND_PORT", "PORT"))
    max_upload_bytes: int = Field(
        default=100 * 1024 * 1024,
        validation_alias=AliasChoices("MAX_UPLOAD_BYTES", "MAX_CONTENT_LENGTH"),
    )
    require_gateway_identity: bool = Field(
        default=False, validation_alias=AliasChoices("REQUIRE_GATEWAY_IDENTITY", "BACKEND_REQUIRE_AUTH")
    )
    dev_api_key_id: str = "development"

    repository_adapter: Literal["memory", "postgres"] = "memory"
    storage_adapter: Literal["memory", "s3", "storage-service"] = "memory"
    engine_adapter: Literal["fake", "paddleocr-vl"] = Field(
        default="fake", validation_alias=AliasChoices("OCR_ENGINE", "ENGINE_ADAPTER")
    )
    preprocessor_adapter: Literal["passthrough", "sandbox"] = "passthrough"

    database_url: str | None = Field(default=None, validation_alias="DATABASE_URL")
    database_pool_size: int = Field(
        default=10, validation_alias="DATABASE_POOL_SIZE", ge=2, le=100
    )
    kafka_bootstrap_servers: str | None = Field(
        default=None, validation_alias=AliasChoices("KAFKA_BROKERS", "KAFKA_BOOTSTRAP_SERVERS")
    )
    kafka_jobs_topic: str = Field(
        default="monkeyocr.events.jobs", validation_alias="OCR_JOB_TOPIC"
    )
    kafka_jobs_dlq_topic: str = Field(
        default="monkeyocr.events.jobs.dlq", validation_alias="OCR_JOB_DLQ_TOPIC"
    )
    kafka_consumer_group: str = Field(
        default="monkeyocr-ocr-workers", validation_alias="OCR_JOB_CONSUMER_GROUP"
    )
    kafka_client_id: str = Field(
        default="monkeyocr-backend", validation_alias="KAFKA_CLIENT_ID"
    )

    s3_endpoint_url: str | None = Field(default=None, validation_alias="MINIO_ENDPOINT")
    s3_region: str = Field(default="us-east-1", validation_alias="MINIO_REGION")
    s3_access_key_id: str | None = Field(default=None, validation_alias="MINIO_ACCESS_KEY")
    s3_secret_access_key: str | None = Field(default=None, validation_alias="MINIO_SECRET_KEY")
    s3_bucket: str = Field(
        default="monkeyocr-documents", validation_alias="DOCUMENT_STORAGE_BUCKET"
    )
    s3_presign_ttl_seconds: int = Field(
        default=900, validation_alias="PRESIGNED_URL_TTL_SECONDS", ge=60, le=86400
    )
    multipart_part_size_bytes: int = Field(
        default=8 * 1024 * 1024,
        validation_alias="MULTIPART_PART_SIZE_BYTES",
        ge=5 * 1024 * 1024,
    )
    upload_session_ttl_seconds: int = Field(
        default=3600, validation_alias="UPLOAD_SESSION_TTL_SECONDS", ge=60
    )

    storage_service_url: str | None = Field(default=None, validation_alias="STORAGE_SERVICE_URL")
    storage_service_token: str | None = Field(default=None, validation_alias="STORAGE_SERVICE_TOKEN")

    paddleocr_vl_base_url: str | None = Field(default=None, validation_alias="OCR_ENGINE_URL")
    paddleocr_vl_model_name: str = Field(
        default="PaddleOCR-VL-1.6", validation_alias="OCR_ENGINE_MODEL"
    )
    paddleocr_vl_engine_version: str = Field(
        default="3.6",
        validation_alias=AliasChoices("OCR_ENGINE_VERSION", "HPS_PADDLEX_VERSION"),
    )
    paddleocr_vl_endpoint_path: str = "/layout-parsing"
    paddleocr_vl_timeout_seconds: float = Field(
        default=300, validation_alias="OCR_ENGINE_TIMEOUT_SECONDS"
    )
    sandbox_base_url: str | None = None
    sandbox_command: str | None = Field(default=None, validation_alias="SANDBOX_COMMAND")
    sandbox_exchange_dir: str | None = Field(
        default=None, validation_alias="SANDBOX_EXCHANGE_DIR"
    )
    sandbox_timeout_seconds: float = 120
    sandbox_max_pages: int = Field(
        default=500, validation_alias="MAX_DOCUMENT_PAGES", ge=1, le=5000
    )
    sandbox_max_pixels: int = Field(
        default=100_000_000, validation_alias="MAX_IMAGE_PIXELS", ge=1_000_000
    )
    sandbox_pdf_dpi: int = Field(
        default=180, validation_alias="PDF_RENDER_DPI", ge=72, le=600
    )
    logging_service_url: str | None = Field(default=None, validation_alias="LOGGING_SERVICE_URL")
    logging_service_token: str | None = Field(default=None, validation_alias="LOGGING_SERVICE_TOKEN")
    logging_service_name: str = Field(
        default="monkeyocr-backend", validation_alias="LOGGING_SERVICE_NAME"
    )
    logging_service_timeout_seconds: float = Field(
        default=2,
        validation_alias="LOGGING_SERVICE_TIMEOUT_SECONDS",
        gt=0,
        le=30,
    )
    api_key_pepper: str | None = Field(
        default=None, validation_alias=AliasChoices("API_KEY_PEPPER", "MONKEYOCR_API_KEY_PEPPER")
    )

    worker_max_page_retries: int = Field(
        default=3, validation_alias="OCR_ENGINE_MAX_RETRIES", ge=0
    )
    worker_retry_base_seconds: float = Field(
        default=1, validation_alias="OCR_ENGINE_RETRY_BASE_SECONDS"
    )
    worker_readiness_timeout_seconds: float = Field(
        default=900,
        validation_alias="WORKER_READINESS_TIMEOUT_SECONDS",
        gt=0,
    )
    worker_readiness_poll_seconds: float = Field(
        default=5,
        validation_alias="WORKER_READINESS_POLL_SECONDS",
        gt=0,
    )
    job_retention_days: int = Field(default=30, validation_alias="JOB_RETENTION_DAYS", ge=1)
    retention_cleanup_interval_seconds: float = Field(
        default=300,
        validation_alias="RETENTION_CLEANUP_INTERVAL_SECONDS",
        gt=0,
    )
    retention_cleanup_batch_size: int = Field(
        default=20, validation_alias="RETENTION_CLEANUP_BATCH_SIZE", ge=1, le=1000
    )
    retention_cleanup_lease_seconds: int = Field(
        default=3600, validation_alias="RETENTION_CLEANUP_LEASE_SECONDS", ge=1
    )
    retention_cleanup_retry_seconds: int = Field(
        default=30, validation_alias="RETENTION_CLEANUP_RETRY_SECONDS", ge=1
    )
    retention_cleanup_delete_concurrency: int = Field(
        default=8,
        validation_alias="RETENTION_CLEANUP_DELETE_CONCURRENCY",
        ge=1,
        le=64,
    )
    sse_heartbeat_seconds: float = 15

    @field_validator("engine_adapter", mode="before")
    @classmethod
    def normalize_engine(cls, value: object) -> object:
        if isinstance(value, str) and value.lower() in {
            "paddle",
            "paddleocr",
            "paddleocr_vl",
            "paddleocr_vl_hps",
        }:
            return "paddleocr-vl"
        return value

    @field_validator("environment", mode="before")
    @classmethod
    def normalize_environment(cls, value: object) -> object:
        return "dev" if value == "development" else value

    @field_validator("database_url", mode="after")
    @classmethod
    def normalize_asyncpg_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.replace("postgresql+psycopg://", "postgresql://").replace(
            "postgresql+asyncpg://", "postgresql://"
        )

    @model_validator(mode="after")
    def infer_durable_adapters(self) -> Settings:
        if self.database_url and self.repository_adapter == "memory" and self.environment != "test":
            self.repository_adapter = "postgres"
        if self.storage_service_url and self.storage_adapter == "memory" and self.environment != "test":
            self.storage_adapter = "storage-service"
        elif self.s3_endpoint_url and self.storage_adapter == "memory" and self.environment != "test":
            self.storage_adapter = "s3"
        if (
            (self.sandbox_exchange_dir or self.sandbox_command or self.sandbox_base_url)
            and self.preprocessor_adapter == "passthrough"
            and self.environment == "production"
        ):
            self.preprocessor_adapter = "sandbox"
        if self.environment == "production":
            self.require_gateway_identity = True
        return self

    @model_validator(mode="after")
    def production_must_not_use_dev_adapters(self) -> Settings:
        if self.environment == "production":
            if self.repository_adapter != "postgres" or not self.database_url:
                raise ValueError("production requires PostgreSQL repository configuration")
            if self.storage_adapter == "storage-service":
                if not self.storage_service_url or not self.storage_service_token:
                    raise ValueError("production storage-service requires URL and token")
            elif self.storage_adapter == "s3":
                if not self.s3_endpoint_url:
                    raise ValueError("production S3 adapter requires an endpoint")
            else:
                raise ValueError("production requires durable object storage")
            if self.engine_adapter != "paddleocr-vl" or not self.paddleocr_vl_base_url:
                raise ValueError("production requires the PaddleOCR-VL engine adapter")
            if self.preprocessor_adapter != "sandbox" or not (
                self.sandbox_exchange_dir or self.sandbox_command or self.sandbox_base_url
            ):
                raise ValueError("production requires the sandbox preprocessor")
            if not self.require_gateway_identity:
                raise ValueError("production must require gateway identity")
            if not self.api_key_pepper:
                raise ValueError("production requires API_KEY_PEPPER")
            if "change-me" in self.api_key_pepper.lower() or len(self.api_key_pepper) < 32:
                raise ValueError("production API_KEY_PEPPER must be a non-placeholder secret")
            if not self.logging_service_url or not self.logging_service_token:
                raise ValueError("production requires the logging service URL and token")
            if "change-me" in self.logging_service_token.lower() or len(self.logging_service_token) < 32:
                raise ValueError("production logging token must be a non-placeholder secret")
            if self.storage_adapter == "storage-service" and self.storage_service_token and (
                "change-me" in self.storage_service_token.lower()
                or len(self.storage_service_token) < 32
            ):
                raise ValueError("production storage token must be a non-placeholder secret")
            if not self.kafka_bootstrap_servers:
                raise ValueError("production requires Kafka brokers")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

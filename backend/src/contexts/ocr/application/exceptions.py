from __future__ import annotations

from src.shared.api import InternalStatusCode


class DependencyError(RuntimeError):
    """Expected dependency failure safe to expose through ``ApiEnvelope``.

    The original exception remains available through exception chaining for
    operators, while public responses and structured logs only use the stable
    status and reason below.
    """

    internal_code = InternalStatusCode.INTERNAL_CONTROLLED_ERROR
    error_reason = "dependency_unavailable"
    public_message = "依赖服务暂时不可用"


class DatabaseUnavailableError(DependencyError):
    internal_code = InternalStatusCode.DATABASE_UNAVAILABLE
    error_reason = "database_unavailable"
    public_message = "数据库暂时不可用"


class StorageUnavailableError(DependencyError):
    internal_code = InternalStatusCode.STORAGE_UNAVAILABLE
    error_reason = "storage_unavailable"
    public_message = "对象存储暂时不可用"


class QueueUnavailableError(DependencyError):
    internal_code = InternalStatusCode.QUEUE_UNAVAILABLE
    error_reason = "queue_unavailable"
    public_message = "消息队列暂时不可用"


class EngineError(DependencyError):
    """Base exception for OCR engine adapters."""

    internal_code = InternalStatusCode.ENGINE_UNAVAILABLE
    error_reason = "engine_unavailable"
    public_message = "OCR 引擎暂时不可用"


class TransientEngineError(EngineError):
    """An engine error that is safe to retry."""


class EngineUnavailableError(TransientEngineError):
    pass


class EngineTimeoutError(TransientEngineError):
    internal_code = InternalStatusCode.ENGINE_TIMEOUT
    error_reason = "engine_timeout"
    public_message = "OCR 引擎响应超时"


class EngineProtocolError(EngineError):
    error_reason = "engine_protocol_error"


class PreprocessingError(RuntimeError):
    pass


class ConcurrentJobUpdateError(RuntimeError):
    """A job snapshot lost an optimistic-lock race.

    This is a domain-level concurrency signal, not evidence that PostgreSQL is
    unavailable. Callers may reload the aggregate and resolve the newer state.
    """


class DuplicateIdempotencyKeyError(RuntimeError):
    """A concurrent request committed the same owner/idempotency key first."""

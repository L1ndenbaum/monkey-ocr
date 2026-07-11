from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from uuid6 import uuid7

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.config import Settings, get_settings
from src.container import AppContainer, create_memory_container, create_runtime_container
from src.contexts.ocr.application.exceptions import DependencyError
from src.contexts.ocr.interfaces.http.v1 import health_router, router
from src.shared.api import ApiEnvelope, InternalStatusCode
from src.shared.errors import BusinessError

logger = logging.getLogger("monkeyocr-backend")


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", request.headers.get("X-Request-ID", str(uuid7())))


def _json_response(envelope: ApiEnvelope[object], *, status_code: int) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=jsonable_encoder(envelope))


def create_app(
    *,
    settings: Settings | None = None,
    container: AppContainer | None = None,
) -> FastAPI:
    settings = settings or (container.settings if container else get_settings())

    provided_container = container

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        if provided_container is not None:
            application.state.container = provided_container
            yield
            return
        if settings.repository_adapter == "memory" and settings.storage_adapter == "memory":
            application.state.container = create_memory_container(settings)
            yield
            return
        async with create_runtime_container(settings) as runtime:
            application.state.container = runtime
            yield

    app = FastAPI(
        title="MonkeyOCR API",
        version="1.0.0",
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    if provided_container is not None:
        app.state.container = provided_container

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        candidate = request.headers.get("X-Request-ID", "")
        request.state.request_id = candidate[:128] if candidate else str(uuid7())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(BusinessError)
    async def business_error_handler(request: Request, exc: BusinessError) -> JSONResponse:
        return _json_response(
            ApiEnvelope.failure(
                exc.internal_code,
                message=exc.message,
                request_id=_request_id(request),
                error_reason=exc.error_reason,
                data=exc.data,
            ),
            status_code=200,
        )

    @app.exception_handler(DependencyError)
    async def dependency_error_handler(
        request: Request, exc: DependencyError
    ) -> JSONResponse:
        logger.warning(
            "expected backend dependency failure",
            extra={
                "request_id": _request_id(request),
                "internal_code": int(exc.internal_code),
                "internal_status_name": exc.internal_code.name,
                "error_reason": exc.error_reason,
                "error_type": type(exc).__name__,
            },
        )
        return _json_response(
            ApiEnvelope.failure(
                exc.internal_code,
                message=exc.public_message,
                request_id=_request_id(request),
                error_reason=exc.error_reason,
            ),
            status_code=200,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [
            {
                "location": [str(item) for item in error.get("loc", ())],
                "message": error.get("msg", "invalid value"),
                "type": error.get("type", "validation_error"),
            }
            for error in exc.errors()
        ]
        return _json_response(
            ApiEnvelope.failure(
                InternalStatusCode.COMMON_INVALID_ARGUMENT,
                message="请求参数无效",
                request_id=_request_id(request),
                error_reason="request_validation_failed",
                data={"errors": details},
            ),
            status_code=200,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _json_response(
            ApiEnvelope.failure(
                InternalStatusCode.COMMON_RESOURCE_NOT_FOUND,
                message="请求的接口或资源不存在",
                request_id=_request_id(request),
                error_reason="http_resource_not_found",
            ),
            status_code=200,
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "unhandled backend exception",
            extra={
                "request_id": _request_id(request),
                "internal_code": int(InternalStatusCode.TRANSPORT_INTERNAL_ERROR),
                "internal_status_name": InternalStatusCode.TRANSPORT_INTERNAL_ERROR.name,
            },
        )
        return _json_response(
            ApiEnvelope.failure(
                InternalStatusCode.TRANSPORT_INTERNAL_ERROR,
                message="服务未能形成正常响应",
                request_id=_request_id(request),
                error_reason="transport_internal_error",
            ),
            status_code=500,
        )

    app.include_router(router)
    app.include_router(health_router)

    original_openapi = app.openapi

    def constrained_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        schema = original_openapi()
        for path in schema.get("paths", {}).values():
            for operation in path.values():
                if isinstance(operation, dict) and "responses" in operation:
                    operation["responses"].pop("422", None)
        app.openapi_schema = schema
        return schema

    app.openapi = constrained_openapi
    return app


app = create_app()

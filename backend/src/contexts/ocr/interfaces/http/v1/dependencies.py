from __future__ import annotations

from typing import Annotated

from fastapi import Header, Request

from src.contexts.ocr.application.services import OCRApplicationService
from src.shared.api import InternalStatusCode
from src.shared.errors import BusinessError


async def get_service(request: Request) -> OCRApplicationService:
    return request.app.state.container.service


async def get_request_id(request: Request) -> str:
    return request.state.request_id


async def get_authenticated_owner_id(
    request: Request,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> str:
    settings = request.app.state.container.settings
    if authorization:
        scheme, separator, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not separator or not token:
            raise BusinessError(
                InternalStatusCode.USER_UNAUTHORIZED,
                "Authorization 必须使用 Bearer API Key",
                "invalid_authorization_scheme",
            )
        return await request.app.state.container.authenticator.authenticate(token)
    if settings.require_gateway_identity:
        raise BusinessError(
            InternalStatusCode.USER_UNAUTHORIZED,
            "缺少网关认证身份",
            "gateway_identity_missing",
        )
    return settings.dev_api_key_id

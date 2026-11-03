"""Consistent error contract. Never leak internals to clients."""
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

log = get_logger("errors")


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str = "", *, headers: dict[str, str] | None = None, **details: Any):
        super().__init__(message or self.code)
        self.message = message or self.code
        self.headers = headers
        self.details = details


class Unauthorized(AppError):
    status_code, code = 401, "unauthenticated"


class Forbidden(AppError):
    status_code, code = 403, "forbidden"


class NotFound(AppError):
    status_code, code = 404, "not_found"


class Conflict(AppError):
    status_code, code = 409, "conflict"


class PayloadTooLarge(AppError):
    status_code, code = 413, "payload_too_large"


class RateLimited(AppError):
    status_code, code = 429, "rate_limited"


class Unavailable(AppError):
    status_code, code = 503, "unavailable"


def _body(code: str, message: str, request: Request, **extra: Any) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "request_id": getattr(request.state, "request_id", None), **extra}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(_body(exc.code, exc.message, request, **exc.details), status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [{"loc": [str(p) for p in e["loc"]], "msg": e["msg"]} for e in exc.errors()]
        return JSONResponse(_body("validation_error", "Request validation failed", request, fields=fields), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(_body("http_error", str(exc.detail), request), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled_exception", exc_info=exc, extra={"path": request.url.path})
        return JSONResponse(_body("internal_error", "An internal error occurred", request), status_code=500)

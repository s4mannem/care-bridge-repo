"""One error shape for every failure: `{"error": {"code", "message", "request_id"}}`."""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from .middleware import request_id_var

log = logging.getLogger("carebridge.errors")


class GatewayError(Exception):
    """Raise from routes or runners for a failure the client should see as-is."""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code, self.code, self.message = status_code, code, message


def _body(code: str, message: str, request: Request) -> dict:
    rid = getattr(request.state, "request_id", None) or request_id_var.get()
    return {"error": {"code": code, "message": message, "request_id": rid}}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(GatewayError)
    async def _gateway(request: Request, exc: GatewayError):
        return JSONResponse(_body(exc.code, exc.message, request), status_code=exc.status_code)

    @app.exception_handler(HTTPException)
    async def _http(request: Request, exc: HTTPException):
        return JSONResponse(_body(f"http_{exc.status_code}", str(exc.detail), request), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        body = _body("invalid_request", "Request failed validation.", request)
        body["error"]["details"] = exc.errors()
        return JSONResponse(body, status_code=422)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.exception("unhandled error rid=%s", request_id_var.get())
        return JSONResponse(_body("internal_error", "Unexpected server error.", request), status_code=500)

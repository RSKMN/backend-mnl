import logging
from typing import Optional
from fastapi import Request, status
from fastapi.responses import JSONResponse
from app.core.responses import error_response

logger = logging.getLogger("qudrugforge-exceptions")

class AppException(Exception):
    """
    Custom application level exception class.
    Enables setting custom codes, messages, HTTP status codes, and context details.
    """
    def __init__(self, code: str, message: str, status_code: int = status.HTTP_400_BAD_REQUEST, details: Optional[any] = None):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)

async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """
    Catches custom AppExceptions and translates them into structured JSON error formats.
    """
    logger.warning(f"AppException caught on request {request.url.path}: [{exc.code}] {exc.message}")
    return error_response(
        code=exc.code,
        message=exc.message,
        details=exc.details,
        status_code=exc.status_code
    )

async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Catches all unexpected unhandled runtime exceptions, preventing leaks of server logs.
    """
    logger.exception(f"Unhandled Exception caught on request {request.url.path}: {str(exc)}")
    return error_response(
        code="INTERNAL_SERVER_ERROR",
        message="An unexpected system error occurred on the server.",
        details={"error_detail": str(exc)},
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
    )

from fastapi.exceptions import RequestValidationError

def _sanitize_pydantic_errors(errors: list) -> list:
    """
    Sanitize Pydantic v2 validation errors to ensure all values are JSON-serializable.
    Pydantic v2 stores the original exception in ctx['error'] as a Python exception
    object which is not JSON-serializable. Convert them to strings.
    """
    clean = []
    for err in errors:
        sanitized = {}
        for k, v in err.items():
            if k == "ctx" and isinstance(v, dict):
                sanitized[k] = {
                    ck: str(cv) if not isinstance(cv, (str, int, float, bool, type(None))) else cv
                    for ck, cv in v.items()
                }
            elif isinstance(v, (str, int, float, bool, list, dict, type(None))):
                sanitized[k] = v
            else:
                sanitized[k] = str(v)
        clean.append(sanitized)
    return clean

async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    logger.warning(f"RequestValidationError caught on request {request.url.path}")
    return error_response(
        code="VALIDATION_ERROR",
        message="Invalid request data.",
        details={"errors": _sanitize_pydantic_errors(exc.errors())},
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY
    )


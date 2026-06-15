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

class DomainError(Exception):
    def __init__(self, message: str, code: str, details: Optional[dict] = None, status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}
        self.status_code = status_code

class OrchestrationFailure(DomainError):
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, code="ORCHESTRATION_FAILURE", details=details, status_code=status.HTTP_502_BAD_GATEWAY)

class ComputeTimeout(DomainError):
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, code="COMPUTE_TIMEOUT", details=details, status_code=status.HTTP_408_REQUEST_TIMEOUT)

class MissingEvidenceError(DomainError):
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, code="MISSING_EVIDENCE", details=details, status_code=status.HTTP_404_NOT_FOUND)

class DependencyFailure(DomainError):
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, code="DEPENDENCY_FAILURE", details=details, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

async def domain_exception_handler(request: Request, exc: DomainError) -> JSONResponse:
    logger.warning(f"DomainError caught on request {request.url.path}: [{exc.code}] {exc.message}")
    return error_response(
        code=exc.code,
        message=exc.message,
        details=exc.details,
        status_code=exc.status_code
    )


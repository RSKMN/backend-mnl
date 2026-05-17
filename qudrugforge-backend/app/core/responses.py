from typing import Any, Optional
from fastapi.responses import JSONResponse
from fastapi import status

def success_response(data: Any = None, message: str = "Request completed") -> JSONResponse:
    """
    Constructs a standard structured API success response.
    
    Format:
    {
        "success": true,
        "data": { ... },
        "message": "Request completed"
    }
    """
    if data is None:
        data = {}
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "success": True,
            "data": data,
            "message": message
        }
    )

def error_response(code: str, message: str, details: Optional[Any] = None, status_code: int = status.HTTP_400_BAD_REQUEST) -> JSONResponse:
    """
    Constructs a standard structured API error response.
    
    Format:
    {
        "success": false,
        "error": {
            "code": "ERROR_CODE",
            "message": "Error description",
            "details": { ... }
        }
    }
    """
    if details is None:
        details = {}
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "error": {
                "code": code,
                "message": message,
                "details": details
            }
        }
    )

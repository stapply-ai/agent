"""
Global exception handlers.
"""

from datetime import datetime
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from .models import ErrorResponse


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """
    Global HTTP exception handler.

    Args:
        request: The request object
        exc: The HTTP exception

    Returns:
        JSONResponse: Formatted error response
    """
    error_response = ErrorResponse(
        error=exc.detail,
        detail=f"HTTP {exc.status_code} error occurred",
        timestamp=datetime.utcnow(),
    )
    return JSONResponse(
        status_code=exc.status_code, content=error_response.model_dump()
    )

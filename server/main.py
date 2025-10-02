"""
Agent Stapply cloud server
"""

from datetime import datetime
from typing import Dict, Any

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


# Pydantic models for type safety
class HealthResponse(BaseModel):
    """Health check response model."""
    status: str = Field(..., description="Service status")
    timestamp: datetime = Field(..., description="Current timestamp")
    version: str = Field(..., description="API version")


class ErrorResponse(BaseModel):
    """Error response model."""
    error: str = Field(..., description="Error message")
    detail: str = Field(..., description="Error details")
    timestamp: datetime = Field(..., description="Error timestamp")


# FastAPI application instance
app = FastAPI(
    title="StApply AI Agent API",
    description="A FastAPI server with type safety and best practices",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS middleware configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Health Check",
    description="Check if the service is running and healthy",
    tags=["Health"]
)
async def health_check() -> HealthResponse:
    """
    Health check endpoint.
    
    Returns:
        HealthResponse: Service health status with timestamp and version
    """
    return HealthResponse(
        status="healthy",
        timestamp=datetime.utcnow(),
        version="1.0.0"
    )


@app.get(
    "/",
    summary="Root Endpoint",
    description="Welcome message and API information",
    tags=["General"]
)
async def root() -> Dict[str, Any]:
    """
    Root endpoint with API information.
    
    Returns:
        Dict containing welcome message and API info
    """
    return {
        "message": "Welcome to StApply AI Agent API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health"
    }


# Global exception handler
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException) -> ErrorResponse:
    """
    Global HTTP exception handler.
    
    Args:
        request: The request object
        exc: The HTTP exception
        
    Returns:
        ErrorResponse: Formatted error response
    """
    return ErrorResponse(
        error=exc.detail,
        detail=f"HTTP {exc.status_code} error occurred",
        timestamp=datetime.utcnow()
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )

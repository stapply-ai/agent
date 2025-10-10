"""
Health check endpoint.
"""

from datetime import datetime
from fastapi import APIRouter, status
from .models import HealthResponse

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Health Check",
    description="Check if the service is running and healthy",
    tags=["Health"],
)
async def health_check() -> HealthResponse:
    """
    Health check endpoint.

    Returns:
        HealthResponse: Service health status with timestamp and version
    """
    return HealthResponse(
        status="healthy", timestamp=datetime.utcnow(), version="1.0.0"
    )

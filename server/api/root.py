"""
Root endpoint.
"""

from typing import Dict, Any
from fastapi import APIRouter

router = APIRouter()

@router.get(
    "/",
    summary="Root Endpoint",
    description="Welcome message and API information",
    tags=["General"],
)
async def root() -> Dict[str, Any]:
    """
    Root endpoint with API information.

    Returns:
        Dict containing welcome message and API info
    """
    return {
        "message": "Welcome to Agent Stapply cloud server",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }

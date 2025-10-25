"""
Health check endpoint.
"""

import time
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, status
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get(
    "/health",
    status_code=status.HTTP_200_OK,
    summary="Health Check",
    description="Check if the service is running and healthy",
    tags=["Health"],
    response_class=HTMLResponse,
)
async def health_check() -> str:
    """
    Health check endpoint with visual dashboard.

    Returns:
        HTML page with service health status
    """
    start_time = time.time()
    
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    status_value = "Healthy"
    version = "1.0.0"
    
    response_time = round((time.time() - start_time) * 1000, 2)
    
    html_path = Path(__file__).parent / "templates" / "health.html"
    html_content = html_path.read_text()
    
    html_content = html_content.replace("{{ status }}", status_value)
    html_content = html_content.replace("{{ version }}", version)
    html_content = html_content.replace("{{ timestamp }}", timestamp)
    html_content = html_content.replace("{{ response_time }}", str(response_time))
    
    return html_content

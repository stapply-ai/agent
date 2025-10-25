"""
Root endpoint.
"""

from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

@router.get(
    "/",
    summary="Root Endpoint",
    description="Welcome page and API information",
    tags=["General"],
    response_class=HTMLResponse,
)
async def root() -> str:
    """
    Root endpoint with API home page.

    Returns:
        HTML page with API information
    """
    html_path = Path(__file__).parent / "templates" / "home.html"
    return html_path.read_text()

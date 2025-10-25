"""
Documentation endpoint.
"""

from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get(
    "/docs",
    summary="API Documentation",
    description="Interactive API documentation",
    tags=["General"],
    response_class=HTMLResponse,
)
async def docs() -> str:
    """
    API documentation page.

    Returns:
        HTML page with comprehensive API documentation
    """
    html_path = Path(__file__).parent / "templates" / "docs.html"
    return html_path.read_text()

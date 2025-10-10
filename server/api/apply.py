"""
Apply endpoint for job application agent.
"""

from datetime import datetime
from typing import Dict, Any
from fastapi import APIRouter, HTTPException, status
from utils.profile import default_profile
from utils.browser import start_agent
from .models import ApplyRequest

router = APIRouter()


@router.post(
    "/apply",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start job application agent",
    description="Launches the autonomous agent to apply using provided data",
    tags=["Agent"],
)
async def apply(request: ApplyRequest) -> Dict[str, Any]:
    """
    Start the async agent run to perform the application flow.

    Returns a simple status payload after the agent completes.
    """
    try:
        profile_data: Dict[str, Any] = request.profile or default_profile 

        await start_agent(
            user_id=request.user_id,
            url=request.url,
            profile=profile_data,
            resume_url=request.resume_url,
            instructions=request.instructions,
            secrets=request.secrets,
        )

        return {
            "status": "completed",
            "timestamp": datetime.utcnow(),
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start agent: {e}",
        )

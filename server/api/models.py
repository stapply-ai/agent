"""
Pydantic models for type safety.
"""

from datetime import datetime
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field, field_serializer


class HealthResponse(BaseModel):
    """Health check response model."""

    status: str = Field(..., description="Service status")
    timestamp: datetime = Field(..., description="Current timestamp")
    version: str = Field(..., description="API version")

    @field_serializer("timestamp")
    def serialize_timestamp(self, value: datetime) -> str:
        return value.isoformat()


class ErrorResponse(BaseModel):
    """Error response model."""

    error: str = Field(..., description="Error message")
    detail: str = Field(..., description="Error details")
    timestamp: datetime = Field(..., description="Error timestamp")

    @field_serializer("timestamp")
    def serialize_timestamp(self, value: datetime) -> str:
        return value.isoformat()


class ApplyRequest(BaseModel):
    """Request body for starting the agent application flow."""

    user_id: str = Field(..., description="User ID")
    url: str = Field(..., description="Target URL to apply to")
    profile: Optional[Dict[str, Any]] = Field(
        default=None, description="Profile data used to fill forms"
    )
    resume_url: str = Field(..., description="URL to the resume file")
    instructions: Optional[str] = Field(
        default=None, description="Additional instructions for the agent"
    )
    secrets: Optional[Dict[str, Any]] = Field(
        default=None, description="Sensitive data to pass to the agent"
    )
    webhook_url: Optional[str] = Field(
        default="http://localhost:3000/webhook/applications",
        description="Webhook URL to notify when agent completes",
    )
    model: Optional[str] = Field(
        default=None, 
        description="Custom LLM model to use for the agent. Format varies by provider: "
                    "openai: 'openai/model-name' (e.g., 'openai/gpt-4'), "
                    "google: 'google/model-name' (e.g., 'google/gemini-pro'), "
                    "groq: 'groq/provider/model-name' (e.g., 'groq/anthropic/claude-3.5-sonnet'). "
                    "If not specified, uses default model."
    )

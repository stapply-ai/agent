"""
Middleware for request validation and security.
"""

import os
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware


class OriginCheckMiddleware(BaseHTTPMiddleware):
    """
    Middleware to restrict API access based on origin in production.
    In production, only allows requests from cloud.stapply.ai.
    In development, allows all origins.
    """

    def __init__(self, app):
        super().__init__(app)
        self.env = os.getenv("ENVIRONMENT", "development").lower()
        self.allowed_origins = [
            "https://cloud.stapply.ai",
            "http://cloud.stapply.ai",
        ]

    async def dispatch(self, request: Request, call_next):
        # Skip origin check in development
        if self.env != "production":
            return await call_next(request)

        # Skip origin check for public endpoints
        if request.url.path in ["/", "/health", "/docs"]:
            return await call_next(request)

        # Check Origin or Referer header
        origin = request.headers.get("origin")
        referer = request.headers.get("referer")

        # Allow requests without origin/referer (e.g., server-to-server)
        # but only if they have proper authentication
        if not origin and not referer:
            # In production, we might want to require authentication here
            # For now, we'll allow it but log a warning
            print(f"⚠️  Request to {request.url.path} has no origin/referer header")
            return await call_next(request)

        # Check if origin or referer matches allowed origins
        allowed = False
        if origin:
            for allowed_origin in self.allowed_origins:
                if origin.startswith(allowed_origin):
                    allowed = True
                    break

        if not allowed and referer:
            for allowed_origin in self.allowed_origins:
                if referer.startswith(allowed_origin):
                    allowed = True
                    break

        if not allowed:
            print(
                f"🚫 Blocked request from unauthorized origin: {origin or referer}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: unauthorized origin",
            )

        return await call_next(request)

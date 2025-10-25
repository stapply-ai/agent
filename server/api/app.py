"""
FastAPI application instance with all endpoints registered.
"""

import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import health, root, apply, docs, exception_handlers
from .middleware import OriginCheckMiddleware

# FastAPI application instance
app = FastAPI(
    title="Agent Stapply API",
    description="Agent Stapply API",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# Environment-aware CORS configuration
env = os.getenv("ENVIRONMENT", "development").lower()
if env == "production":
    # Restrict to cloud.stapply.ai in production
    allowed_origins = [
        "https://cloud.stapply.ai",
        "http://cloud.stapply.ai",
    ]
else:
    # Allow all origins in development
    allowed_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add origin check middleware for production
app.add_middleware(OriginCheckMiddleware)

# Register routers
app.include_router(root.router)
app.include_router(health.router)
app.include_router(docs.router)
app.include_router(apply.router)

# Register exception handlers
app.add_exception_handler(HTTPException, exception_handlers.http_exception_handler)

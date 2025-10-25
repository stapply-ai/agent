"""
FastAPI application instance with all endpoints registered.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import health, root, apply, exception_handlers

# FastAPI application instance
app = FastAPI(
    title="Agent Stapply API",
    description="Agent Stapply API",
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

# Register routers
app.include_router(root.router)
app.include_router(health.router)
app.include_router(apply.router)

# Register exception handlers
app.add_exception_handler(HTTPException, exception_handlers.http_exception_handler)

"""
Agent Stapply cloud server - Entry point
"""

from .api.app import app

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")

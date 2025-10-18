# Stapply AI Agent

This codebase contains the code to run an eval with the agent and the server that powers the cloud platform of Stapply.

To run: `uv run python -m server.main`.

## Setup

### Prerequisites

- Python 3.8+
- uv (Rust-based Python package manager)

Install uv (macOS/Linux):
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```
On Windows (PowerShell):
```powershell
irm https://astral.sh/uv/install.ps1 | iex
```

### Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd stapply-ai/agent
```

2. Create and activate a virtual environment with uv:
```bash
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

3. Install dependencies (from `pyproject.toml`):
```bash
uv sync
```

4. Install Playwright browser dependencies (first-time only):
```bash
uv run playwright install chromium
```

## Running the Server

### Development Mode

```bash
uv run python server/main.py
```

The server will start on `http://localhost:8000`

### Using Uvicorn directly

```bash
uv run uvicorn server.main:app --reload --host 0.0.0.0 --port 8000
```

## API Documentation

Once the server is running, you can access:

- **Interactive API docs (Swagger UI)**: http://localhost:8000/docs
- **Alternative API docs (ReDoc)**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/openapi.json

## Development

### Code Structure

```
server/
├── main.py              # Main FastAPI application
└── __init__.py          # Python package marker

pyproject.toml          # Project metadata and dependencies (managed by uv)
README.md               # This file
```

## License

See LICENSE file for details.
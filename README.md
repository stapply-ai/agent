# StApply AI Agent

This codebase contains the code to run an eval with the agent and the server that powers the cloud platform of Stapply.

## Setup

### Prerequisites

- Python 3.8+
- pip or uv

### Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd stapply-ai/agent
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

## Running the Server

### Development Mode

```bash
cd server
python main.py
```

The server will start on `http://localhost:8000`

### Using Uvicorn directly

```bash
cd server
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## API Documentation

Once the server is running, you can access:

- **Interactive API docs (Swagger UI)**: http://localhost:8000/docs
- **Alternative API docs (ReDoc)**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/openapi.json

## Available Endpoints

### Health Check
- **GET** `/health` - Check service health status

### General
- **GET** `/` - Root endpoint with API information

## API Response Examples

### Health Check Response
```json
{
  "status": "healthy",
  "timestamp": "2024-01-01T12:00:00.000000",
  "version": "1.0.0"
}
```

### Root Endpoint Response
```json
{
  "message": "Welcome to StApply AI Agent API",
  "version": "1.0.0",
  "docs": "/docs",
  "health": "/health"
}
```

## Development

### Code Structure

```
server/
├── main.py              # Main FastAPI application
└── __init__.py          # Python package marker

requirements.txt         # Python dependencies
README.md               # This file
```

### Type Safety

The API uses Pydantic models for request/response validation and type safety:

- `HealthResponse`: Health check response model
- `ErrorResponse`: Error response model

All endpoints include proper type hints and return models.

### Best Practices Implemented

- ✅ Comprehensive type hints
- ✅ Pydantic models for data validation
- ✅ Proper HTTP status codes
- ✅ CORS middleware configuration
- ✅ Global exception handling
- ✅ API documentation with descriptions
- ✅ Environment configuration ready
- ✅ Structured project layout

## Contributing

1. Follow PEP 8 style guidelines
2. Add type hints to all functions
3. Use Pydantic models for data validation
4. Update documentation for new endpoints
5. Test your changes

## License

See LICENSE file for details.
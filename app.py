"""FastAPI application — routes and server entry point."""

import os

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from config import BackendRegistry
from gateway import (
    BackendJSONError,
    normalize_request_body,
    resolve_request_id,
    validate_request_body,
)

_BACKEND_ERROR = {"error": "backend_error"}

app = FastAPI(title="Inference Gateway")
registry = BackendRegistry.from_config()

PORT = int(os.environ.get("PORT", "8080"))


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------


@app.exception_handler(httpx.HTTPStatusError)
async def backend_http_error(_request: Request, exc: httpx.HTTPStatusError):
    return JSONResponse(status_code=502, content=_BACKEND_ERROR)


@app.exception_handler(httpx.ConnectError)
async def backend_connect_error(_request: Request, exc: httpx.ConnectError):
    return JSONResponse(status_code=502, content={"error": "backend_unavailable"})


@app.exception_handler(httpx.TimeoutException)
async def backend_timeout(_request: Request, exc: httpx.TimeoutException):
    return JSONResponse(status_code=504, content={"error": "gateway_timeout"})


@app.exception_handler(httpx.ReadError)
async def backend_read_error(_request: Request, exc: httpx.ReadError):
    return JSONResponse(status_code=502, content=_BACKEND_ERROR)


@app.exception_handler(httpx.WriteError)
async def backend_write_error(_request: Request, exc: httpx.WriteError):
    return JSONResponse(status_code=502, content=_BACKEND_ERROR)


@app.exception_handler(BackendJSONError)
async def backend_json_error(_request: Request, exc: BackendJSONError):
    return JSONResponse(status_code=502, content=_BACKEND_ERROR)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": b.name,
                "object": "model",
                "created": 0,
                "owned_by": "inference-gateway",
            }
            for b in registry.list_backends()
        ],
    }


@app.get("/v1/backends")
async def get_backends():
    default = registry.get_default()
    return {
        "backends": [
            {
                "name": b.name,
                "type": b.type,
                "default": b is default,
            }
            for b in registry.list_backends()
        ],
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    error = validate_request_body(body)
    if error:
        return JSONResponse(error, status_code=400)
    body = normalize_request_body(body)
    headers = {k.lower(): v for k, v in request.headers.items()}
    request_id = resolve_request_id(headers)
    stream = body["stream"]

    model = body.get("model")
    known = {b.name for b in registry.list_backends()}
    backend = (
        registry.get(model) if model and model in known else registry.get_default()
    )

    result = await backend.generate(body, request_id, stream)
    if stream:
        return StreamingResponse(
            result,
            media_type="text/event-stream",
            headers={"X-Request-ID": request_id},
        )
    return JSONResponse(result, headers={"X-Request-ID": request_id})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)

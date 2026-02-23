"""FastAPI application — routes and server entry point."""

import os

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from gateway import (
    BACKEND_URL,
    BackendJSONError,
    build_response,
    echo_response,
    echo_stream,
    extract_prompt,
    forward_to_backend,
    resolve_request_id,
)

app = FastAPI(title="Inference Gateway")

PORT = int(os.environ.get("PORT", "8080"))


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------

@app.exception_handler(httpx.HTTPStatusError)
async def backend_http_error(_request: Request, exc: httpx.HTTPStatusError):
    return JSONResponse(
        status_code=502,
        content={"error": f"Backend error: {exc.response.status_code}"},
    )


@app.exception_handler(httpx.ConnectError)
async def backend_connect_error(_request: Request, exc: httpx.ConnectError):
    return JSONResponse(
        status_code=502,
        content={"error": f"Backend connection failed: {exc}"},
    )


@app.exception_handler(httpx.TimeoutException)
async def backend_timeout(_request: Request, exc: httpx.TimeoutException):
    return JSONResponse(
        status_code=504,
        content={"error": "Backend request timed out"},
    )


@app.exception_handler(httpx.ReadError)
async def backend_read_error(_request: Request, exc: httpx.ReadError):
    return JSONResponse(
        status_code=502,
        content={"error": f"Backend read failed: {exc}"},
    )


@app.exception_handler(httpx.WriteError)
async def backend_write_error(_request: Request, exc: httpx.WriteError):
    return JSONResponse(
        status_code=502,
        content={"error": f"Backend write failed: {exc}"},
    )


@app.exception_handler(BackendJSONError)
async def backend_json_error(_request: Request, exc: BackendJSONError):
    return JSONResponse(
        status_code=502,
        content={"error": "Backend returned non-JSON response"},
    )


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
                "id": "echo",
                "object": "model",
                "created": 0,
                "owned_by": "inference-gateway",
            }
        ],
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    headers = {k.lower(): v for k, v in request.headers.items()}
    request_id = resolve_request_id(headers)
    stream = body.get("stream", False)

    # Echo mode (no BACKEND_URL configured)
    if not BACKEND_URL:
        prompt = extract_prompt(body)
        if stream:
            return StreamingResponse(
                echo_stream(prompt, request_id),
                media_type="text/event-stream",
                headers={"X-Request-ID": request_id},
            )
        content = echo_response(prompt)
        resp = build_response(request_id, content, prompt)
        return JSONResponse(resp, headers={"X-Request-ID": request_id})

    # Backend forwarding mode
    result = await forward_to_backend(body, request_id, stream)
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

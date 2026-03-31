"""FastAPI application — routes and server entry point."""

from dotenv import load_dotenv

load_dotenv()

import os
import time

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from config import BackendRegistry
from cost import compute_cost
from gateway import (
    BackendJSONError,
    normalize_request_body,
    resolve_request_id,
    validate_request_body,
)
from metrics import (
    get_metrics_summary,
    record_request_metrics,
    record_streaming_metrics,
    start_metrics_server,
)
from technique import resolve_engine_backend, resolve_technique
from tracing import setup_tracing

_BACKEND_ERROR = {"error": "backend_error"}

app = FastAPI(title="Inference Gateway")
setup_tracing(app)
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


@app.get("/health")
async def health():
    results = []
    for b in registry.list_backends():
        check = await b.health_check()
        results.append({"name": b.name, "type": b.type, **check})
    ok_count = sum(1 for r in results if r["status"] == "ok")
    if ok_count == len(results):
        status = "healthy"
    elif ok_count > 0:
        status = "degraded"
    else:
        status = "unhealthy"
    return {"status": status, "backends": results}


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


@app.get("/metrics/summary")
async def metrics_summary():
    return get_metrics_summary()


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


async def _instrumented_stream(generator, technique: str, start_time: float):
    """Wrap a streaming generator to record TTFT and inter-chunk timing."""
    ttft = None
    chunk_delays: list[float] = []
    last_chunk_time = start_time
    async for chunk in generator:
        now = time.perf_counter()
        if ttft is None:
            ttft = now - start_time
        else:
            chunk_delays.append(now - last_chunk_time)
        last_chunk_time = now
        yield chunk
    duration = time.perf_counter() - start_time
    record_streaming_metrics(technique, duration, ttft=ttft, chunk_delays=chunk_delays)


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    start_time = time.perf_counter()
    body = await request.json()
    error = validate_request_body(body)
    if error:
        return JSONResponse(error, status_code=400)
    body = normalize_request_body(body)
    headers = {k.lower(): v for k, v in request.headers.items()}
    request_id = resolve_request_id(headers)
    technique = resolve_technique(headers, body)
    stream = body["stream"]

    # Engine routing override (env-var driven), then normal registry lookup
    engine_backend = resolve_engine_backend(technique, registry)
    if engine_backend:
        backend = engine_backend
    else:
        model = body.get("model")
        known = {b.name for b in registry.list_backends()}
        backend = (
            registry.get(model) if model and model in known else registry.get_default()
        )

    resp_headers = {"X-Request-ID": request_id, "X-Technique": technique}

    try:
        result = await backend.generate(body, request_id, stream)
    except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException,
            httpx.ReadError, httpx.WriteError, BackendJSONError):
        fallback = registry.get_fallback()
        if fallback is None or fallback is backend:
            raise
        result = await fallback.generate(body, request_id, stream)
        duration = time.perf_counter() - start_time
        if stream:
            return StreamingResponse(
                _instrumented_stream(result, technique, start_time),
                media_type="text/event-stream",
                headers={**resp_headers, "X-Fallback": "true"},
            )
        usage = result.get("usage", {})
        record_request_metrics(
            technique, duration,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            cost_usd=compute_cost(duration),
        )
        result["fallback"] = True
        return JSONResponse(result, headers={**resp_headers, "X-Fallback": "true"})

    if stream:
        return StreamingResponse(
            _instrumented_stream(result, technique, start_time),
            media_type="text/event-stream",
            headers=resp_headers,
        )
    duration = time.perf_counter() - start_time
    usage = result.get("usage", {}) if isinstance(result, dict) else {}
    record_request_metrics(
        technique, duration,
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
        cost_usd=compute_cost(duration),
    )
    return JSONResponse(result, headers=resp_headers)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    start_metrics_server()
    uvicorn.run(app, host="0.0.0.0", port=PORT)

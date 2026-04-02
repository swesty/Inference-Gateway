# Inference Gateway — Code Review & Architecture Analysis

**Date:** 2026-04-02
**Scope:** Full codebase review (~1,650 lines of Python across 17 files)

---

## Executive Summary

This is a well-structured, clean codebase with good separation of concerns and solid fundamentals. The architecture is appropriate for an inference proxy — stateless, async, pluggable backends. The issues below are ordered by impact. Most are in the "polish for production" category rather than fundamental design flaws.

---

## 1. Architecture & Design Patterns

### 1.1 GOOD: Clean Separation of Concerns

The `gateway.py` / `app.py` split is smart — pure validation/normalization logic lives framework-free in `gateway.py`, while `app.py` only handles HTTP plumbing. This makes the core logic trivially testable without FastAPI.

### 1.2 ISSUE: httpx Client Instantiation Per Request (High Impact)

**Files:** `backends/remote.py:47`, `backends/remote.py:63`, `backends/vllm.py:34`, `backends/vllm.py:49`

Every single request creates a new `httpx.AsyncClient`, establishes a new TCP connection, performs TLS handshake (for HTTPS backends), then tears it all down:

```python
# remote.py:47
async with httpx.AsyncClient(timeout=120) as client:
    resp = await client.post(url, json=body, headers=headers)
```

This is the single biggest performance issue in the codebase. For inference workloads where TTFT matters, you're paying ~1-5ms TCP + potentially 10-30ms TLS per request on top of actual inference latency. Under load, you'll also exhaust ephemeral ports and hit connection limits.

**Fix:** Create a shared `httpx.AsyncClient` per backend instance with connection pooling:

```python
class RemoteBackend(Backend):
    def __init__(self, name: str, url: str, type: str = "remote") -> None:
        super().__init__(name, type=type)
        self.url = url
        self._client = httpx.AsyncClient(
            timeout=120,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
```

Add a `close()` method and call it during shutdown. For `VllmBackend`, pass `verify=self.tls_verify` at client creation time.

### 1.3 ISSUE: Duplicated Forwarding Logic in VllmBackend (Medium Impact)

**Files:** `backends/vllm.py:29-58` vs `backends/remote.py:42-84`

`VllmBackend._forward()` and `_forward_stream()` are near-complete copies of `RemoteBackend`'s methods, differing only in `self._prepare_body(body)` and `verify=self.tls_verify`. This defeats the purpose of inheritance.

**Fix:** Add a hook in `RemoteBackend` for body preparation and pass client config through constructor:

```python
class RemoteBackend(Backend):
    def __init__(self, name, url, type="remote", verify=True):
        ...
        self._verify = verify

    def _prepare_body(self, body):
        return body  # override in subclass

    async def _forward(self, body, request_id):
        body = self._prepare_body(body)
        # ... use self._verify, shared client
```

Then `VllmBackend` only overrides `_prepare_body()` and sets `verify` in `__init__`. The current approach means every bug fix to forwarding logic must be applied twice.

### 1.4 ISSUE: Dead Code — `backends/RemoteBackend.py`

**File:** `backends/RemoteBackend.py` (entire file, 68 lines)

This is an old version of `remote.py` that uses a module-level `BACKEND_URL = os.environ.get("BACKEND_URL", "")` (line 12) and has a different `generate()` signature (`prompt: str` at line 17 vs `body: dict` in the active version). It's not imported anywhere and not exported from `backends/__init__.py`.

**Fix:** Delete `backends/RemoteBackend.py`. It's confusing to have two files implementing the same class.

### 1.5 ISSUE: Dead Code — `main.py`

**File:** `main.py` (6 lines)

```python
def main():
    print("Hello from inference-gateway!")
```

The actual entry point is `app.py`. This file is never used.

**Fix:** Delete `main.py` or make it the actual entry point that imports and runs `app.py`.

### 1.6 ISSUE: `gateway.py:8` — Hardcoded `MODEL_NAME = "echo"`

This constant is used in `build_response()` and `build_sse_chunk()` but only by `EchoBackend`. The value "echo" leaks into response objects regardless of which backend actually served the request. For `RemoteBackend`/`VllmBackend`, the upstream response already contains the correct model name, so this only affects the echo path. Still, it's a latent bug if you ever add another local backend.

**Fix:** Pass `model_name` as a parameter to `build_response()` and `build_sse_chunk()` instead of using a module-level constant.

### 1.7 ISSUE: Fallback Logic Code Duplication

**File:** `app.py:201-233` vs `app.py:235-258`

The fallback path (lines 210-233) duplicates almost all of the happy path (lines 235-258) — streaming response creation, metrics recording, and JSONL logging. The only difference is `X-Fallback: true` header and `result["fallback"] = True`.

**Fix:** Extract the response-building logic into a helper that takes `is_fallback: bool`:

```python
async def _build_chat_response(result, stream, technique, start_time, ...):
    ...
```

This removes ~20 lines of duplication and ensures metrics/logging stay consistent between paths.

---

## 2. Performance & Optimization

### 2.1 ISSUE: Synchronous File I/O in Async Handler (High Impact)

**File:** `request_logger.py:55-57`

```python
with open(filename, "a") as f:
    f.write(json.dumps(entry) + "\n")
    f.flush()
```

This is called from the async `chat_completions()` handler. `open()` + `write()` + `flush()` are blocking syscalls that will block the entire event loop. Under load with many concurrent requests, this serializes all request logging through the OS file I/O path.

**Fix:** Either:
- Use `aiofiles` for async I/O
- Offload to a background thread via `asyncio.to_thread()`
- Buffer writes and flush periodically (best for throughput)

### 2.2 ISSUE: `json.loads(VLLM_BACKEND_MAP_JSON)` on Every Request

**File:** `technique.py:57`

```python
map_json = os.environ.get("VLLM_BACKEND_MAP_JSON")
if map_json:
    mapping = json.loads(map_json)
```

`resolve_engine_backend()` is called for every request. It reads an env var and parses JSON every time. The env var doesn't change at runtime.

**Fix:** Parse once at module load or in a cached function:

```python
import functools

@functools.lru_cache(maxsize=1)
def _get_backend_map() -> dict | None:
    raw = os.environ.get("VLLM_BACKEND_MAP_JSON")
    return json.loads(raw) if raw else None
```

### 2.3 ISSUE: New VllmBackend Instance Per Routed Request

**File:** `technique.py:60`, `technique.py:72`

```python
return VllmBackend(f"engine-{technique}", url)
```

When engine routing is active, every request creates a brand-new `VllmBackend` instance. Combined with issue 1.2 (new httpx client per request), this means zero connection reuse across requests to the same engine.

**Fix:** Cache backend instances by URL:

```python
_engine_cache: dict[str, VllmBackend] = {}

def resolve_engine_backend(technique, registry):
    ...
    url = mapping.get(technique)
    if url:
        if url not in _engine_cache:
            _engine_cache[url] = VllmBackend(f"engine-{technique}", url)
        return _engine_cache[url]
```

### 2.4 ISSUE: `get_server_profile()` Called Repeatedly

**Files:** `app.py:145`, `app.py:163`, `app.py:227`, `app.py:253`, `metrics.py:89`, `metrics.py:111`, `metrics.py:124`

`get_server_profile()` does `os.environ.get()` on every call. It's called 2-3 times per request (metrics + logging + sometimes stream instrumentation). Env vars don't change at runtime.

**Fix:** Cache the result at module level or use `functools.lru_cache()`.

### 2.5 OBSERVATION: `count_tokens()` Heuristic

**File:** `gateway.py:104-106`

```python
def count_tokens(text: str) -> int:
    return max(1, len(text) // 4)
```

This is only used by `EchoBackend` via `build_response()`. Real backends return actual token counts from the model. The heuristic is fine for echo/testing, but document that it's intentionally approximate so no one tries to "fix" it.

### 2.6 ISSUE: Streaming Metrics Don't Track Token Counts

**File:** `app.py:166-167`

```python
prompt_tokens=0,
completion_tokens=0,
```

In `_instrumented_stream()`, token counts are hardcoded to 0. The stream wrapper doesn't parse SSE chunks to extract usage data. This means:
- `prompt_tokens_total` and `completion_tokens_total` counters are always 0 for streaming requests
- `completion_tokens_per_second` and `time_per_output_token` histograms are never populated for streaming
- Cost estimation for streaming requests is based purely on wall-clock time, not actual token usage

**Fix:** Parse the final SSE chunk (which typically contains usage data in OpenAI-compatible APIs) or accept this as a known limitation and document it. Many vLLM deployments include `usage` in the final streaming chunk — you could extract it there.

---

## 3. Error Handling & Resilience

### 3.1 ISSUE: Exception Handlers Swallow All Context (High Impact)

**Files:** `app.py:48-75`

```python
@app.exception_handler(httpx.HTTPStatusError)
async def backend_http_error(_request: Request, exc: httpx.HTTPStatusError):
    return JSONResponse(status_code=502, content=_BACKEND_ERROR)
```

All six exception handlers return a generic `{"error": "backend_error"}` or similar, with zero context about what actually failed. The original exception (which contains the backend URL, HTTP status, response body, etc.) is completely discarded. No logging occurs.

For an inference gateway where debugging backend issues is critical, this is a significant operational gap. When a vLLM backend returns a 422 (bad parameter) vs a 500 (OOM), the operator needs to know.

**Fix:** Log the exception and include safe context in the response:

```python
@app.exception_handler(httpx.HTTPStatusError)
async def backend_http_error(_request: Request, exc: httpx.HTTPStatusError):
    logger.error("Backend HTTP error: %s %s → %d", exc.request.method, exc.request.url, exc.response.status_code)
    return JSONResponse(status_code=502, content={
        "error": "backend_error",
        "upstream_status": exc.response.status_code,
    })
```

### 3.2 ISSUE: No Request Logging for Failed Requests

**File:** `app.py:175-258`

`req_logger.log()` is only called on the success path (lines 160-172 for streaming, lines 251-257 for non-streaming). When a request fails (4xx validation error or 5xx backend error), no JSONL log entry is created.

This means:
- Error rate can only be computed from Prometheus `requests_total` minus JSONL line counts
- No per-request forensics for failures
- `status_code` field in JSONL is always 200

**Fix:** Add a `finally` block or middleware that logs all requests, including failures:

```python
# In exception handlers, or via middleware:
req_logger.log(..., status_code=502)
```

### 3.3 ISSUE: `_instrumented_stream()` Silently Eats Generator Errors

**File:** `app.py:140-172`

If the backend generator raises an exception mid-stream (e.g., backend disconnects), the `async for chunk in generator` loop will propagate the exception, but:
- No metrics are recorded (lines 159 onwards never execute)
- No JSONL log entry is written
- The client sees a truncated SSE stream with no error indication

**Fix:** Wrap the generator loop in try/except/finally:

```python
async def _instrumented_stream(...):
    ttft = None
    chunk_delays = []
    last_chunk_time = start_time
    error = False
    try:
        async for chunk in generator:
            ...
            yield chunk
    except Exception:
        error = True
        raise
    finally:
        duration = time.perf_counter() - start_time
        record_streaming_metrics(technique, duration, ttft=ttft, chunk_delays=chunk_delays)
        req_logger.log(..., status_code=500 if error else 200)
```

### 3.4 ISSUE: No Timeout on `request.json()` Parsing

**File:** `app.py:178`

```python
body = await request.json()
```

If a client sends a `Content-Type: application/json` header but then slowly trickles body bytes, this will block the handler indefinitely (or until uvicorn's keep-alive timeout, which defaults to 5s for the header, but has no body timeout).

This is a minor concern since uvicorn has its own timeouts, but a malformed/enormous JSON body could cause high memory usage before validation rejects it.

**Fix:** Consider adding a request body size limit via middleware or FastAPI dependency.

### 3.5 ISSUE: Fallback Doesn't Catch Errors in Fallback

**File:** `app.py:208`

```python
result = await fallback.generate(body, request_id, stream)
```

If the fallback backend also fails, the exception propagates to the global exception handler, which returns a generic 502. The operator has no way to know that both primary and fallback failed.

**Fix:** Wrap the fallback call in its own try/except and log that both backends failed.

### 3.6 ISSUE: `lambda_pricing.py` — Bare `except Exception` Swallowing All Errors

**File:** `lambda_pricing.py:44`

```python
except Exception:
    pass
```

If the Lambda API returns unexpected JSON structure, or there's a DNS failure, or any other error — it's silently swallowed. The `_fetched = True` flag (set on line 23 before the try block) means it will never retry.

**Fix:** At minimum, log the error:

```python
except Exception as e:
    logger.warning("Failed to fetch Lambda pricing: %s", e)
```

---

## 4. Security

### 4.1 ISSUE: No Request Body Size Limit

**Files:** `app.py:178`, `monitoring/nginx-gateway-lb.conf` (`client_max_body_size 64m`)

The nginx config allows 64MB request bodies. A malicious client could send a 64MB JSON payload that gets parsed into memory, validated, normalized, and forwarded to the backend. With many concurrent requests, this is a memory exhaustion vector.

**Fix:** Add a FastAPI middleware that rejects bodies over a reasonable limit (e.g., 1MB for chat completions):

```python
@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    if request.headers.get("content-length", 0) > 1_000_000:
        return JSONResponse({"error": "request_too_large"}, status_code=413)
    return await call_next(request)
```

Also reduce `client_max_body_size` in nginx to match.

### 4.2 ISSUE: No Rate Limiting

There's no rate limiting at the gateway level. A single client can monopolize GPU resources by flooding requests. The nginx config has no `limit_req` directives either.

**Fix:** Add `limit_req_zone` in nginx config for basic rate limiting, or use a FastAPI middleware like `slowapi`.

### 4.3 ISSUE: No Authentication

The gateway is wide open — any client that can reach it can send inference requests. For a research/dev setup this is fine, but the deployment guides describe exposing this on cloud instances.

**Fix:** At minimum, add optional API key validation via a header check middleware that can be enabled via env var.

### 4.4 ISSUE: Technique Header Injection

**File:** `technique.py:28-30`

```python
header_val = headers.get("x-technique")
if header_val:
    return header_val
```

The `X-Technique` header value is used directly as a Prometheus label (`technique.py:28` → `metrics.py:90`). Prometheus labels with high cardinality (arbitrary user-supplied strings) can cause memory exhaustion in Prometheus.

**Fix:** Validate against a known set of techniques:

```python
KNOWN_TECHNIQUES = {"baseline", "beam_search", "chunked_prefill", "speculative"}

def resolve_technique(headers, body):
    header_val = headers.get("x-technique")
    if header_val and header_val in KNOWN_TECHNIQUES:
        return header_val
    ...
```

Or sanitize/normalize before using as a label.

### 4.5 OBSERVATION: `GF_SECURITY_ADMIN_PASSWORD=admin` in docker-compose.yml

**File:** `docker-compose.yml:42`

Hardcoded Grafana admin password. Acceptable for local dev, but the deployment docs should emphasize changing this.

---

## 5. Code Quality

### 5.1 ISSUE: No Logging Framework

The entire codebase has zero `logging` usage. There's structured JSONL for request metrics, but no operational logging — no startup messages, no error traces, no debug output. When something goes wrong in production, the only signal is the HTTP response code.

**Fix:** Add Python `logging` with structured output. At minimum, log:
- Startup: backend registry contents, port, config file used
- Errors: all exception handler invocations with context
- Warnings: fallback triggered, Lambda API failures, health check failures

### 5.2 ISSUE: `build_sse_chunk()` Imports `json` Inside Function Body

**File:** `gateway.py:140`

```python
def build_sse_chunk(...) -> str:
    import json
```

This is a deferred import inside a function that's called per-chunk during streaming. Python caches module imports, so the runtime cost is negligible after the first call, but it's unconventional and suggests the import was moved here accidentally.

**Fix:** Move `import json` to the top of `gateway.py`.

### 5.3 ISSUE: `_instrumented_stream()` Re-imports `get_server_profile`

**File:** `app.py:145`

```python
async def _instrumented_stream(...):
    from technique import get_server_profile
```

`get_server_profile` is already imported at module level on line 30. This inner import is unnecessary.

### 5.4 ISSUE: Inconsistent Return Type Annotations

**File:** `backends/remote.py:37`

```python
async def generate(self, body, request_id, stream=False) -> str | AsyncGenerator[str, None]:
```

The return type says `str | AsyncGenerator` but `_forward()` returns `dict[str, Any]` (line 42). The actual return is `dict | AsyncGenerator`, not `str | AsyncGenerator`.

**File:** `backends/backend.py:10`

```python
async def generate(self, body, request_id, stream=False) -> str | AsyncGenerator[str, None]:
    raise NotImplementedError
```

Same issue in the abstract base class — return type annotation says `str` but implementations return `dict`.

### 5.5 ISSUE: `get_metrics_summary()` Accesses Private Prometheus Internals

**File:** `metrics.py:129`, `metrics.py:135`

```python
req_count = REQUESTS_TOTAL.labels(**labels)._value.get()
REQUEST_DURATION.labels(**labels)._sum.get()
```

`_value` and `_sum` are private attributes of `prometheus_client` internals. These can break on library upgrades without notice.

**Fix:** Use the official `prometheus_client` API. For example, use `REQUESTS_TOTAL.labels(**labels)._value.get()` → `prometheus_client.generate_latest()` and parse, or use `CollectorRegistry.get_sample_value()`.

### 5.6 ISSUE: `get_metrics_summary()` Only Reports 4 Hardcoded Techniques

**File:** `metrics.py:127`

```python
for technique in ("baseline", "beam_search", "chunked_prefill", "speculative"):
```

If a user sends `X-Technique: custom_technique`, it gets recorded in Prometheus (issue 4.4) but never appears in the `/metrics/summary` endpoint.

---

## 6. Configuration & Deployment

### 6.1 ISSUE: No `.dockerignore`

**File:** (missing)

The Dockerfile's `COPY *.py ./` will copy `test_gateway.py` and `main.py` into the production image. `COPY backends/` will copy `RemoteBackend.py` (the dead code). Any `__pycache__/`, `.env`, `logs/`, or `.git/` in the build context also get sent to the Docker daemon, slowing builds.

**Fix:** Create `.dockerignore`:

```
__pycache__
*.pyc
.git
.env
.env.example
logs/
docs/
scripts/
workloads/
monitoring/
test_gateway.*
main.py
backends/RemoteBackend.py
.claude/
.mcp.json
```

### 6.2 ISSUE: Docker Image Runs as Root

**File:** `Dockerfile`

No `USER` directive. The process runs as root inside the container, which is a container escape risk.

**Fix:** Add:

```dockerfile
RUN useradd --create-home appuser
USER appuser
```

### 6.3 ISSUE: No Docker HEALTHCHECK

**File:** `Dockerfile`

No `HEALTHCHECK` instruction. Orchestrators (Docker Compose, ECS, K8s) can't automatically detect if the gateway is healthy.

**Fix:**

```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/healthz')"
```

### 6.4 ISSUE: `docker-compose.yml` — Unpinned Image Tags

**File:** `docker-compose.yml:27`, `docker-compose.yml:37`

```yaml
image: prom/prometheus:latest
image: grafana/grafana:latest
```

`latest` is mutable. Builds are non-reproducible and a Prometheus/Grafana upgrade could break the monitoring stack.

**Fix:** Pin to specific versions:

```yaml
image: prom/prometheus:v2.51.0
image: grafana/grafana:10.4.0
```

### 6.5 ISSUE: No Graceful Shutdown

**File:** `app.py:265-267`

```python
if __name__ == "__main__":
    start_metrics_server()
    uvicorn.run(app, host="0.0.0.0", port=PORT)
```

No signal handling, no shutdown hook. When a container receives SIGTERM:
- In-flight streaming responses are abruptly terminated
- httpx clients are not cleanly closed (if you fix issue 1.2 with persistent clients)
- Prometheus metrics server is not shut down

Uvicorn does handle SIGTERM for its own server, but the Prometheus metrics server (started via `start_http_server()`) runs in a daemon thread and doesn't get clean shutdown.

**Fix:** Use uvicorn's `on_shutdown` hook or FastAPI's `lifespan`:

```python
@asynccontextmanager
async def lifespan(app):
    start_metrics_server()
    yield
    # cleanup: close shared httpx clients, etc.

app = FastAPI(title="Inference Gateway", lifespan=lifespan)
```

### 6.6 ISSUE: `config.yaml` Loaded Relative to CWD

**File:** `config.py:48`

```python
config_path = Path(path) if path else Path("config.yaml")
```

Uses relative path. If the process is started from a different directory, it silently falls back to echo-only mode. This is a common source of "it works in dev but not in Docker" bugs (though the Dockerfile sets `WORKDIR /app` and copies `config.yaml` there, so it works today).

**Fix:** Resolve relative to the script's directory:

```python
config_path = Path(path) if path else Path(__file__).parent / "config.yaml"
```

---

## 7. Testing

### 7.1 ISSUE: No Test Framework — Custom Assert Functions

**File:** `test_gateway.py:18-35`

The test suite uses hand-rolled `assert_eq()` and `assert_contains()` with global mutable counters (`PASS`, `FAIL`). This means:
- No test isolation (a failure in test 5 doesn't prevent test 6 from running, but shared server state leaks between tests)
- No parameterization
- No fixtures
- No parallel execution
- No `-k` style test selection
- No coverage reporting

For 30 tests this is manageable, but it makes adding new tests tedious.

**Fix:** Migrate to `pytest` with `httpx.AsyncClient` + `pytest-asyncio`. The stdlib-only constraint seems intentional (no test deps in `pyproject.toml`), but `pytest` would pay for itself quickly.

### 7.2 ISSUE: Fallback Path is Completely Untested

**File:** `app.py:201-233`

The entire fallback retry block — lines 201-233 — is never exercised by any test. Test 18 (line 240) verifies that `get_fallback()` returns `None`, but never triggers the actual fallback code path where primary fails and fallback succeeds.

**Fix:** Add a test that:
1. Configures a config with a broken primary backend (e.g., `RemoteBackend` pointing to a closed port) and a fallback (`EchoBackend`)
2. Sends a request
3. Verifies `X-Fallback: true` header and `fallback: true` in response body

### 7.3 ISSUE: RemoteBackend and VllmBackend HTTP Behavior Untested

**Files:** `backends/remote.py`, `backends/vllm.py`

All tests use `EchoBackend`. The actual HTTP forwarding, error handling, stream parsing, TLS verification, and beam search injection in `RemoteBackend`/`VllmBackend` are never tested.

**Fix:** Use `pytest-httpx` or a simple async mock server to test:
- `_forward()` with 200, 500, timeout, and non-JSON responses
- `_forward_stream()` with proper SSE, mid-stream disconnect, and error responses
- `VllmBackend._prepare_body()` beam search injection
- TLS verify flag propagation

### 7.4 ISSUE: Exception Handlers Untested

**File:** `app.py:48-75`

All six exception handlers are untested. The test suite never triggers a backend error because `EchoBackend` never fails.

### 7.5 ISSUE: `lambda_pricing.py` Untested

**File:** `lambda_pricing.py` (entire module)

Zero test coverage. The Lambda API integration, JSON parsing, caching logic, and error handling are all untested.

### 7.6 OBSERVATION: Test Server Startup Race Condition

**File:** `test_gateway.py:73-78`

```python
for _ in range(30):
    try:
        urllib.request.urlopen(f"{BASE}/healthz")
        break
    except Exception:
        time.sleep(0.2)
```

The polling loop waits up to 6 seconds. If the server doesn't start in time, the tests silently proceed and all fail with connection errors. No explicit failure message if the server doesn't come up.

---

## 8. Dependencies

### 8.1 ISSUE: No Upper Bounds on Dependencies

**File:** `pyproject.toml:7-12`

```toml
"fastapi>=0.129.2",
"httpx>=0.28.1",
```

Only floor pins. A `fastapi>=1.0.0` or `httpx>=1.0.0` major version bump could introduce breaking changes. The `uv.lock` file provides reproducibility for direct builds, but anyone installing from the pyproject.toml without the lockfile gets unbounded versions.

### 8.2 ISSUE: No Test Dependencies Declared

**File:** `pyproject.toml`

No `[project.optional-dependencies] test = [...]` section. If you migrate to pytest (recommendation 7.1), declare test dependencies properly.

### 8.3 OBSERVATION: `uv` Pinned to `latest`

**File:** `Dockerfile:3`

```dockerfile
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
```

Same `latest` tag problem as the monitoring images. Pin to a specific version.

---

## 9. Priority Summary

### Critical (Fix Before Production)

| # | Issue | File | Impact |
|---|-------|------|--------|
| 1.2 | httpx client per request | `remote.py`, `vllm.py` | Latency + connection exhaustion |
| 3.1 | Exception handlers swallow context | `app.py:48-75` | Undebuggable production failures |
| 4.4 | Technique header → unbounded Prometheus labels | `technique.py:28` | Prometheus memory exhaustion |
| 5.1 | No logging framework | Entire codebase | Zero operational visibility |

### High (Fix Soon)

| # | Issue | File | Impact |
|---|-------|------|--------|
| 2.1 | Sync file I/O in async handler | `request_logger.py:55` | Event loop blocking under load |
| 2.3 | New VllmBackend per routed request | `technique.py:60,72` | No connection reuse |
| 3.2 | Failed requests not logged | `app.py` | Incomplete audit trail |
| 3.3 | Stream errors not recorded | `app.py:140-172` | Silent metric gaps |
| 4.1 | No request body size limit | `app.py:178` | Memory exhaustion vector |

### Medium (Improve)

| # | Issue | File | Impact |
|---|-------|------|--------|
| 1.3 | Duplicated forwarding logic | `vllm.py` | Maintenance burden |
| 1.4 | Dead code `RemoteBackend.py` | `backends/RemoteBackend.py` | Confusion |
| 1.7 | Fallback code duplication | `app.py:201-233` | Maintenance burden |
| 2.6 | Streaming: zero token counts | `app.py:166-167` | Incomplete metrics |
| 6.1 | No `.dockerignore` | (missing) | Bloated image, slow builds |
| 6.2 | Docker runs as root | `Dockerfile` | Security |
| 6.5 | No graceful shutdown | `app.py:265` | Dropped connections on deploy |
| 7.2 | Fallback path untested | Tests | Regression risk |
| 7.3 | RemoteBackend untested | Tests | Regression risk |

### Low (Nice to Have)

| # | Issue | File | Impact |
|---|-------|------|--------|
| 1.5 | Dead `main.py` | `main.py` | Clutter |
| 1.6 | Hardcoded MODEL_NAME | `gateway.py:8` | Latent bug |
| 2.2 | JSON parsed per request | `technique.py:57` | Micro-optimization |
| 2.4 | `get_server_profile()` uncached | Multiple | Micro-optimization |
| 5.2 | Inner `import json` | `gateway.py:140` | Style |
| 5.3 | Redundant inner import | `app.py:145` | Style |
| 5.4 | Wrong return type annotations | `backend.py`, `remote.py` | Type checker noise |
| 5.5 | Private Prometheus API usage | `metrics.py:129,135` | Fragile |
| 6.4 | Unpinned monitoring images | `docker-compose.yml` | Reproducibility |
| 6.6 | Config path relative to CWD | `config.py:48` | Portability |

---

## 10. What's Done Well

Credit where it's due — this codebase gets a lot right:

1. **Separation of concerns** — `gateway.py` is framework-free pure logic. Easy to test, easy to reason about.
2. **Async throughout** — No accidental blocking in the hot path (except the JSONL logging).
3. **Eager connect for streaming** — `remote.py:62-71` validates the connection before returning the generator to `StreamingResponse`. This prevents the common bug where streaming errors only surface after response headers are sent.
4. **Comprehensive observability** — Prometheus histograms, counters, JSONL logging, and optional OTEL tracing. The metric selection (TTFT, inter-chunk delay, tokens/sec) is exactly right for inference workloads.
5. **Technique/profile labeling** — The two-axis labeling (technique + server_profile) is well-designed for A/B testing inference configurations.
6. **Config validation** — `BackendRegistry.from_config()` validates all backend definitions upfront and fails fast with clear error messages.
7. **Flexible engine routing** — The three-tier routing (explicit JSON → auto port offset → registry lookup) covers the common deployment patterns well.
8. **Docker layer caching** — Dependencies first, then source. Rebuild only copies source on code changes.
9. **Clean abstractions** — The Backend hierarchy is minimal and extensible without over-engineering.
10. **Test coverage breadth** — 30 tests covering validation, normalization, routing, streaming, metrics, logging, and technique resolution is solid for a ~1,600 line codebase.

# Change Log & Insights

---

## Step 1 — Backend ABC + Echo & Remote Backends (Issue #6)

**Status:** Complete

**Files changed:**
- `backends/backend.py` — new, ABC with `generate()` contract
- `backends/echo.py` — new, `EchoBackend` wrapping echo logic from `gateway.py`
- `backends/remote.py` — new, `RemoteBackend` wrapping forward logic from `gateway.py`
- `backends/__init__.py` — new, re-exports

**Verification:** All 14 existing tests pass unchanged.

---

## Step 2 — Config-Driven Backend Registry (Issue #7)

**Status:** Complete

**Files changed:**
- `backends/backend.py` — added `__init__(self, name: str)` to ABC
- `backends/echo.py` — added `__init__` calling `super().__init__(name)`, defaults to `"echo"`
- `backends/remote.py` — updated `__init__` to call `super().__init__(name)` instead of storing `self.name` directly
- `pyproject.toml` / `uv.lock` — added `pyyaml` dependency
- `config.yaml` — new, default echo config with commented-out remote examples
- `config.py` — new, `BackendRegistry` with `from_config()`, `get()`, `get_default()`, `get_fallback()`, `list_backends()`

**Design decisions:**
- No env var overrides — YAML is the single source of truth for all config
- Backend type determines class: `echo` → `EchoBackend`, anything else with a `url` → `RemoteBackend`
- `type` field defaults to the backend's name if omitted
- Fail-fast validation: missing `url` on remote types or invalid `default_backend` raise `ValueError` at startup

**Verification:** Registry smoke test passes. All 14 existing tests pass.

### Insights

1. **`name` on the ABC** — Pushing shared state (`name`) into the base class creates a consistent identity contract. Every backend is addressable by name, which the registry needs for lookup. Subclasses can't forget to set it.

2. **Fail-fast config validation** — `from_config()` raises `ValueError` immediately for misconfiguration (missing URL, unknown default). This surfaces errors at boot time, not under load. For config-driven systems, startup is the right place to fail.

3. **Type field as a hook point** — The `type` field is informational today (any non-echo type with a URL becomes `RemoteBackend`), but it gives a natural extension point for specialized classes later (e.g., `VLLMBackend` in Step 7) without changing the config schema.

---

## Step 3 — Model Routing + Backend Metadata (Issues #8, #9)

**Status:** Complete

**Files changed:**
- `app.py` — replaced echo/remote branching with unified registry-based code path; `/v1/models` now dynamically lists all registered backends
- `backends/echo.py` — `generate()` now returns a full response dict (via `build_response()`) for non-streaming, matching `RemoteBackend`'s shape
- `gateway.py` — removed `BACKEND_URL`, `echo_response()`, `echo_stream()`, `forward_to_backend()`; removed model defaulting from `normalize_request_body()`; cleaned up unused imports (`os`, `AsyncGenerator`)
- `test_gateway.py` — removed `BACKEND_URL` env pop; added Test 15 (explicit model routing) and Test 16 (unknown model fallback)
- `README.md` — replaced `BACKEND_URL` docs with Configuration section; added Model Routing section; fixed error table to match actual error keys; updated validation table

**Design decisions:**
- Both backends return the same shape (dict for non-streaming, async generator for streaming) so `app.py` has one code path
- Unknown models fall back to `default_backend` rather than returning an error — graceful degradation over strict routing
- `/v1/models` was folded into this step (originally planned as Step 4 / Issue #9) since it was a one-line change once the registry existed
- No `"backend"` metadata field added to responses — kept it simple; can be added later if needed

**Verification:** 34/34 assertions pass across 16 tests (14 existing + 2 new routing tests).

### Insights

1. **Strategy Pattern payoff** — The two-branch if/else in `app.py` (echo vs. remote) collapsed into three lines: look up backend, call `generate()`, return result. The key enabler was making `EchoBackend.generate()` return the same dict shape as `RemoteBackend.generate()`. Polymorphism replaces conditionals.

2. **Adjacent features collapse** — Issue #9 (dynamic `/v1/models`) was planned as a separate step, but once the registry existed it was a one-line list comprehension. Good abstractions make nearby features trivial to add.

3. **Removing defaults at the right layer** — `normalize_request_body()` no longer defaults `model` to `"echo"`. Model resolution moved to the routing layer (`app.py`), where it belongs. Normalization should clean input, not make routing decisions.

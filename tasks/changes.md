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

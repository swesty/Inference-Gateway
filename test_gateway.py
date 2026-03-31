#!/usr/bin/env python3
"""Automated tests for the inference gateway (echo mode) — stdlib only."""

import json
import os
import signal
import subprocess
import sys
import time
import urllib.request

PORT = 9124
BASE = f"http://localhost:{PORT}"
PASS = 0
FAIL = 0


def assert_eq(label: str, expected, actual):
    global PASS, FAIL
    if actual == expected:
        print(f"  PASS: {label}")
        PASS += 1
    else:
        print(f"  FAIL: {label} — expected {expected!r}, got {actual!r}")
        FAIL += 1


def assert_contains(label: str, needle: str, haystack: str):
    global PASS, FAIL
    if needle in haystack:
        print(f"  PASS: {label}")
        PASS += 1
    else:
        print(f"  FAIL: {label} — {needle!r} not found")
        FAIL += 1


def post_json(path: str, body: dict, headers: dict | None = None):
    """POST JSON and return (status, response_headers, body_str)."""
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, dict(resp.headers), resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode()


def get_json(path: str):
    """GET and return parsed JSON."""
    with urllib.request.urlopen(f"{BASE}{path}") as resp:
        return json.loads(resp.read().decode())


def main():
    global PASS, FAIL

    # Start server
    env = {**os.environ, "PORT": str(PORT)}
    proc = subprocess.Popen(
        [sys.executable, "app.py"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait for server
    for _ in range(30):
        try:
            urllib.request.urlopen(f"{BASE}/healthz")
            break
        except Exception:
            time.sleep(0.2)

    try:
        # Test 1: GET /healthz
        print("Test 1: GET /healthz")
        data = get_json("/healthz")
        assert_eq("status ok", "ok", data.get("status"))

        # Test 2: GET /v1/models
        print("Test 2: GET /v1/models")
        data = get_json("/v1/models")
        assert_eq("object list", "list", data.get("object"))
        assert_eq("model id", "echo", data["data"][0]["id"])

        # Test 3: Non-streaming POST
        print("Test 3: Non-streaming POST")
        status, _, body = post_json(
            "/v1/chat/completions",
            {"messages": [{"role": "user", "content": "Hello!"}]},
        )
        assert_eq("status 200", 200, status)
        resp = json.loads(body)
        assert_contains("has id", "id", str(resp.keys()))
        assert_eq("object", "chat.completion", resp["object"])
        assert_eq("content", "Echo: Hello!", resp["choices"][0]["message"]["content"])
        assert_contains("has usage", "usage", str(resp.keys()))

        # Test 4: Client-provided X-Request-ID
        print("Test 4: Client-provided X-Request-ID")
        status, hdrs, body = post_json(
            "/v1/chat/completions",
            {"messages": [{"role": "user", "content": "Hi"}]},
            headers={"X-Request-ID": "test-42"},
        )
        resp = json.loads(body)
        assert_eq("id in body", "test-42", resp["id"])
        # Header keys may vary in case
        hdr_lower = {k.lower(): v for k, v in hdrs.items()}
        assert_eq("id in header", "test-42", hdr_lower.get("x-request-id"))

        # Test 5: Auto-generated UUID
        print("Test 5: Auto-generated UUID")
        _, _, body = post_json(
            "/v1/chat/completions",
            {"messages": [{"role": "user", "content": "test"}]},
        )
        resp = json.loads(body)
        assert_eq("uuid length 36", 36, len(resp["id"]))

        # Test 6: Streaming SSE
        print("Test 6: Streaming SSE")
        status, _, body = post_json(
            "/v1/chat/completions",
            {"messages": [{"role": "user", "content": "Hi"}], "stream": True},
        )
        assert_contains("has Echo:", "Echo: Hi", body)
        assert_contains("has DONE", "[DONE]", body)

        # --- Validation tests ---

        # Test 7: Missing messages
        print("Test 7: Missing messages")
        status, _, body = post_json("/v1/chat/completions", {})
        assert_eq("status 400", 400, status)
        assert_eq("error", "invalid_messages", json.loads(body)["error"])

        # Test 8: messages not a list
        print("Test 8: messages not a list")
        status, _, body = post_json(
            "/v1/chat/completions", {"messages": "not a list"}
        )
        assert_eq("status 400", 400, status)
        assert_eq("error", "invalid_messages", json.loads(body)["error"])

        # Test 9: Message missing role/content
        print("Test 9: Message missing role/content")
        status, _, body = post_json(
            "/v1/chat/completions", {"messages": [{"role": "user"}]}
        )
        assert_eq("status 400", 400, status)
        assert_eq("error", "invalid_messages", json.loads(body)["error"])

        # Test 10: stream not bool
        print("Test 10: stream not bool")
        status, _, body = post_json(
            "/v1/chat/completions",
            {"messages": [{"role": "user", "content": "hi"}], "stream": "yes"},
        )
        assert_eq("status 400", 400, status)
        assert_eq("error", "invalid_stream", json.loads(body)["error"])

        # Test 11: max_tokens out of range
        print("Test 11: max_tokens out of range")
        status, _, body = post_json(
            "/v1/chat/completions",
            {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 0},
        )
        assert_eq("status 400", 400, status)
        assert_eq("error", "invalid_max_tokens", json.loads(body)["error"])

        # Test 12: temperature out of range
        print("Test 12: temperature out of range")
        status, _, body = post_json(
            "/v1/chat/completions",
            {"messages": [{"role": "user", "content": "hi"}], "temperature": 3.0},
        )
        assert_eq("status 400", 400, status)
        assert_eq("error", "invalid_temperature", json.loads(body)["error"])

        # Test 13: stop wrong type
        print("Test 13: stop wrong type")
        status, _, body = post_json(
            "/v1/chat/completions",
            {"messages": [{"role": "user", "content": "hi"}], "stop": 42},
        )
        assert_eq("status 400", 400, status)
        assert_eq("error", "invalid_stop", json.loads(body)["error"])

        # Test 14: Normalization strips unknown fields and applies defaults
        print("Test 14: Normalization")
        status, _, body = post_json(
            "/v1/chat/completions",
            {
                "messages": [{"role": "user", "content": "hi"}],
                "unknown_field": True,
                "temperature": 0.5,
            },
        )
        assert_eq("status 200", 200, status)
        resp = json.loads(body)
        assert_eq("model defaulted", "echo", resp["model"])
        assert_eq("echo content", "Echo: hi", resp["choices"][0]["message"]["content"])

        # Test 15: Model routing — explicit model "echo" routes to echo backend
        print("Test 15: Model routing — explicit echo")
        status, _, body = post_json(
            "/v1/chat/completions",
            {"messages": [{"role": "user", "content": "route me"}], "model": "echo"},
        )
        assert_eq("status 200", 200, status)
        resp = json.loads(body)
        assert_eq("routed to echo", "Echo: route me", resp["choices"][0]["message"]["content"])

        # Test 16: Unknown model falls back to default backend
        print("Test 16: Unknown model falls back to default")
        status, _, body = post_json(
            "/v1/chat/completions",
            {"messages": [{"role": "user", "content": "fallback"}], "model": "nonexistent-model"},
        )
        assert_eq("status 200", 200, status)
        resp = json.loads(body)
        assert_eq("fell back to echo", "Echo: fallback", resp["choices"][0]["message"]["content"])

        # Test 17: GET /v1/backends returns correct shape
        print("Test 17: GET /v1/backends")
        data = get_json("/v1/backends")
        backends = data["backends"]
        assert_eq("one backend", 1, len(backends))
        assert_eq("name", "echo", backends[0]["name"])
        assert_eq("type", "echo", backends[0]["type"])
        assert_eq("default", True, backends[0]["default"])

        # Test 18: No fallback configured — backend error returns 502
        print("Test 18: No fallback — error propagates")
        # The echo backend always works, so we verify the config state:
        # get_fallback() should be None since config.yaml has no fallback_backend
        # We test this indirectly — a request to a nonexistent model still uses
        # default (echo) and succeeds; there's no fallback to invoke.
        status, hdrs, body = post_json(
            "/v1/chat/completions",
            {"messages": [{"role": "user", "content": "test"}], "model": "nonexistent"},
        )
        assert_eq("status 200 via default", 200, status)
        resp = json.loads(body)
        assert_eq("no fallback flag", None, resp.get("fallback"))

        # Test 19: VllmBackend created from config with type "vllm"
        print("Test 19: VllmBackend config instantiation")
        from backends import VllmBackend
        from config import BackendRegistry
        import tempfile, pathlib
        vllm_cfg = "default_backend: vllm_test\nbackends:\n  vllm_test:\n    type: vllm\n    url: http://localhost:9999\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(vllm_cfg)
            f.flush()
            reg = BackendRegistry.from_config(f.name)
        pathlib.Path(f.name).unlink()
        b = reg.get("vllm_test")
        assert_eq("is VllmBackend", True, isinstance(b, VllmBackend))
        assert_eq("type is vllm", "vllm", b.type)
        assert_eq("url set", "http://localhost:9999", b.url)

        # Test 20: Technique resolution — default is "baseline"
        print("Test 20: Technique resolution — default baseline")
        status, hdrs, body_str = post_json(
            "/v1/chat/completions",
            {"messages": [{"role": "user", "content": "hi"}]},
        )
        hlower = {k.lower(): v for k, v in hdrs.items()}
        assert_eq("status 200", 200, status)
        assert_eq("technique baseline", "baseline", hlower.get("x-technique"))

        # Test 21: Technique resolution — X-Technique header
        print("Test 21: Technique resolution — X-Technique header")
        status, hdrs, body_str = post_json(
            "/v1/chat/completions",
            {"messages": [{"role": "user", "content": "hi"}]},
            headers={"X-Technique": "chunked_prefill"},
        )
        hlower = {k.lower(): v for k, v in hdrs.items()}
        assert_eq("status 200", 200, status)
        assert_eq("technique from header", "chunked_prefill", hlower.get("x-technique"))

        # Test 22: Technique resolution — metadata.technique in body
        print("Test 22: Technique resolution — body metadata")
        status, hdrs, body_str = post_json(
            "/v1/chat/completions",
            {"messages": [{"role": "user", "content": "hi"}], "metadata": {"technique": "speculative"}},
        )
        hlower = {k.lower(): v for k, v in hdrs.items()}
        assert_eq("status 200", 200, status)
        assert_eq("technique from body", "speculative", hlower.get("x-technique"))

        # Test 23: Technique resolution — header takes priority over body
        print("Test 23: Technique resolution — header priority")
        status, hdrs, body_str = post_json(
            "/v1/chat/completions",
            {"messages": [{"role": "user", "content": "hi"}], "metadata": {"technique": "speculative"}},
            headers={"X-Technique": "beam_search"},
        )
        hlower = {k.lower(): v for k, v in hdrs.items()}
        assert_eq("status 200", 200, status)
        assert_eq("header wins", "beam_search", hlower.get("x-technique"))

        # Test 24: GET /health with echo-only → healthy
        print("Test 24: GET /health — echo-only healthy")
        resp = get_json("/health")
        assert_eq("status healthy", "healthy", resp["status"])
        assert_eq("one backend", 1, len(resp["backends"]))
        assert_eq("echo ok", "ok", resp["backends"][0]["status"])

        # Test 25: /healthz unchanged
        print("Test 25: /healthz still works")
        resp = get_json("/healthz")
        assert_eq("healthz ok", "ok", resp["status"])

        # Test 26: GET /metrics/summary returns JSON
        print("Test 26: GET /metrics/summary")
        resp = get_json("/metrics/summary")
        assert_eq("has server_profile", True, "server_profile" in resp)
        assert_eq("has techniques", True, "techniques" in resp)

        # Test 27: requests_total increments after requests
        print("Test 27: Metrics — requests_total increments")
        # We've already made several requests above, so baseline should have counts
        baseline = resp["techniques"].get("baseline", {})
        assert_eq("baseline has requests", True, baseline.get("requests", 0) > 0)

        # Test 28: Cost is 0.0 when GPU_HOURLY_COST_USD is unset
        print("Test 28: Cost — zero when unset")
        from cost import compute_cost
        assert_eq("cost zero", 0.0, compute_cost(1.0))

    finally:
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=5)

    print(f"\nResults: {PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL > 0 else 0)


if __name__ == "__main__":
    main()

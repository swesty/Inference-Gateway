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
    # Remove BACKEND_URL to ensure echo mode
    env.pop("BACKEND_URL", None)
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

    finally:
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=5)

    print(f"\nResults: {PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL > 0 else 0)


if __name__ == "__main__":
    main()

#!/usr/bin/env bash
# Automated tests for the inference gateway (echo mode).
set -euo pipefail

PORT=9123
BASE="http://localhost:$PORT"
PASS=0
FAIL=0
SERVER_PID=""

cleanup() {
    if [[ -n "$SERVER_PID" ]]; then
        kill "$SERVER_PID" 2>/dev/null || true
        wait "$SERVER_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

# Start server in echo mode
PORT=$PORT uv run python app.py >/dev/null 2>&1 &
SERVER_PID=$!

# Wait for server to be ready
for i in $(seq 1 30); do
    if curl -s "$BASE/healthz" >/dev/null 2>&1; then
        break
    fi
    sleep 0.2
done

assert_eq() {
    local label="$1" expected="$2" actual="$3"
    if [[ "$actual" == "$expected" ]]; then
        echo "  PASS: $label"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $label — expected '$expected', got '$actual'"
        FAIL=$((FAIL + 1))
    fi
}

assert_contains() {
    local label="$1" needle="$2" haystack="$3"
    if [[ "$haystack" == *"$needle"* ]]; then
        echo "  PASS: $label"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $label — '$needle' not found in output"
        FAIL=$((FAIL + 1))
    fi
}

# ---- Test 1: GET /healthz ----
echo "Test 1: GET /healthz"
STATUS=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/healthz")
assert_eq "status 200" "200" "$STATUS"
BODY=$(curl -s "$BASE/healthz")
assert_contains "status ok" '"ok"' "$BODY"

# ---- Test 2: GET /v1/models ----
echo "Test 2: GET /v1/models"
BODY=$(curl -s "$BASE/v1/models")
assert_contains "object list" '"object":"list"' "$(echo "$BODY" | tr -d ' ')"
assert_contains "model echo" '"id":"echo"' "$(echo "$BODY" | tr -d ' ')"

# ---- Test 3: Non-streaming POST ----
echo "Test 3: Non-streaming POST"
BODY=$(curl -s -X POST "$BASE/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -d '{"messages":[{"role":"user","content":"Hello!"}]}')
assert_contains "has id" '"id"' "$BODY"
assert_contains "has choices" '"choices"' "$BODY"
assert_contains "has usage" '"usage"' "$BODY"
assert_contains "object type" '"chat.completion"' "$BODY"
assert_contains "echo content" "Echo: Hello!" "$BODY"

# ---- Test 4: Client-provided X-Request-ID ----
echo "Test 4: Client-provided X-Request-ID"
RESP=$(curl -s -D- -X POST "$BASE/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -H "X-Request-ID: test-42" \
    -d '{"messages":[{"role":"user","content":"Hi"}]}')
assert_contains "id in body" '"id":"test-42"' "$(echo "$RESP" | tr -d ' ')"
assert_contains "id in header" "x-request-id: test-42" "$(echo "$RESP" | tr '[:upper:]' '[:lower:]')"

# ---- Test 5: Auto-generated UUID ----
echo "Test 5: Auto-generated UUID"
BODY=$(curl -s -X POST "$BASE/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -d '{"messages":[{"role":"user","content":"test"}]}')
ID=$(echo "$BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
ID_LEN=${#ID}
assert_eq "uuid length 36" "36" "$ID_LEN"

# ---- Test 6: Streaming ----
echo "Test 6: Streaming SSE"
STREAM=$(curl -s -N -X POST "$BASE/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -d '{"messages":[{"role":"user","content":"Hi"}],"stream":true}')
assert_contains "has Echo:" "Echo: Hi" "$STREAM"
assert_contains "has DONE" "[DONE]" "$STREAM"

# ---- Summary ----
echo ""
echo "Results: $PASS passed, $FAIL failed"
if [[ $FAIL -gt 0 ]]; then
    exit 1
fi

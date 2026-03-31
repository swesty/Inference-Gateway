#!/usr/bin/env bash
# Shared defaults for experiment scripts.

GATEWAY_URL="${GATEWAY_URL:-http://localhost:8080}"
WORKLOAD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../workloads" && pwd)"
TIMEOUT="${TIMEOUT:-60}"

wait_for_gateway() {
    local url="$GATEWAY_URL/healthz"
    local deadline=$((SECONDS + TIMEOUT))
    echo "Waiting for gateway at $url ..."
    while (( SECONDS < deadline )); do
        if curl -sf "$url" > /dev/null 2>&1; then
            echo "Gateway is ready."
            return 0
        fi
        sleep 1
    done
    echo "ERROR: Gateway not reachable after ${TIMEOUT}s" >&2
    return 1
}

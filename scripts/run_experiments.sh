#!/usr/bin/env bash
# Technique sweep: run workload for each technique and collect results.
#
# Usage:
#   ./scripts/run_experiments.sh
#   GATEWAY_URL=http://myhost:8080 ./scripts/run_experiments.sh

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/_common.sh"

TECHNIQUES=("baseline" "chunked_prefill" "speculative" "beam_search")
TOPIC="${TOPIC:-large language models}"

wait_for_gateway || exit 1

echo ""
echo "=== Technique Sweep ==="
echo "Gateway: $GATEWAY_URL"
echo "Topic:   $TOPIC"
echo ""

for tech in "${TECHNIQUES[@]}"; do
    echo "--- Running technique: $tech ---"
    (cd "$WORKLOAD_DIR" && uv run python workload.py \
        --technique "$tech" \
        --topic "$TOPIC" \
        --gateway-url "$GATEWAY_URL" \
        --no-wait)
    echo ""
done

echo "=== Sweep Complete ==="
echo "Check /metrics/summary or JSONL logs for results."

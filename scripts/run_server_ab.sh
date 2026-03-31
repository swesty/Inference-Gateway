#!/usr/bin/env bash
# A/B testing: compare two techniques sequentially.
#
# Usage:
#   ./scripts/run_server_ab.sh baseline beam_search
#   ./scripts/run_server_ab.sh baseline speculative --topic "neural networks"

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/_common.sh"

TECHNIQUE_A="${1:-baseline}"
TECHNIQUE_B="${2:-beam_search}"
shift 2 2>/dev/null || true

TOPIC="${TOPIC:-large language models}"
RUNS="${RUNS:-3}"

# Parse optional flags
while [[ $# -gt 0 ]]; do
    case "$1" in
        --topic) TOPIC="$2"; shift 2 ;;
        --runs)  RUNS="$2"; shift 2 ;;
        *) echo "Unknown flag: $1" >&2; exit 1 ;;
    esac
done

wait_for_gateway || exit 1

echo ""
echo "=== A/B Test: $TECHNIQUE_A vs $TECHNIQUE_B ==="
echo "Gateway: $GATEWAY_URL"
echo "Topic:   $TOPIC"
echo "Runs:    $RUNS per technique"
echo ""

for tech in "$TECHNIQUE_A" "$TECHNIQUE_B"; do
    echo "--- Arm: $tech ($RUNS runs) ---"
    for i in $(seq 1 "$RUNS"); do
        echo "  Run $i/$RUNS"
        (cd "$WORKLOAD_DIR" && uv run python workload.py \
            --technique "$tech" \
            --topic "$TOPIC" \
            --gateway-url "$GATEWAY_URL" \
            --no-wait) 2>&1 | sed 's/^/    /'
    done
    echo ""
done

echo "=== A/B Test Complete ==="
echo "Compare results at $GATEWAY_URL/metrics/summary"

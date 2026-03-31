#!/usr/bin/env bash
# A/B testing harness for comparing vLLM engine configurations.
#
# Usage:
#   ./scripts/run_server_ab.sh sequential   # restart vLLM between arms
#   ./scripts/run_server_ab.sh parallel     # multi-port routing via VLLM_BACKEND_MAP_JSON
#
# Configure arms in scripts/ab_arms.sh (copy from ab_arms.example.sh).

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/_common.sh"

MODE="${1:-sequential}"
ARMS_FILE="${SCRIPT_DIR}/ab_arms.sh"
WORKLOAD_DIR="$(cd "$SCRIPT_DIR/../workloads" && pwd)"
RUNS="${RUNS:-3}"

if [[ ! -f "$ARMS_FILE" ]]; then
    echo "ERROR: $ARMS_FILE not found." >&2
    echo "Copy ab_arms.example.sh to ab_arms.sh and customize." >&2
    exit 1
fi

source "$ARMS_FILE"

run_workload() {
    local technique="$1"
    (cd "$WORKLOAD_DIR" && uv run python workload.py \
        --technique "$technique" \
        --gateway-url "$GATEWAY_URL" \
        --no-wait) 2>&1 | sed 's/^/    /'
}

# ---------------------------------------------------------------------------
# Sequential: restart vLLM + gateway between arms
# ---------------------------------------------------------------------------
run_sequential() {
    echo "=== A/B Test: Sequential Mode ==="
    echo "Arms: $AB_ARMS_COUNT | Runs per arm: $RUNS"
    echo ""

    for i in $(seq 1 "$AB_ARMS_COUNT"); do
        local profile_var="AB_ARM_${i}_SERVER_PROFILE"
        local technique_var="AB_ARM_${i}_TECHNIQUE"
        local hint_var="AB_ARM_${i}_HINT"
        local profile="${!profile_var}"
        local technique="${!technique_var}"
        local hint="${!hint_var}"

        echo "--- Arm $i/$AB_ARMS_COUNT: $profile ---"
        echo "  Technique: $technique"
        echo ""
        echo "  1. On GPU host, start vLLM:"
        echo "     $hint"
        echo ""
        echo "  2. Set VLLM_SERVER_PROFILE=$profile in .env"
        echo "  3. Restart gateway: uv run python app.py"
        echo ""
        read -r -p "  Press ENTER when ready (or 'skip' to skip this arm): " response
        if [[ "$response" == "skip" ]]; then
            echo "  Skipped."
            echo ""
            continue
        fi

        wait_for_gateway || { echo "  Gateway not reachable, skipping arm." >&2; continue; }

        for r in $(seq 1 "$RUNS"); do
            echo "  Run $r/$RUNS"
            run_workload "$technique"
        done
        echo ""
    done

    echo "=== Sequential A/B Complete ==="
    echo "Compare server_profile labels in Grafana or /metrics/summary."
}

# ---------------------------------------------------------------------------
# Parallel: one vLLM per port, VLLM_BACKEND_MAP_JSON routing
# ---------------------------------------------------------------------------
run_parallel() {
    echo "=== A/B Test: Parallel Mode ==="
    echo "Arms: $AB_ARMS_COUNT | Runs per arm: $RUNS"
    echo ""
    echo "Prerequisites:"
    echo "  1. Run engine fleet on GPU: bash scripts/vllm_engine/run_engine_fleet.sh"
    echo "  2. Multi-port SSH tunnel (ports 8000-8005)"
    echo "  3. Set VLLM_AUTO_ENGINE_ROUTING=true in .env (or VLLM_BACKEND_MAP_JSON)"
    echo "  4. Restart gateway"
    echo ""
    read -r -p "Press ENTER when ready: "

    wait_for_gateway || exit 1

    for i in $(seq 1 "$AB_ARMS_COUNT"); do
        local technique_var="AB_ARM_${i}_TECHNIQUE"
        local profile_var="AB_ARM_${i}_SERVER_PROFILE"
        local technique="${!technique_var}"
        local profile="${!profile_var}"

        echo "--- Arm $i/$AB_ARMS_COUNT: $profile (technique: $technique) ---"
        for r in $(seq 1 "$RUNS"); do
            echo "  Run $r/$RUNS"
            run_workload "$technique"
        done
        echo ""
    done

    echo "=== Parallel A/B Complete ==="
    echo "Compare technique labels in Grafana or /metrics/summary."
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
case "$MODE" in
    sequential) run_sequential ;;
    parallel)   run_parallel ;;
    *)
        echo "Usage: $0 {sequential|parallel}" >&2
        echo ""
        echo "  sequential  Restart vLLM between arms (guided prompts)"
        echo "  parallel    Multi-port routing (engine fleet + auto routing)" >&2
        exit 1
        ;;
esac

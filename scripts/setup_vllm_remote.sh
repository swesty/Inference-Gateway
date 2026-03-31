#!/usr/bin/env bash
# Install and start vLLM on a fresh cloud GPU instance.
#
# Usage (run ON the remote instance):
#   bash setup_vllm_remote.sh
#   MODEL_NAME=TinyLlama/TinyLlama-1.1B-Chat-v1.0 bash setup_vllm_remote.sh
#
# Or via SSH:
#   ssh user@gpu-host 'bash -s' < scripts/setup_vllm_remote.sh

set -euo pipefail

MODEL_NAME="${MODEL_NAME:-TinyLlama/TinyLlama-1.1B-Chat-v1.0}"
VLLM_PORT="${VLLM_PORT:-8000}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-2048}"

echo "=== vLLM Remote Setup ==="
echo "Model:    $MODEL_NAME"
echo "Port:     $VLLM_PORT"
echo "Max len:  $MAX_MODEL_LEN"
echo ""

# Install vLLM if not present
if ! command -v vllm &> /dev/null; then
    echo "Installing vLLM..."
    pip install vllm
fi

echo "Starting vLLM server..."
exec vllm serve "$MODEL_NAME" \
    --port "$VLLM_PORT" \
    --max-model-len "$MAX_MODEL_LEN" \
    --trust-remote-code

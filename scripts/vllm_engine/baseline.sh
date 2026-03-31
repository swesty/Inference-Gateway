#!/usr/bin/env bash
# Baseline vLLM: minimal flags, rely on vLLM defaults.
# Engine args: https://docs.vllm.ai/en/stable/configuration/engine_args/
set -euo pipefail
cd "$(dirname "$0")"
source ./_common.sh
exec vllm serve "$VLLM_MODEL" \
  --served-model-name "$VLLM_SERVED_NAME" \
  --host "$VLLM_BIND_HOST" \
  --port "$VLLM_SERVE_PORT"

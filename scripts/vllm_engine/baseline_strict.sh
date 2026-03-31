#!/usr/bin/env bash
# Strict baseline: explicitly disable chunked prefill + prefix caching.
# Use as a control arm if your vLLM version defaults them on.
set -euo pipefail
cd "$(dirname "$0")"
source ./_common.sh
exec vllm serve "$VLLM_MODEL" \
  --served-model-name "$VLLM_SERVED_NAME" \
  --host "$VLLM_BIND_HOST" \
  --port "$VLLM_SERVE_PORT" \
  --no-enable-chunked-prefill \
  --no-enable-prefix-caching

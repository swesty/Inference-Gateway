#!/usr/bin/env bash
# Speculative decoding via --speculative-config.
# https://docs.vllm.ai/en/stable/features/speculative_decoding/
#
# Set a full JSON string before running, e.g.:
#   export VLLM_SPECULATIVE_CONFIG_JSON='{"method":"eagle","model":"org/draft-ckpt","num_speculative_tokens":3}'
#   bash scripts/vllm_engine/speculative_decoding.sh
set -euo pipefail
cd "$(dirname "$0")"
source ./_common.sh
DEFAULT_SPEC='{"method":"eagle","model":"REPLACE_WITH_DRAFT_HF_ID","num_speculative_tokens":3}'
SPEC_JSON="${VLLM_SPECULATIVE_CONFIG_JSON:-$DEFAULT_SPEC}"
if [[ "$SPEC_JSON" == *"REPLACE_WITH_DRAFT_HF_ID"* ]]; then
  echo "Set VLLM_SPECULATIVE_CONFIG_JSON with a real draft model id." >&2
  echo "See: https://docs.vllm.ai/en/stable/features/speculative_decoding/" >&2
  exit 1
fi
exec vllm serve "$VLLM_MODEL" \
  --served-model-name "$VLLM_SERVED_NAME" \
  --host "$VLLM_BIND_HOST" \
  --port "$VLLM_SERVE_PORT" \
  --speculative-config "$SPEC_JSON"

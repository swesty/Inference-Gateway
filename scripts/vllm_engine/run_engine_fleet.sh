#!/usr/bin/env bash
# Launch one vLLM process per engine profile on fixed ports (GPU host only).
# Port layout matches gateway VLLM_AUTO_ENGINE_ROUTING=true offsets.
#
# On your laptop: set VLLM_AUTO_ENGINE_ROUTING=true in .env, keep the base URL
# pointing at port 8000, and forward all ports in the SSH tunnel.
#
# VRAM: multiple TinyLlama processes may fit one GPU; larger models may OOM.
set -euo pipefail
cd "$(dirname "$0")"
source ./_common.sh

declare -a PIDS=()

cleanup() {
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
}
trap cleanup INT TERM

launch() {
  local port=$1
  shift
  echo "Starting vLLM on :$port $*" >&2
  VLLM_SERVE_PORT=$port vllm serve "$VLLM_MODEL" \
    --served-model-name "$VLLM_SERVED_NAME" \
    --host "$VLLM_BIND_HOST" \
    --port "$port" \
    "$@" &
  PIDS+=($!)
}

launch 8000
launch 8001 --enable-chunked-prefill
launch 8002 --enable-prefix-caching
launch 8003 --enable-chunked-prefill --enable-prefix-caching
launch 8004 --no-enable-chunked-prefill --no-enable-prefix-caching

if [[ -n "${VLLM_SPECULATIVE_CONFIG_JSON:-}" ]]; then
  launch 8005 --speculative-config "$VLLM_SPECULATIVE_CONFIG_JSON"
else
  echo "Skipping :8005 (speculative_decoding): export VLLM_SPECULATIVE_CONFIG_JSON to enable." >&2
fi

echo "Fleet PIDs: ${PIDS[*]}" >&2
echo "Laptop: VLLM_AUTO_ENGINE_ROUTING=true + multi-port SSH tunnel (see README Step 7)." >&2
wait

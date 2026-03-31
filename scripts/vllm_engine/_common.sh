# shellcheck shell=bash
# Shared defaults for vllm serve wrappers. Source-only (do not execute directly).
#
# Engine / scheduler flags reference:
#   https://docs.vllm.ai/en/stable/configuration/engine_args/
#
# Override any variable when invoking, e.g.:
#   VLLM_SERVE_PORT=8001 bash scripts/vllm_engine/chunked_prefill.sh
#
# Run these on the GPU host (e.g. Lambda), not your laptop.

: "${VLLM_MODEL:=TinyLlama/TinyLlama-1.1B-Chat-v1.0}"
: "${VLLM_SERVED_NAME:=texttinyllama}"
: "${VLLM_BIND_HOST:=0.0.0.0}"
: "${VLLM_SERVE_PORT:=8000}"

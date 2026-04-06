# Testing Results

## Current Environment (2026-04-06)

- **GPU**: NVIDIA RTX 6000 Pro Blackwell 96GB (Jarvis, LAN)
- **Model**: Nemotron Nano 3 30B nvfp4 (served as `nemotron-lora`)
- **Gateway**: FastAPI on gesserit :8080, Prometheus :9101, nginx LB :8780
- **Workload**: Ops/Triage agent (4-step: classify → investigate → recommend → summarize), 7 golden incidents

### Triage Agent Results (Nemotron 30B on Jarvis)

| Arm | Technique | Concurrency | Success | p50 | p95 | Throughput | Category Acc |
|-----|-----------|-------------|---------|-----|-----|------------|-------------|
| 1 | baseline | 1 | 7/7 | 7.1s | 15.3s | 0.13 inc/s | 85.7% |
| 2 | chunked_prefill | 1 | 7/7 | 7.1s | 19.0s | 0.10 inc/s | 57.1% |
| 3 | baseline | 3 | 7/7 | 7.2s | 28.2s | 0.25 inc/s | 42.9% |
| 4 | chunked_prefill | 3 | 7/7 | 8.6s | 26.5s | 0.16 inc/s | 57.1% |

### Raw Benchmark (Nemotron 30B, 30 requests, concurrency=5, max_tokens=64)

| Technique | Throughput | p50 | p95 | Errors |
|-----------|-----------|-----|-----|--------|
| baseline | 5.9 req/s | 901ms | 1001ms | 0 |
| chunked_prefill | 6.3 req/s | 827ms | 1006ms | 0 |

---

## Historical Environment (2026-04-02)

> Results below are from earlier testing on RTX 3090 with TinyLlama 1.1B. Kept for reference.

- **GPU**: NVIDIA GeForce RTX 3090, 24GB VRAM, CUDA 8.6, driver 580.119.02
- **Model**: TinyLlama/TinyLlama-1.1B-Chat-v1.0 (max_model_len=2048)
- **Backends tested**: Echo, Ollama 0.11.4, vLLM 0.18.1
- **Gateway**: FastAPI on port 8080, Prometheus metrics on port 9101
- **Workload**: LangChain two-step agent (Researcher -> Writer), 2 LLM calls per workload

## Unit Tests

74/74 assertions passing across 30 test cases covering validation, normalization, routing, streaming, metrics, logging, and technique resolution.

## Quick Start (Echo Backend)

| Endpoint | Status |
|----------|--------|
| `GET /healthz` | 200 OK |
| `GET /health` | healthy, 1 backend |
| `GET /v1/models` | lists echo |
| `GET /v1/backends` | echo, default=true |
| `POST /v1/chat/completions` (non-streaming) | 200, correct echo response |
| `POST /v1/chat/completions` (streaming) | SSE chunks + `[DONE]` |
| `GET /metrics/summary` | JSON with technique counts |
| Prometheus `:9101/metrics` | Histograms and counters |
| JSONL request logs | Daily-rotated files in `logs/gateway/` |
| Body size limit (>1MB) | 413 rejected |
| Startup logging | "Gateway started on port 8080 with N backend(s)" |

## Ollama Backend Testing

Ollama 0.11.4 with TinyLlama, connected as `type: remote` at `http://127.0.0.1:11434`.

### Stress Test Results (Non-streaming)

| Concurrency | Duration | Avg Latency | Success Rate |
|-------------|----------|-------------|--------------|
| 10 | 12s | ~4s | 100% (10/10) |
| 25 | 30s | ~10s | 100% (25/25) |
| 50 | 65s | ~19s | 100% (50/50) |
| 100 | 145s | ~40s | 100% (100/100) |

Gateway held stable at all concurrency levels with zero errors. Latency scaled linearly (GPU queuing).

### Streaming

Streaming initially returned empty responses. Root cause: `generate()` was not awaiting `_forward_stream()`, returning an unawaited coroutine instead of the async generator. Fixed in commit `8cfb7bb`. After fix, streaming worked correctly with full SSE chunk delivery.

## vLLM Backend Testing

vLLM 0.18.1 with TinyLlama, connected as `type: vllm` at `http://127.0.0.1:8000`.

### Baseline vLLM (server_profile=default)

Stress test: 15 streaming workloads per technique (60 total).

| Technique | Success (streaming) | Avg Duration | Avg TTFT |
|-----------|-------------------|-------------|----------|
| baseline | 15/15 | 1.3s | 213ms |
| beam_search | 4/15 | 13.0s | 12.9s |
| chunked_prefill | 15/15 | 1.3s | 179ms |
| speculative | 15/15 | 1.5s | 115ms |

Beam search streaming failures are expected: beam search explores multiple candidates before emitting tokens, which conflicts with SSE streaming. Non-streaming beam search works fine (10/10).

### Chunked Prefill vLLM (server_profile=chunked_prefill)

vLLM restarted with `--enable-chunked-prefill`. Stress test: 20 streaming + 15 non-streaming per technique.

| Technique | Streaming | Non-streaming | Avg Duration | Avg TTFT |
|-----------|-----------|---------------|-------------|----------|
| baseline | 20/20 | 15/15 | 2.1s | 161ms |
| beam_search | 11/20 | 15/15 | 14.7s | 18.0s |
| chunked_prefill | 20/20 | 15/15 | 1.8s | 134ms |
| speculative | 20/20 | 15/15 | 2.7s | 168ms |

### Cumulative Metrics (chunked_prefill profile)

| Metric | Value |
|--------|-------|
| Total requests | 371 |
| Prompt tokens | 45,160 |
| Completion tokens | 62,037 |
| TTFT observations (streaming) | 211 |

### vLLM vs Ollama Comparison (at 15 concurrent)

| Metric | Ollama | vLLM (baseline) | vLLM (chunked prefill) |
|--------|--------|-----------------|----------------------|
| Avg duration | ~9s | 1.3s | 1.8s |
| Avg TTFT | N/A (non-streaming) | 213ms | 134ms |

vLLM is ~5-7x faster than Ollama for the same model at similar concurrency.

## Bugs Found and Fixed During Testing

| Bug | Root Cause | Fix |
|-----|-----------|-----|
| Empty streaming responses from remote backends | `generate()` returned unawaited coroutine from `_forward_stream()` | Added `await` — commit `8cfb7bb` |
| Beam search params never injected to vLLM | `normalize_request_body()` stripped `technique` field before `_prepare_body()` could read it | Inject `technique` into body after resolution — commit `2f54cf5` |
| Ollama returning 400 from workload | LangChain workload didn't pass `model` field; Ollama requires it | Added `--model` flag to workload — commit `2ec41a0` |

## Observability Verification

| Component | Status |
|-----------|--------|
| Prometheus scraping gateway | UP, 15s interval |
| Grafana dashboards | 10 panels, server_profile dropdown, per-technique breakdowns |
| TTFT metrics | Populated for streaming requests across all techniques |
| Inter-chunk delay metrics | Populated (17,971+ observations) |
| Tokens/sec metrics | Populated for non-streaming requests |
| JSONL request logs | Daily rotation, all fields present |
| Operational logging | Startup, errors, fallback events, stream failures |

## Lambda Cloud Testing (A10 GPU)

Instance: 150.136.249.201, NVIDIA A10 (23GB), vLLM 0.18.1 via SSH tunnel.

### Stress Test (20 streaming + 15 non-streaming per technique)

| Technique | Streaming | Non-streaming | Avg Duration | Avg TTFT |
|-----------|-----------|---------------|-------------|----------|
| baseline | 20/20 | 15/15 | 3.1s | 105ms |
| beam_search | 7/20 | 15/15 | 18.1s | 18.0s |
| chunked_prefill | 20/20 | 15/15 | 3.6s | 87ms |
| speculative | 20/20 | 15/15 | 3.4s | 84ms |

### Nginx Load Balancer

Full request path verified: client -> nginx :8780 -> gateway :8080 -> SSH tunnel -> Lambda A10 vLLM.
Health, models, and chat completion endpoints all working through the load balancer.

### Experiment Script Sweep

`scripts/run_experiments.sh` ran successfully across all 4 techniques. baseline, chunked_prefill, and speculative completed through Lambda vLLM. beam_search fell back to echo (beam search params cause vLLM errors in non-streaming mode with newer versions).

## Benchmark Results (scripts/benchmark.py)

Raw throughput and latency measurements using the async benchmark script. Results isolate gateway + backend performance without LangChain overhead.

### Gateway Overhead (Echo Backend)

| Concurrency | Throughput | p50 Latency | p99 Latency |
|-------------|-----------|-------------|-------------|
| 50 | **1,063 req/s** | 42ms | 96ms |
| 50 (streaming) | **966 req/s** | 46ms | 96ms |

The gateway adds ~42ms overhead at 50 concurrent requests — under 2% of a typical LLM request.

### RTX 3090 + vLLM (TinyLlama, max_tokens=32)

| Mode | Concurrency | Throughput | p50 Latency | p50 TTFT | p95 TTFT |
|------|-------------|-----------|-------------|----------|----------|
| Non-streaming | 20 | **133 req/s** | 156ms | — | — |
| Streaming | 20 | **132 req/s** | 159ms | **19ms** | 59ms |
| Streaming | 50 | **219 req/s** | 218ms | **46ms** | 128ms |

Zero errors across all runs (500/500 requests).

### Cross-Environment Comparison

| Environment | GPU | Avg Duration | Avg TTFT | Notes |
|-------------|-----|-------------|----------|-------|
| Local Ollama | RTX 3090 | ~4s (10 concurrent) | N/A | Non-streaming only |
| Local vLLM (baseline) | RTX 3090 | 2.2s | 213ms | |
| Local vLLM (chunked prefill) | RTX 3090 | 1.8s | 134ms | --enable-chunked-prefill |
| Lambda vLLM (baseline) | A10 | 3.1s | 105ms | Via SSH tunnel |

## README Walkthrough Verification

All 20 steps verified end-to-end:

| Steps | Description | Status |
|-------|-------------|--------|
| 1-8 | Lambda setup, SSH, GPU, vLLM, tunnel | Verified |
| 9-11 | Project config, gateway startup, health checks | Verified |
| 12-13 | Nginx load balancer on port 8780 | Verified |
| 14 | LangChain workload through full path | Verified |
| 15 | All metrics endpoints (Prometheus, JSON, JSONL) | Verified |
| 16-18 | Prometheus + Grafana with live traffic | Verified |
| 19 | Experiment scripts (technique sweep) | Verified |

## Review Issues Addressed

12 issues created (#26-#37) from code review, all fixed in two commits:

- **Wave 1** (`fd0ef3b`): Connection pooling, technique validation, async I/O, VllmBackend dedup, Docker hardening, dead code removal, pinned images, code quality
- **Wave 2** (`69a88c9`): Logging framework, graceful shutdown (lifespan), stream error handling, body size limit

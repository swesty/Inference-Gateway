# Technique Resolution & Engine Routing

## Overview

Every request gets a **technique** label used for metrics grouping, logging, and optional engine routing. The technique is resolved from the request, then optionally used to route to a technique-specific vLLM instance.

```
Request → Technique Resolution → Engine Routing → Backend
                                      ↓
                             (if no engine route)
                                      ↓
                              Normal registry lookup
```

## Technique Resolution

**Priority order** (first match wins):

| Priority | Source | Example |
|----------|--------|---------|
| 1 (highest) | `X-Technique` request header | `curl -H "X-Technique: chunked_prefill" ...` |
| 2 | `metadata.technique` in request body | `{"metadata": {"technique": "speculative"}}` |
| 3 (default) | Hardcoded | `"baseline"` |

The resolved technique appears in:
- `X-Technique` response header
- Prometheus metric labels
- JSONL log entries

## Engine Routing

Engine routing is **optional** — leave both env vars unset for normal model-based routing.

### Why Engine Routing Exists

vLLM engine flags (chunked prefill, prefix caching, speculative decoding) are set at **server startup**, not per-request. To compare different engine configurations without restarting between requests, you run **multiple vLLM instances on different ports** and let the gateway route by technique.

### Strategy 1: Explicit JSON Mapping

Set `VLLM_BACKEND_MAP_JSON` with a technique → URL map:

```bash
VLLM_BACKEND_MAP_JSON='{"baseline":"http://localhost:8000","chunked_prefill":"http://localhost:8001","speculative":"http://localhost:8002"}'
```

- Request with `X-Technique: chunked_prefill` → `http://localhost:8001`
- Request with unknown technique → falls through to normal registry lookup

### Strategy 2: Auto Port-Offset

Set `VLLM_AUTO_ENGINE_ROUTING=true`. The gateway applies a port offset to the default backend's URL:

| Technique | Port Offset |
|-----------|-------------|
| `baseline` | +0 |
| `chunked_prefill` | +1 |
| `speculative` | +2 |
| `beam_search` | +3 |

If the default backend URL is `http://localhost:8000`:
- `X-Technique: chunked_prefill` → routes to `http://localhost:8001`
- `X-Technique: speculative` → routes to `http://localhost:8002`

This matches the port layout of `scripts/vllm_engine/run_engine_fleet.sh`.

### Engine Routing Creates Ephemeral Backends

When engine routing activates, it creates a temporary `VllmBackend` instance for that request. These backends are **not** registered in the `BackendRegistry` — they exist only for the duration of the request. This keeps the registry clean and avoids confusion in `/v1/backends` listings.

---

## A/B Testing

### Concepts

| Term | Meaning |
|------|---------|
| **Technique** | Label for the request type. Groups metrics. Set via `X-Technique` header. |
| **Server Profile** | Label for the engine configuration. Set via `VLLM_SERVER_PROFILE` env var. Change and restart gateway between engine configs. |

Both labels appear in Prometheus metrics and JSONL logs. Use **technique** to compare request types against the same engine, and **server profile** to compare engine configurations.

### Label-Only Sweep

Same vLLM server, different technique labels. Tests how the gateway handles different labels, not different engines.

```bash
./scripts/run_experiments.sh
```

### Sequential A/B

Restart vLLM with different engine flags between arms. Guided prompts tell you what to do at each step.

```bash
./scripts/run_server_ab.sh sequential
```

Flow per arm:
1. Script shows which engine script to run on the GPU host
2. You restart vLLM with the new flags
3. You set `VLLM_SERVER_PROFILE` in `.env` and restart the gateway
4. Script runs the workload N times
5. Repeat for next arm

Compare results by `server_profile` in Grafana.

### Parallel A/B

Multiple vLLM instances on different ports. No restarts needed.

```bash
# On GPU host:
bash scripts/vllm_engine/run_engine_fleet.sh

# On laptop (multi-port tunnel):
ssh -L 8000:127.0.0.1:8000 -L 8001:127.0.0.1:8001 ... -N ubuntu@<IP>

# Set in .env:
VLLM_AUTO_ENGINE_ROUTING=true

# Run:
./scripts/run_server_ab.sh parallel
```

Compare results by `technique` in Grafana (each technique routes to a different engine).

### Configuring Arms

Copy `scripts/ab_arms.example.sh` to `scripts/ab_arms.sh` and customize:

```bash
AB_ARMS_COUNT=4

AB_ARM_1_SERVER_PROFILE="eng_baseline"
AB_ARM_1_TECHNIQUE="ab_baseline"
AB_ARM_1_HINT="bash scripts/vllm_engine/baseline.sh"

AB_ARM_2_SERVER_PROFILE="eng_chunked_prefill"
AB_ARM_2_TECHNIQUE="ab_chunked_prefill"
AB_ARM_2_HINT="bash scripts/vllm_engine/chunked_prefill.sh"
# ...
```

---

## vLLM Engine Profiles

Located in `scripts/vllm_engine/`. Run these **on the GPU host**, not the laptop.

| Script | Flags | Port |
|--------|-------|------|
| `baseline.sh` | Minimal (vLLM defaults) | 8000 |
| `chunked_prefill.sh` | `--enable-chunked-prefill` | 8000 |
| `prefix_caching.sh` | `--enable-prefix-caching` | 8000 |
| `chunked_prefill_and_prefix_caching.sh` | Both flags | 8000 |
| `baseline_strict.sh` | `--no-enable-chunked-prefill --no-enable-prefix-caching` | 8000 |
| `speculative_decoding.sh` | `--speculative-config $JSON` | 8000 |
| `run_engine_fleet.sh` | All of the above on ports 8000–8005 | 8000–8005 |

Override defaults with environment variables:

```bash
VLLM_MODEL=meta-llama/Llama-2-7b-chat-hf VLLM_SERVE_PORT=8001 bash scripts/vllm_engine/chunked_prefill.sh
```

### Beam Search

Beam search is **not** an engine flag — it's a per-request parameter. `VllmBackend` automatically injects `use_beam_search=True` and `best_of=4` when `technique="beam_search"`. No special vLLM startup flags needed. Compare beam vs greedy by running the workload with `--technique beam_search` vs `--technique baseline` against the same server.

# Inference Gateway

An OpenAI-compatible HTTP inference gateway. Routes `POST /v1/chat/completions` to named backends defined in `config.yaml`, with streaming, fallback routing, Prometheus metrics, JSONL logging, and optional OpenTelemetry tracing.

GPU inference runs on **Jarvis** (RTX 6000 Pro Blackwell 96GB, LAN) serving **Nemotron Nano 3 30B** (nvfp4) via vLLM. **Gesserit** (dev workstation) runs the **triage agent** → **nginx** (load balancer) → the FastAPI **gateway** → vLLM on Jarvis over LAN. An SSH tunnel is used when the GPU host is remote (e.g., Lambda Cloud).

**You need:** Python 3.12+, **[uv](https://docs.astral.sh/uv/)**, **nginx** for the load balancer, and **Docker** for Prometheus + Grafana.

---

## Run everything in this order

Do the steps **in sequence**. Keep earlier long-running steps open (Lambda SSH with vLLM, tunnel) while you do later steps on **new terminal tabs** on your laptop.

---

### Step 1 — Create an SSH key on your laptop

Skip if you already have a key registered with Lambda.

```bash
ssh-keygen -t ed25519 -C "your_email@example.com" -f ~/.ssh/id_ed25519_lambda -N ""
cat ~/.ssh/id_ed25519_lambda.pub
```

Copy the full line from the `.pub` file. Never share the file without `.pub`.

---

### Step 2 — Add that key in Lambda Cloud

1. Open **https://cloud.lambdalabs.com/** and sign in.
2. Go to **SSH keys**.
3. **Add** a key and paste the public line. Save.

---

### Step 3 — Launch a GPU instance in Lambda

1. **Instances** → **Launch instance**.
2. Pick a **region** and **GPU** type (A10 for small models, A100+ for Nemotron 30B).
3. **Base image:** choose **Lambda Stack 24.04** or **Lambda Stack 22.04** (includes NVIDIA driver, CUDA, Python).
4. Select your **SSH key** from Step 2.
5. **Launch** and wait until the instance is **running**.
6. Copy the instance **public IP**.

You pay while the instance runs — **terminate** when done.

---

### Step 4 — SSH into the instance

```bash
ssh -i ~/.ssh/id_ed25519_lambda ubuntu@<INSTANCE_IP>
```

---

### Step 5 — On the instance: confirm the GPU

```bash
nvidia-smi
```

You should see an NVIDIA GPU. If you get `command not found`, you likely chose a CPU-only SKU or the wrong image — terminate and launch again with a GPU type and Lambda Stack.

---

### Step 6 — On the instance: install vLLM and start the server

Still inside the SSH session. Leave this terminal open with `vllm serve` running.

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip
python3 -m venv ~/vllm-env
source ~/vllm-env/bin/activate
pip install -U pip wheel
pip install "vllm==0.13.0"

vllm serve nvidia/Nemotron-Nano-3-30B-Instruct \
  --served-model-name nemotron-lora \
  --host 0.0.0.0 \
  --port 8000
```

Or use the engine profile scripts (copy `scripts/vllm_engine/` to the GPU host):

```bash
bash scripts/vllm_engine/baseline.sh
```

Other profiles: `chunked_prefill.sh`, `prefix_caching.sh`, `speculative_decoding.sh`, etc.

**Engine fleet** (one vLLM per technique, ports 8000–8005):

```bash
bash scripts/vllm_engine/run_engine_fleet.sh
```

Wait until you see **application startup complete**. First install and model download can take several minutes.

---

### Step 7 — On your laptop: open the SSH tunnel

**New tab** on the laptop. Do not close Step 6.

```bash
ssh -i ~/.ssh/id_ed25519_lambda -L 8000:127.0.0.1:8000 -N ubuntu@<INSTANCE_IP>
```

**Engine fleet** (forward all ports):

```bash
ssh -i ~/.ssh/id_ed25519_lambda \
  -L 8000:127.0.0.1:8000 -L 8001:127.0.0.1:8001 -L 8002:127.0.0.1:8002 \
  -L 8003:127.0.0.1:8003 -L 8004:127.0.0.1:8004 -L 8005:127.0.0.1:8005 \
  -N ubuntu@<INSTANCE_IP>
```

---

### Step 8 — On your laptop: check vLLM through the tunnel

**New tab:**

```bash
curl -sS http://127.0.0.1:8000/v1/models
```

You should see JSON with `"id":"nemotron-lora"`. If this fails, fix Step 6 or 7 before continuing.

---

### Step 9 — On your laptop: configure the project

```bash
cd <path-to-inference-gateway>
cp .env.example .env
```

Edit `.env`:

```bash
PORT=8080
VLLM_SERVER_PROFILE=baseline
# For engine fleet routing:
# VLLM_AUTO_ENGINE_ROUTING=true
```

Install dependencies:

```bash
uv sync
```

Update `config.yaml` to include the vLLM backend:

```yaml
default_backend: vllm_jarvis
fallback_backend: echo
backends:
  echo:
    type: echo
  vllm_jarvis:
    type: vllm
    url: http://jarvis.swesty.net:8000  # LAN direct; use http://localhost:8081 with SSH tunnel
```

---

### Step 10 — On your laptop: start the gateway

```bash
uv run python app.py
```

Gateway listens on **`:8080`**. Prometheus metrics on **`:9101/metrics`**. JSONL logs in `logs/gateway/`.

---

### Step 11 — On your laptop: quick check (gateway port 8080)

```bash
curl -sS http://127.0.0.1:8080/healthz
curl -sS http://127.0.0.1:8080/health
curl -sS http://127.0.0.1:8080/v1/models
```

You want `200` on `/health` with `"status":"healthy"` and `nemotron-lora` in `/v1/models`.

---

### Step 12 — On your laptop: start nginx load balancer

Needs `nginx` installed (`nginx -v`).

```bash
nginx -t -p /tmp -c "$(pwd)/monitoring/nginx-gateway-lb.conf"
nginx -p /tmp -c "$(pwd)/monitoring/nginx-gateway-lb.conf"
```

Stop later:

```bash
nginx -s quit -p /tmp -c "$(pwd)/monitoring/nginx-gateway-lb.conf"
```

---

### Step 13 — On your laptop: quick check (load balancer 8780)

```bash
curl -sS http://127.0.0.1:8780/health
curl -sS http://127.0.0.1:8780/v1/models
curl -sS "http://127.0.0.1:8780/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "X-Technique: baseline" \
  -d '{"model":"nemotron-lora","messages":[{"role":"user","content":"Say hi in five words."}],"max_tokens":32}'
```

If `8780` refuses: Step 12 didn't start. If `502`: gateway on `8080` is not up.

---

### Step 14 — On your laptop: run the workload

Steps 6, 7, 10, 12 must be running.

```bash
cd workloads
uv sync
uv run python workload.py --technique baseline
```

**Path:** Workload → nginx `8780` → gateway `8080` → tunnel → vLLM. Model name `nemotron-lora` must match `--served-model-name`.

---

### Step 15 — What "full metrics" means

- **Prometheus text:** `http://127.0.0.1:9101/metrics` (histograms and counters with `technique` + `server_profile` labels)
- **JSON summary:** `http://127.0.0.1:8080/metrics/summary`
- **vLLM engine metrics:** `http://127.0.0.1:8000/metrics` (via tunnel)
- **JSONL per-request logs:** `logs/gateway/gateway_metrics_YYYY-MM-DD.jsonl`

**Labels:** `--technique` on the workload sets `X-Technique`. Set `VLLM_SERVER_PROFILE` in `.env` to match the vLLM you are running; restart gateway after changing.

---

### Step 16 — Start Prometheus + Grafana (Docker)

From the **repo root** (Steps 6, 7, 10 must be running):

```bash
docker compose up -d
```

- **Prometheus:** http://127.0.0.1:9090
- **Grafana:** http://127.0.0.1:3000 (admin / admin)

Open http://127.0.0.1:9090/targets — confirm **`inference-gateway`** is **UP**.

---

### Step 17 — Open Grafana and use the dashboards

1. Open http://127.0.0.1:3000
2. **Dashboards** → **Inference Gateway** folder
3. Start with **Inference Gateway Overview** — request rate, latency percentiles, TTFT, tokens/sec, GPU cost

---

### Step 18 — Generate traffic so the graphs move

With Grafana open (time range **Last 15 minutes**):

1. Send traffic with Step 13 `curl`, or run `uv run python workload.py --technique baseline` (Step 14).
2. Wait one or two scrape intervals (15s).
3. Refresh the dashboard.

Labeled histograms only get data after at least one request with that label pair.

---

### Step 19 — Different vLLM engine settings (A/B)

Engine flags are set at **`vllm serve` startup**, not per-request. `X-Technique` is a label only. To compare engine configs:

**Label-only sweep** (same vLLM, different technique labels):

```bash
./scripts/run_experiments.sh
```

**Sequential A/B** (restart vLLM between arms, guided prompts):

```bash
./scripts/run_server_ab.sh sequential
```

**Parallel A/B** (engine fleet + auto port routing):

```bash
# On GPU: bash scripts/vllm_engine/run_engine_fleet.sh
# .env: VLLM_AUTO_ENGINE_ROUTING=true
./scripts/run_server_ab.sh parallel
```

Configure arms in `scripts/ab_arms.sh` (copy from `ab_arms.example.sh`).

After each server config change: set `VLLM_SERVER_PROFILE` in `.env`, restart gateway, then run workload. Compare by `server_profile` in Grafana.

---

### Step 20 — Troubleshooting

| # | Problem | Fix |
|---|---------|-----|
| 1 | SSH permission denied | Wrong key, user, or key not added in Lambda (Steps 1–2) |
| 2 | `nvidia-smi` not found on Lambda | Wrong instance type or image; redo Step 3 with GPU SKU + Lambda Stack |
| 3 | `connection refused` on `127.0.0.1:8000` | Step 6 not running, or Step 7 tunnel not running |
| 4 | `connection refused` on `127.0.0.1:8080` | Step 10 not running or wrong directory/env |
| 5 | `connection refused` on `127.0.0.1:8780` | Step 12 (nginx) not running or wrong config path |
| 6 | `502` from `127.0.0.1:8780` | nginx is up but gateway on `8080` is not; start Step 10 |
| 7 | `/health` not healthy | Fix vLLM backend URL in `config.yaml` (`http://127.0.0.1:8000` with tunnel) |
| 8 | Workload LLM errors | Run Step 13 curl to verify gateway+vLLM end-to-end |
| 9 | Grafana empty / Prometheus targets red | Confirm Steps 6, 7, 10 running; `curl http://127.0.0.1:9101/metrics` |
| 10 | No metrics after requests | Restart gateway; widen Grafana time range |
| 11 | vLLM OOM | Reduce `MAX_MODEL_LEN`, lower batch size, or use a smaller model |
| 12 | SSH tunnel drops | Use `tmux`/`screen`; tunnel script uses `ServerAliveInterval=30` |

---

## Quick Start (local, no GPU)

For development without a GPU — echo backend works out of the box:

```bash
uv sync
uv run python app.py
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hello!"}]}'
```

---

## Automated Tests

```bash
uv run python test_gateway.py
```

---

## Configuration

Backends are defined in `config.yaml`. If no config file is found, the gateway runs with a single echo backend.

```yaml
default_backend: echo
fallback_backend: echo
backends:
  echo:
    type: echo
  vllm_remote:
    type: vllm
    url: http://localhost:8000
```

Backend types: `echo` (testing), `remote` (generic OpenAI-compatible), `vllm` (vLLM-specific with beam search + TLS support).

### Supported Inference Engines

Any OpenAI-compatible inference server works with `type: remote`. The `vllm` type adds beam search parameter injection.

| Engine | Type | Start Command | Notes |
|--------|------|---------------|-------|
| **vLLM** | `vllm` | `vllm serve <model> --port 8000` | Beam search, TLS, chunked prefill, speculative decoding |
| **llama.cpp** | `remote` | `llama-server -m model.gguf --port 8000` | CPU/GPU, GGUF quantized models |
| **SGLang** | `remote` | `python -m sglang.launch_server --model <model> --port 8000` | RadixAttention, continuous batching |
| **TensorRT-LLM** | `remote` | Via Triton with OpenAI frontend | NVIDIA-optimized, INT4/INT8/FP8 quantization |
| **Ollama** | `remote` | `ollama serve` (port 11434) | Easy setup, GGUF models, `model` field required |
| **OpenAI API** | `remote` | N/A | Use `url: https://api.openai.com` |

Example multi-engine config:

```yaml
default_backend: vllm_local
fallback_backend: llamacpp
backends:
  vllm_local:
    type: vllm
    url: http://localhost:8000
  llamacpp:
    type: remote
    url: http://localhost:8001
  sglang:
    type: remote
    url: http://localhost:8002
  ollama:
    type: remote
    url: http://127.0.0.1:11434
```

**Operational logging:** The gateway logs startup, errors, fallback events, and stream failures via Python's `logging` module. Set log level with the `LOG_LEVEL` env var (default: `INFO`).

**Request body limit:** Requests larger than `MAX_BODY_BYTES` (default: 1MB) are rejected with `413`. Configure in `.env`.

See `.env.example` for all environment variables.

---

## Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /healthz` | Liveness probe |
| `GET /health` | Readiness probe with backend connectivity checks |
| `GET /v1/models` | List available models |
| `GET /v1/backends` | List backends with type and default status |
| `GET /metrics/summary` | JSON metrics summary |
| `POST /v1/chat/completions` | Chat completion (streaming and non-streaming) |

Prometheus scrape endpoint on `:9101/metrics`.

---

## Docker

```bash
docker compose up -d
# Gateway:    http://localhost:8080
# Nginx LB:   http://localhost:8780
# Prometheus: http://localhost:9090
# Grafana:    http://localhost:3000 (admin/admin)
```

The container runs as a non-root user with a built-in healthcheck. Prometheus and Grafana images are pinned to specific versions for reproducible builds.

---

## Documentation

- [Architecture](docs/architecture.md) — System design, request lifecycle, module map, streaming protocol
- [API Reference](docs/api-reference.md) — All endpoints with request/response formats and error codes
- [Configuration](docs/configuration.md) — config.yaml options, all environment variables, backend types
- [Observability](docs/observability.md) — Prometheus metrics, JSONL logging, OpenTelemetry tracing, cost tracking, Grafana dashboards
- [Engine Routing & A/B Testing](docs/engine-routing.md) — Technique resolution, engine routing strategies, vLLM engine profiles, A/B testing guide
- [Cloud Deployment](docs/cloud-deployment.md) — Lambda/Anyscale setup with SSH tunnel

---

## Experiment Results

Triage agent workload (7 golden incidents) through the full path: nginx → gateway → Jarvis vLLM (Nemotron Nano 3 30B, nvfp4, RTX 6000 Pro Blackwell 96GB).

| Arm | Technique | Concurrency | Success | p50 Latency | p95 Latency | Throughput | Category Acc |
|-----|-----------|-------------|---------|-------------|-------------|------------|-------------|
| 1 | baseline | 1 | 7/7 | 7.1s | 15.3s | 0.13 inc/s | 85.7% |
| 2 | chunked_prefill | 1 | 7/7 | 7.1s | 19.0s | 0.10 inc/s | 57.1% |
| 3 | baseline | 3 | 7/7 | 7.2s | 28.2s | 0.25 inc/s | 42.9% |
| 4 | chunked_prefill | 3 | 7/7 | 8.6s | 26.5s | 0.16 inc/s | 57.1% |

Raw benchmark (single-turn, 30 requests, concurrency=5, max_tokens=64):

| Technique | Throughput | p50 | p95 | Errors |
|-----------|-----------|-----|-----|--------|
| baseline | 5.9 req/s | 901ms | 1001ms | 0 |
| chunked_prefill | 6.3 req/s | 827ms | 1006ms | 0 |

**Pinned versions:** vLLM 0.8+, Nemotron Nano 3 30B nvfp4, Prometheus v3.3.0, Grafana 11.6.0.

---

## Reflection

The biggest surprise was that **chunked prefill did not improve agentic workload latency** — in fact it was slightly worse (7.1s vs 7.1s p50 sequential, but 19.0s vs 15.3s at p95). The hypothesis was that the recommend step's longer context (tool results injected into the prompt) would benefit from chunked prefill's pipelined prefill scheduling. In practice, the triage agent's prompts are short enough (~500 tokens) that the overhead of chunked scheduling exceeds its benefit. Chunked prefill shines with long shared prefixes (RAG, system prompts reused across requests), not short unique prompts.

The second insight was the **throughput vs latency tradeoff under concurrency**. At concurrency=3, wall-clock time dropped 47% (53s → 28s for baseline) but p95 latency nearly doubled (15s → 28s). This is the classic queuing effect — vLLM batches concurrent requests, improving GPU utilization but increasing per-request wait time. For an SRE triage agent where incidents arrive sporadically, sequential processing with lower p95 is the better operating point.

If I were to add one more piece of instrumentation, it would be **per-step Prometheus histograms** exported from the agent itself (not just the gateway). Currently step latencies are only in the JSON output. Exposing `triage_step_duration_seconds{step="classify",technique="baseline"}` as a Prometheus metric would let the Grafana dashboard show the agent's internal performance alongside gateway metrics, completing the end-to-end observability story.

# Cloud Deployment Guide

Deploy the inference gateway with a remote GPU-hosted vLLM backend via SSH tunnel.

## Architecture

```
[gesserit]                         [Jarvis (LAN) / Cloud GPU]
  gateway:8080  ─── LAN / SSH ───>  vLLM:8000
  prometheus:9090                    Nemotron Nano 3 30B nvfp4
  grafana:3000                       RTX 6000 Pro Blackwell 96GB
```

## 1. Launch a GPU Instance

### Lambda Cloud

1. Go to [Lambda Cloud](https://lambdalabs.com/service/gpu-cloud)
2. Launch an instance with at least 1x A10 or better
3. Note the SSH connection details (IP, username, key)

### Anyscale

1. Go to [Anyscale Console](https://console.anyscale.com)
2. Launch a GPU workspace
3. Note the SSH connection details

## 2. Install and Start vLLM

SSH into your instance and run:

```bash
# Option A: Run the setup script directly
bash scripts/setup_vllm_remote.sh

# Option B: Run via SSH pipe
ssh user@gpu-host 'bash -s' < scripts/setup_vllm_remote.sh

# Option C: Custom model
ssh user@gpu-host MODEL_NAME=nvidia/Nemotron-Nano-3-30B-Instruct bash -s < scripts/setup_vllm_remote.sh
```

The default model is `nvidia/Nemotron-Nano-3-30B-Instruct` (served as `nemotron-lora`). For testing on smaller GPUs, use `TinyLlama/TinyLlama-1.1B-Chat-v1.0`.

## 3. Open the SSH Tunnel

On your local machine:

```bash
SSH_HOST=ubuntu@<gpu-instance-ip> ./scripts/ssh_tunnel.sh
```

This forwards `localhost:8081` to the remote vLLM server on port 8000.

Environment variables:
- `SSH_HOST` (required) — e.g. `ubuntu@192.168.1.100`
- `SSH_KEY` — path to SSH private key (default: `~/.ssh/id_ed25519`)
- `LOCAL_PORT` — local port (default: `8081`)
- `REMOTE_PORT` — remote vLLM port (default: `8000`)

## 4. Configure the Gateway

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

Update `.env`:

```bash
PORT=8080
GPU_HOURLY_COST_USD=0.0   # Owned hardware (Jarvis); set to 1.10 for Lambda A10
```

## 5. Start the Gateway

### Local (development)

```bash
uv sync
uv run python app.py
```

### Docker (production)

```bash
docker compose up -d
```

## 6. Verify End-to-End

```bash
# Health check
curl http://localhost:8080/health

# Should show vllm_jarvis (or vllm_remote) backend as "ok"
# If it shows "error", check the SSH tunnel is running

# Send a request
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hello!"}]}'

# Check metrics
curl http://localhost:8080/metrics/summary

# Run a full workload
cd workloads && uv run python workload.py --technique baseline
```

## 7. Run Experiments

```bash
# Technique sweep
./scripts/run_experiments.sh

# A/B test
./scripts/run_server_ab.sh baseline beam_search
```

## Troubleshooting

### SSH tunnel drops

The tunnel script uses `ServerAliveInterval=30` to keep the connection alive. If it still drops:
- Check the GPU instance hasn't been terminated
- Try adding `-o TCPKeepAlive=yes` to the SSH command
- Use `tmux` or `screen` to persist the tunnel

### "backend_unavailable" errors

1. Verify the SSH tunnel is running: `curl http://localhost:8081/health`
2. Check vLLM is serving: SSH into the instance and check `curl localhost:8000/health`
3. If using Docker: the gateway container uses `host.docker.internal` to reach the tunnel. Update `config.yaml`:
   ```yaml
   vllm_remote:
     type: vllm
     url: http://host.docker.internal:8081
   ```

### vLLM out of memory

- Use a smaller model (`TinyLlama` or `Nemotron-Mini-4B` for smaller GPUs)
- Reduce `MAX_MODEL_LEN` in the setup script
- Check GPU memory: `nvidia-smi`

### Grafana shows no data

1. Check Prometheus targets: `http://localhost:9090/targets`
2. Verify gateway metrics: `curl http://localhost:9101/metrics`
3. Wait 15-30s for Prometheus to scrape

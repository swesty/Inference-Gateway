"""Mock investigation tools for the triage agent.

MOCK: All tools return synthetic data for demonstration purposes.
Real implementations would query journalctl, Prometheus, Docker API, etc.
Documented as mock per assignment requirements ("mocked tools OK if documented").

Each tool simulates realistic latency (50-200ms) so tool time is visible
in gateway metrics and the investigation step isn't instant.
"""

from __future__ import annotations

import asyncio
import random
import time

from triage_agent.models import Classification, Incident, ToolResult

# ---------------------------------------------------------------------------
# Synthetic log data keyed by incident category
# ---------------------------------------------------------------------------

_LOG_DATA: dict[str, list[str]] = {
    "container": [
        "Apr 06 02:14:01 gesserit kernel: Out of memory: Killed process 4821 (python) total-vm:8421532kB",
        "Apr 06 02:14:01 gesserit kernel: oom-kill:constraint=CONSTRAINT_MEMCG,cpuset=docker-a3f8c1.scope",
        "Apr 06 02:14:02 gesserit dockerd[1102]: container a3f8c1e9 exited with code 137 (OOM killed)",
        "Apr 06 02:14:03 gesserit systemd[1]: docker-a3f8c1.scope: Consumed 12.4G memory peak",
    ],
    "storage": [
        "Apr 06 03:30:15 gesserit systemd[1]: Starting Daily apt download activities...",
        "Apr 06 03:30:18 gesserit logrotate[8821]: error: /var/log/nginx/access.log: No space left on device",
        "Filesystem      Size  Used Avail Use% Mounted on",
        "/dev/nvme0n1p2  932G  878G   54G  94% /home/gesserit",
        "du -sh /home/gesserit/.cache/huggingface: 412G",
    ],
    "gateway": [
        '2026/04/06 02:45:11 [error] 1234#0: *5821 connect() failed (111: Connection refused) while connecting to upstream, client: 127.0.0.1, upstream: "http://127.0.0.1:8080/v1/chat/completions"',
        "Apr 06 02:45:11 gesserit nginx[1234]: 502 Bad Gateway - upstream prematurely closed connection",
        "Apr 06 02:45:12 gesserit gateway[3456]: ERROR - Backend vllm_local health check failed: ConnectError",
        "Apr 06 02:45:12 gesserit gateway[3456]: WARNING - Falling back to echo backend",
    ],
    "network": [
        "Apr 06 04:12:33 gesserit sshd[9102]: Connection to jarvis (192.168.1.50) port 22: Connection timed out",
        "Apr 06 04:12:33 gesserit systemd[1]: ssh-tunnel-jarvis.service: Main process exited, code=exited, status=255",
        "Apr 06 04:12:34 gesserit kernel: TCP: request_sock_TCP: Possible SYN flooding on port 8081",
        "ss -tlnp output: State Recv-Q Send-Q Local:8081 Peer:* -- LISTEN 0 0 (no process bound)",
    ],
    "monitoring": [
        'Apr 06 05:00:01 gesserit prometheus[2201]: msg="Scrape failed" target="http://localhost:9101/metrics" err="context deadline exceeded"',
        "Apr 06 05:00:16 gesserit prometheus[2201]: level=warn msg=\"Target is down\" job=inference-gateway",
        "Apr 06 05:01:02 gesserit grafana[2305]: level=error msg=\"Failed to execute query\" datasource=Prometheus err=\"client_error: query timed out in expression evaluation\"",
    ],
    "process": [
        "  PID USER      PR  NI    VIRT    RES    SHR S  %CPU  %MEM     TIME+ COMMAND",
        "18234 gesserit  20   0  4.2g  3.8g   12m R 398.0  12.1  47:23.91 pytest",
        "18235 gesserit  20   0  2.1g  1.9g    8m S  99.5   6.0  47:23.45 python",
        "Apr 06 01:55:00 gesserit cron[1]: pytest --maxfail=0 triggered by crontab, still running after 45min",
    ],
}

# ---------------------------------------------------------------------------
# Synthetic system metrics keyed by incident category
# ---------------------------------------------------------------------------

_METRICS_DATA: dict[str, list[str]] = {
    "container": [
        "CONTAINER        CPU %   MEM USAGE / LIMIT     MEM %   NET I/O         BLOCK I/O",
        "inference-gw     185%    7.8GiB / 8GiB         97.5%   1.2GB / 450MB   12GB / 3.1GB",
        "prometheus        12%    1.2GiB / 4GiB         30.0%   890MB / 120MB   4.5GB / 200MB",
        "docker_container_restart_count{name='inference-gateway'} 3",
    ],
    "storage": [
        "disk_used_bytes{mountpoint='/home/gesserit'} 942871674880",
        "disk_total_bytes{mountpoint='/home/gesserit'} 1000204886016",
        "disk_used_percent{mountpoint='/home/gesserit'} 94.2",
        "node_filesystem_avail_bytes{mountpoint='/home/gesserit'} 57333211136",
        "Largest dirs: .cache/huggingface(412G) .local/share/docker(189G) models/(145G)",
    ],
    "gateway": [
        "llm_gateway_requests_total{technique='baseline'} 1847",
        "llm_gateway_requests_total{technique='chunked_prefill'} 923",
        "request_duration_seconds{quantile='0.95'} 32.1  # was 2.1 yesterday",
        "up{job='inference-gateway'} 0",
        "nginx_http_requests_total{status='502'} 347  # last 5 min",
    ],
    "network": [
        "ssh_tunnel_status{target='jarvis'} 0  # down",
        "node_network_transmit_errs_total{device='eth0'} 142",
        "probe_success{target='192.168.1.50:8000'} 0",
        "tcp_retransmits{peer='192.168.1.50'} 89  # last 5 min",
        "ping_rtt_ms{target='jarvis'} timeout",
    ],
    "monitoring": [
        "prometheus_target_scrape_pool_targets{pool='inference-gateway'} 1",
        "prometheus_target_scrape_pool_sync_total{pool='inference-gateway'} 847",
        "scrape_duration_seconds{job='inference-gateway'} 15.2  # timeout at 10s",
        "prometheus_tsdb_head_series 248000  # high cardinality",
        "grafana_api_response_status{status='504'} 23",
    ],
    "process": [
        "node_cpu_seconds_total{mode='user'} rising at 4 cores saturated",
        "node_load1 6.8  node_load5 5.2  node_load15 3.1  # 4-core system",
        "process_cpu_seconds_total{pid='18234',cmd='pytest'} 2838.4",
        "process_resident_memory_bytes{pid='18234'} 4080218112  # 3.8 GiB",
        "node_memory_MemAvailable_bytes 2147483648  # only 2 GiB free",
    ],
}

# ---------------------------------------------------------------------------
# Runbook snippets keyed by category (only fetched for high/critical)
# ---------------------------------------------------------------------------

_RUNBOOKS: dict[str, str] = {
    "container": (
        "## Runbook: Container OOM\n"
        "1. Check which container was killed: `docker ps -a --filter exited=137`\n"
        "2. Review memory limits: `docker inspect <id> | jq '.[0].HostConfig.Memory'`\n"
        "3. Check host memory pressure: `free -h && cat /proc/meminfo | grep -i oom`\n"
        "4. Increase container memory limit or reduce batch size in gateway config\n"
        "5. Restart container: `docker compose up -d <service>`"
    ),
    "storage": (
        "## Runbook: Disk Pressure\n"
        "1. Identify largest directories: `du -sh /home/gesserit/*/ | sort -rh | head`\n"
        "2. Clear HuggingFace cache: `huggingface-cli delete-cache` (interactive)\n"
        "3. Prune Docker: `docker system prune -a --volumes`\n"
        "4. Check log rotation: `ls -lah /var/log/nginx/`\n"
        "5. Set up alert at 85% to prevent recurrence"
    ),
    "gateway": (
        "## Runbook: Gateway 502 Errors\n"
        "1. Check gateway process: `systemctl status inference-gateway` or `docker logs inference-gw`\n"
        "2. Verify vLLM backend: `curl -s http://localhost:8081/health`\n"
        "3. Check SSH tunnel: `ss -tlnp | grep 8081`\n"
        "4. If tunnel down: `SSH_HOST=jarvis ./scripts/ssh_tunnel.sh`\n"
        "5. If vLLM OOM: restart on Jarvis with lower --max-model-len"
    ),
    "network": (
        "## Runbook: SSH Tunnel Failure\n"
        "1. Check tunnel process: `pgrep -af 'ssh.*-L.*8081'`\n"
        "2. Test Jarvis reachability: `ping -c 3 192.168.1.50`\n"
        "3. Test SSH directly: `ssh -o ConnectTimeout=5 jarvis echo ok`\n"
        "4. Restart tunnel: `SSH_HOST=jarvis ./scripts/ssh_tunnel.sh`\n"
        "5. If Jarvis unreachable: check physical network, GPU host power"
    ),
    "monitoring": (
        "## Runbook: Monitoring Stack Issues\n"
        "1. Check Prometheus health: `curl localhost:9090/-/healthy`\n"
        "2. Check scrape targets: `curl -s localhost:9090/api/v1/targets | jq '.data.activeTargets[] | {target: .scrapeUrl, health}'`\n"
        "3. If high cardinality: check for label explosion in gateway metrics\n"
        "4. Restart Prometheus: `docker compose restart prometheus`\n"
        "5. Check Grafana datasource connectivity in UI"
    ),
    "process": (
        "## Runbook: Runaway Process\n"
        "1. Identify process: `top -bn1 | head -15`\n"
        "2. Check if it's a known cron job: `crontab -l | grep pytest`\n"
        "3. Send SIGTERM gracefully: `kill 18234`\n"
        "4. If unresponsive after 10s: `kill -9 18234`\n"
        "5. Review crontab for missing --timeout or --maxfail flags"
    ),
}


# ---------------------------------------------------------------------------
# Public tool functions
# ---------------------------------------------------------------------------


async def log_search(incident: Incident, classification: Classification) -> ToolResult:
    """MOCK: Search system logs relevant to the incident category.

    In production, this would query journalctl, Docker logs, or a log
    aggregator (Loki, ELK). Returns synthetic log lines matching the
    classified category.
    """
    start = time.perf_counter()
    await asyncio.sleep(random.uniform(0.05, 0.15))

    category = classification.category
    logs = _LOG_DATA.get(category, _LOG_DATA["process"])
    result_text = "\n".join(logs)

    elapsed_ms = (time.perf_counter() - start) * 1000
    return ToolResult(
        tool_name="log_search",
        query=f"category={category} incident={incident.id}",
        result=result_text,
        latency_ms=round(elapsed_ms, 1),
    )


async def system_metrics(
    incident: Incident, classification: Classification
) -> ToolResult:
    """MOCK: Fetch system and container metrics for the incident category.

    In production, this would query Prometheus, node_exporter, nvidia-smi,
    or Docker stats. Returns synthetic metric lines.
    """
    start = time.perf_counter()
    await asyncio.sleep(random.uniform(0.05, 0.10))

    category = classification.category
    metrics = _METRICS_DATA.get(category, _METRICS_DATA["process"])
    result_text = "\n".join(metrics)

    elapsed_ms = (time.perf_counter() - start) * 1000
    return ToolResult(
        tool_name="system_metrics",
        query=f"category={category} incident={incident.id}",
        result=result_text,
        latency_ms=round(elapsed_ms, 1),
    )


async def runbook_fetch(
    incident: Incident, classification: Classification
) -> ToolResult:
    """MOCK: Fetch the relevant remediation runbook for this incident.

    In production, this would query a wiki, Confluence, or runbook repo.
    Only called for high/critical severity incidents.
    """
    start = time.perf_counter()
    await asyncio.sleep(random.uniform(0.10, 0.20))

    category = classification.category
    runbook = _RUNBOOKS.get(
        category,
        f"## No specific runbook for '{category}'\n"
        "1. Gather logs and metrics for the affected component\n"
        "2. Check recent deployments or config changes\n"
        "3. Escalate to on-call engineer with collected evidence",
    )

    elapsed_ms = (time.perf_counter() - start) * 1000
    return ToolResult(
        tool_name="runbook_fetch",
        query=f"category={category} severity={classification.severity}",
        result=runbook,
        latency_ms=round(elapsed_ms, 1),
    )

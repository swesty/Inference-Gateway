"""Structured per-request JSONL logging with daily rotation."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


class RequestLogger:
    """Logs one JSON line per request to a daily-rotated file."""

    def __init__(self) -> None:
        self.log_dir = os.environ.get("GATEWAY_METRICS_LOG_DIR", "logs/gateway")
        self.disabled = self.log_dir == "-"

    def log(
        self,
        *,
        request_id: str,
        technique: str,
        server_profile: str,
        backend: str,
        duration_s: float,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
        trace_id: str | None,
        stream: bool,
        status_code: int,
    ) -> None:
        if self.disabled:
            return

        now = datetime.now(timezone.utc)
        entry = {
            "timestamp": now.isoformat(),
            "request_id": request_id,
            "technique": technique,
            "server_profile": server_profile,
            "backend": backend,
            "duration_s": round(duration_s, 6),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost_usd": round(cost_usd, 8),
            "trace_id": trace_id,
            "stream": stream,
            "status_code": status_code,
        }

        log_path = Path(self.log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        filename = log_path / f"gateway_metrics_{now.strftime('%Y-%m-%d')}.jsonl"
        with open(filename, "a") as f:
            f.write(json.dumps(entry) + "\n")
            f.flush()

"""Per-request GPU cost estimation."""

from __future__ import annotations

import os


def get_gpu_hourly_cost() -> float:
    """Return GPU hourly cost from env var, or 0.0 if unset."""
    return float(os.environ.get("GPU_HOURLY_COST_USD", "0.0"))


def compute_cost(duration_s: float) -> float:
    """Compute estimated GPU cost for a request based on its duration."""
    hourly_rate = get_gpu_hourly_cost()
    return (duration_s / 3600) * hourly_rate

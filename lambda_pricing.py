"""Optional Lambda Cloud API pricing lookup."""

from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger("inference_gateway")

_cached_price: float | None = None
_fetched: bool = False


def fetch_lambda_pricing() -> float | None:
    """Fetch GPU hourly price from Lambda Cloud API.

    Returns the hourly price in USD, or None if unavailable.
    Result is cached after first call.
    """
    global _cached_price, _fetched
    if _fetched:
        return _cached_price

    _fetched = True
    api_key = os.environ.get("LAMBDA_API_KEY")
    if not api_key:
        return None

    try:
        resp = httpx.get(
            "https://cloud.lambdalabs.com/api/v1/instance-types",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        # Find the first available GPU instance price
        for instance_type in data.get("data", {}).values():
            price = instance_type.get("instance_type", {}).get(
                "price_cents_per_hour"
            )
            if price is not None:
                _cached_price = price / 100.0
                return _cached_price
    except Exception as e:
        logger.warning("Failed to fetch Lambda pricing: %s", e)

    return None

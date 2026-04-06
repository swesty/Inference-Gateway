"""Exponential-backoff retry wrapper for async LLM calls."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx

log = logging.getLogger(__name__)

T = TypeVar("T")

RETRYABLE_STATUS_CODES = {429, 502, 503, 504}


async def with_retry(
    coro_factory: Callable[[], Awaitable[T]],
    *,
    step_name: str = "",
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    timeout: float = 60.0,
) -> T:
    """Execute *coro_factory()* with retries on transient failures.

    *coro_factory* is called fresh on each attempt (important because
    LangChain coroutines are single-use).
    """
    last_exc: BaseException | None = None

    for attempt in range(max_retries + 1):
        try:
            return await asyncio.wait_for(coro_factory(), timeout=timeout)

        except asyncio.TimeoutError:
            last_exc = TimeoutError(f"{step_name}: timed out after {timeout}s")
            log.warning("%s attempt %d/%d timed out", step_name, attempt + 1, max_retries + 1)

        except httpx.ConnectError as exc:
            last_exc = exc
            log.warning("%s attempt %d/%d connect error: %s", step_name, attempt + 1, max_retries + 1, exc)

        except httpx.TimeoutException as exc:
            last_exc = exc
            log.warning("%s attempt %d/%d httpx timeout: %s", step_name, attempt + 1, max_retries + 1, exc)

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in RETRYABLE_STATUS_CODES:
                raise  # 400, 401, 422 etc. — not retryable
            last_exc = exc
            log.warning(
                "%s attempt %d/%d got %d",
                step_name, attempt + 1, max_retries + 1, exc.response.status_code,
            )

        except Exception as exc:
            # Catch OpenAI SDK errors that wrap HTTP status codes
            status = getattr(exc, "status_code", None)
            if status and status in RETRYABLE_STATUS_CODES:
                last_exc = exc
                log.warning("%s attempt %d/%d API error %d", step_name, attempt + 1, max_retries + 1, status)
            else:
                raise

        if attempt < max_retries:
            delay = min(base_delay * (2 ** attempt) + random.uniform(0, 0.5), max_delay)
            log.info("%s retrying in %.1fs", step_name, delay)
            await asyncio.sleep(delay)

    raise RuntimeError(f"{step_name}: failed after {max_retries + 1} attempts") from last_exc

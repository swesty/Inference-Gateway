#!/usr/bin/env python3
"""Gateway throughput and latency benchmark.

Sends concurrent requests to measure raw gateway performance
independent of LLM inference time. Best used with echo backend
for gateway-only overhead, or with a real backend for end-to-end.

Usage:
    uv run python scripts/benchmark.py
    uv run python scripts/benchmark.py --concurrency 50 --requests 200
    uv run python scripts/benchmark.py --stream --model tinyllama
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time

import httpx


async def send_request(
    client: httpx.AsyncClient,
    url: str,
    body: dict,
    technique: str,
    stream: bool,
) -> dict:
    """Send a single request and return timing info."""
    headers = {
        "Content-Type": "application/json",
        "X-Technique": technique,
    }
    start = time.perf_counter()
    ttft = None

    if stream:
        body["stream"] = True
        req = client.build_request("POST", url, json=body, headers=headers)
        resp = await client.send(req, stream=True)
        chunks = 0
        async for line in resp.aiter_lines():
            if line.startswith("data:"):
                if ttft is None:
                    ttft = time.perf_counter() - start
                chunks += 1
        await resp.aclose()
        duration = time.perf_counter() - start
        return {"duration": duration, "ttft": ttft, "chunks": chunks, "status": resp.status_code}
    else:
        resp = await client.post(url, json=body, headers=headers)
        duration = time.perf_counter() - start
        return {"duration": duration, "ttft": None, "chunks": 0, "status": resp.status_code}


async def run_benchmark(args: argparse.Namespace) -> None:
    url = f"{args.gateway_url}/v1/chat/completions"
    body = {
        "messages": [{"role": "user", "content": "Say hello in one sentence."}],
        "max_tokens": args.max_tokens,
    }
    if args.model:
        body["model"] = args.model

    async with httpx.AsyncClient(timeout=120) as client:
        # Warmup
        print(f"Warming up ({args.warmup} requests)...")
        warmup_tasks = [
            send_request(client, url, dict(body), args.technique, args.stream)
            for _ in range(args.warmup)
        ]
        await asyncio.gather(*warmup_tasks)

        # Benchmark
        print(f"Running {args.requests} requests at concurrency {args.concurrency}...")
        semaphore = asyncio.Semaphore(args.concurrency)
        results = []

        async def bounded_request():
            async with semaphore:
                return await send_request(client, url, dict(body), args.technique, args.stream)

        start_time = time.perf_counter()
        tasks = [bounded_request() for _ in range(args.requests)]
        results = await asyncio.gather(*tasks)
        wall_time = time.perf_counter() - start_time

    # Analyze
    durations = [r["duration"] for r in results]
    successes = sum(1 for r in results if r["status"] == 200)
    errors = len(results) - successes
    durations_sorted = sorted(durations)

    print(f"\n{'=' * 50}")
    print(f"Benchmark Results")
    print(f"{'=' * 50}")
    print(f"Gateway:       {args.gateway_url}")
    print(f"Model:         {args.model or '(default)'}")
    print(f"Technique:     {args.technique}")
    print(f"Streaming:     {args.stream}")
    print(f"Concurrency:   {args.concurrency}")
    print(f"Total reqs:    {args.requests}")
    print(f"Successes:     {successes}")
    print(f"Errors:        {errors}")
    print(f"Wall time:     {wall_time:.2f}s")
    print(f"Throughput:    {args.requests / wall_time:.1f} req/s")
    print()
    print(f"Latency:")
    print(f"  Min:         {min(durations) * 1000:.1f}ms")
    print(f"  p50:         {durations_sorted[len(durations_sorted) // 2] * 1000:.1f}ms")
    print(f"  p95:         {durations_sorted[int(len(durations_sorted) * 0.95)] * 1000:.1f}ms")
    print(f"  p99:         {durations_sorted[int(len(durations_sorted) * 0.99)] * 1000:.1f}ms")
    print(f"  Max:         {max(durations) * 1000:.1f}ms")
    print(f"  Avg:         {statistics.mean(durations) * 1000:.1f}ms")

    if args.stream:
        ttfts = [r["ttft"] for r in results if r["ttft"] is not None]
        if ttfts:
            ttfts_sorted = sorted(ttfts)
            avg_chunks = statistics.mean(r["chunks"] for r in results)
            print()
            print(f"TTFT:")
            print(f"  Min:         {min(ttfts) * 1000:.1f}ms")
            print(f"  p50:         {ttfts_sorted[len(ttfts_sorted) // 2] * 1000:.1f}ms")
            print(f"  p95:         {ttfts_sorted[int(len(ttfts_sorted) * 0.95)] * 1000:.1f}ms")
            print(f"  Avg:         {statistics.mean(ttfts) * 1000:.1f}ms")
            print(f"  Avg chunks:  {avg_chunks:.0f}")
    print(f"{'=' * 50}")


def main():
    parser = argparse.ArgumentParser(description="Gateway throughput benchmark")
    parser.add_argument("--gateway-url", default="http://localhost:8080", help="Gateway URL")
    parser.add_argument("--requests", type=int, default=100, help="Total requests (default: 100)")
    parser.add_argument("--concurrency", type=int, default=20, help="Concurrent requests (default: 20)")
    parser.add_argument("--warmup", type=int, default=5, help="Warmup requests (default: 5)")
    parser.add_argument("--max-tokens", type=int, default=32, help="Max tokens per request (default: 32)")
    parser.add_argument("--model", default=None, help="Model name (omit for default backend)")
    parser.add_argument("--technique", default="baseline", help="Technique label (default: baseline)")
    parser.add_argument("--stream", action="store_true", help="Use streaming")
    args = parser.parse_args()

    asyncio.run(run_benchmark(args))


if __name__ == "__main__":
    main()

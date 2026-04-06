"""CLI entry point for the triage agent."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
import urllib.error
import urllib.request

from triage_agent.agent import AgentConfig, run_triage
from triage_agent.incidents import load_incidents
from triage_agent.metrics_collector import TriageMetrics


def wait_for_gateway(base_url: str, timeout: int = 30) -> bool:
    """Poll /healthz until the gateway is ready."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/healthz", timeout=2) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(1)
    return False


async def _run(args: argparse.Namespace) -> None:
    incidents = load_incidents(args.incidents_file)
    print(f"Loaded {len(incidents)} incidents")

    config = AgentConfig(
        gateway_url=args.gateway_url,
        model=args.model,
        technique_override=args.technique,
        max_retries=args.max_retries,
    )

    metrics = TriageMetrics()
    semaphore = asyncio.Semaphore(args.concurrency)

    async def _process(incident):
        async with semaphore:
            return await run_triage(incident, config), incident

    wall_start = time.perf_counter()
    tasks = [_process(inc) for inc in incidents]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    metrics.wall_clock = time.perf_counter() - wall_start

    for result in results:
        if isinstance(result, Exception):
            logging.error("Unexpected error: %s", result)
            continue
        report, incident = result
        metrics.add(report, incident)

    metrics.print_table()

    if args.output:
        metrics.save(args.output)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ops/Triage agent — monitors gesserit via inference gateway on Jarvis"
    )
    parser.add_argument("--gateway-url", default="http://localhost:8080",
                        help="Gateway base URL (default: http://localhost:8080)")
    parser.add_argument("--model", default="nemotron",
                        help="Model name to request (default: nemotron)")
    parser.add_argument("--technique", default=None,
                        help="Override all steps to use this technique (default: per-step routing)")
    parser.add_argument("--concurrency", type=int, default=1,
                        help="Max incidents to process concurrently (default: 1)")
    parser.add_argument("--incidents-file", default=None,
                        help="Path to incidents JSON (default: built-in golden set)")
    parser.add_argument("--max-retries", type=int, default=3,
                        help="Max retries per LLM step (default: 3)")
    parser.add_argument("--no-wait", action="store_true",
                        help="Skip gateway health check polling")
    parser.add_argument("--output", default=None,
                        help="Write full results JSON to this path")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if not args.no_wait:
        print(f"Waiting for gateway at {args.gateway_url}...")
        if not wait_for_gateway(args.gateway_url):
            print("ERROR: Gateway not reachable", file=sys.stderr)
            sys.exit(1)
        print("Gateway is ready.\n")

    asyncio.run(_run(args))

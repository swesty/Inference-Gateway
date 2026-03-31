#!/usr/bin/env python3
"""LangChain two-step workload: Researcher -> Writer.

Connects to the inference gateway via OpenAI-compatible API.
Sends X-Technique header for technique labeling.

Usage:
    uv run python workload.py --technique baseline
    uv run python workload.py --technique beam_search --topic "quantum computing"
"""

from __future__ import annotations

import argparse
import sys
import time

import urllib.request
import urllib.error


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


def run_workload(base_url: str, technique: str, topic: str) -> None:
    """Run a two-step Researcher -> Writer chain."""
    from langchain_openai import ChatOpenAI
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import StrOutputParser

    llm = ChatOpenAI(
        base_url=f"{base_url}/v1",
        api_key="not-needed",
        default_headers={"X-Technique": technique},
    )

    # Step 1: Researcher — gather key facts
    researcher_prompt = ChatPromptTemplate.from_messages([
        ("system", "You are a research assistant. List 3-5 key facts about the given topic."),
        ("user", "Topic: {topic}"),
    ])
    researcher_chain = researcher_prompt | llm | StrOutputParser()

    print(f"[Researcher] Gathering facts about: {topic}")
    facts = researcher_chain.invoke({"topic": topic})
    print(f"[Researcher] Facts:\n{facts}\n")

    # Step 2: Writer — synthesize into a paragraph
    writer_prompt = ChatPromptTemplate.from_messages([
        ("system", "You are a technical writer. Synthesize the given facts into a clear, concise paragraph."),
        ("user", "Facts:\n{facts}\n\nWrite a summary paragraph."),
    ])
    writer_chain = writer_prompt | llm | StrOutputParser()

    print("[Writer] Synthesizing summary...")
    summary = writer_chain.invoke({"facts": facts})
    print(f"[Writer] Summary:\n{summary}\n")


def main():
    parser = argparse.ArgumentParser(description="LangChain workload for inference gateway")
    parser.add_argument("--technique", default="baseline", help="Technique label (default: baseline)")
    parser.add_argument("--topic", default="large language models", help="Research topic")
    parser.add_argument("--gateway-url", default="http://localhost:8080", help="Gateway base URL")
    parser.add_argument("--no-wait", action="store_true", help="Skip health check polling")
    args = parser.parse_args()

    if not args.no_wait:
        print(f"Waiting for gateway at {args.gateway_url}...")
        if not wait_for_gateway(args.gateway_url):
            print("ERROR: Gateway not reachable", file=sys.stderr)
            sys.exit(1)
        print("Gateway is ready.\n")

    run_workload(args.gateway_url, args.technique, args.topic)


if __name__ == "__main__":
    main()

"""LLM factory — creates ChatOpenAI instances with per-step technique routing."""

from __future__ import annotations

from langchain_openai import ChatOpenAI


# Default technique for each agent step.  Overridden by --technique CLI flag.
STEP_TECHNIQUES: dict[str, str] = {
    "classify": "baseline",
    "recommend": "chunked_prefill",
    "summarize": "baseline",
}


def make_llm(
    base_url: str,
    model: str,
    technique: str,
    *,
    streaming: bool = False,
    timeout: float = 30.0,
    request_id: str | None = None,
) -> ChatOpenAI:
    """Build a ChatOpenAI pointed at the inference gateway with the right headers."""
    headers: dict[str, str] = {"X-Technique": technique}
    if request_id:
        headers["X-Request-ID"] = request_id

    return ChatOpenAI(
        base_url=f"{base_url}/v1",
        api_key="not-needed",
        model=model,
        streaming=streaming,
        default_headers=headers,
        request_timeout=timeout,
    )

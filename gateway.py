"""Core logic for the inference gateway — no framework imports."""

import time
import uuid
from typing import Any


MODEL_NAME = "echo"


class BackendJSONError(Exception):
    """Raised when the backend returns a non-JSON response."""


ALLOWED_FIELDS = {"messages", "stream", "max_tokens", "model", "temperature", "stop"}


# ---------------------------------------------------------------------------
# Request validation & normalization
# ---------------------------------------------------------------------------


def validate_request_body(body: dict) -> dict | None:
    """Return an error dict if *body* is invalid, or ``None`` if it's OK."""
    # messages — required, list of dicts with role (str) and content (str)
    messages = body.get("messages")
    if not isinstance(messages, list):
        return {"error": "invalid_messages"}
    for msg in messages:
        if (
            not isinstance(msg, dict)
            or not isinstance(msg.get("role"), str)
            or not isinstance(msg.get("content"), str)
        ):
            return {"error": "invalid_messages"}

    # stream — optional, must be bool
    if "stream" in body and not isinstance(body["stream"], bool):
        return {"error": "invalid_stream"}

    # max_tokens — optional, int in [1, 128000]
    if "max_tokens" in body:
        mt = body["max_tokens"]
        if not isinstance(mt, int) or isinstance(mt, bool) or not (1 <= mt <= 128000):
            return {"error": "invalid_max_tokens"}

    # model — optional, must be str
    if "model" in body and not isinstance(body["model"], str):
        return {"error": "invalid_model"}

    # temperature — optional, int|float in [0.0, 2.0]
    if "temperature" in body:
        t = body["temperature"]
        if (
            not isinstance(t, (int, float))
            or isinstance(t, bool)
            or not (0.0 <= t <= 2.0)
        ):
            return {"error": "invalid_temperature"}

    # stop — optional, str or list[str]
    if "stop" in body:
        s = body["stop"]
        if isinstance(s, str):
            pass
        elif isinstance(s, list) and all(isinstance(i, str) for i in s):
            pass
        else:
            return {"error": "invalid_stop"}

    return None


def normalize_request_body(body: dict) -> dict:
    """Return a new dict with only recognised fields and sensible defaults."""
    out: dict = {k: v for k, v in body.items() if k in ALLOWED_FIELDS}
    out.setdefault("stream", False)
    return out


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------


def resolve_request_id(headers: dict[str, str]) -> str:
    """Return an existing request ID from headers or generate a new UUID."""
    for key in ("x-request-id", "request-id"):
        value = headers.get(key)
        if value:
            return value
    return str(uuid.uuid4())


def extract_prompt(body: dict[str, Any]) -> str:
    """Pull the last user message content from the messages list."""
    messages = body.get("messages", [])
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return msg.get("content", "")
    return ""


def count_tokens(text: str) -> int:
    """Rough token count heuristic: ~4 chars per token, minimum 1."""
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------


def build_response(request_id: str, content: str, prompt: str) -> dict[str, Any]:
    """Build a full OpenAI-compatible chat completion response."""
    return {
        "id": request_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": MODEL_NAME,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": count_tokens(prompt),
            "completion_tokens": count_tokens(content),
            "total_tokens": count_tokens(prompt) + count_tokens(content),
        },
    }


def build_sse_chunk(
    request_id: str, content: str | None, finish_reason: str | None
) -> str:
    """Build a single SSE `data:` line for streaming."""
    import json

    delta: dict[str, str] = {}
    if content is not None:
        delta["content"] = content

    chunk = {
        "id": request_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": MODEL_NAME,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }
    return f"data: {json.dumps(chunk)}\n\n"



from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import gateway
from .backend import Backend


class EchoBackend(Backend):
    def __init__(self, name: str = "echo") -> None:
        super().__init__(name, type="echo")

    async def generate(
        self, body: dict[str, Any], request_id: str, stream: bool = False
    ) -> dict[str, Any] | AsyncGenerator[str, None]:
        prompt = gateway.extract_prompt(body)
        if stream:
            return self._stream(prompt, request_id)
        content = self._echo(prompt)
        return gateway.build_response(request_id, content, prompt)

    async def _stream(
        self, prompt: str, request_id: str
    ) -> AsyncGenerator[str, None]:
        yield gateway.build_sse_chunk(request_id, self._echo(prompt), None)
        yield gateway.build_sse_chunk(request_id, None, "stop")
        yield "data: [DONE]\n\n"

    def _echo(self, prompt: str) -> str:
        """Return the echo reply for a prompt."""
        return f"Echo: {prompt}"

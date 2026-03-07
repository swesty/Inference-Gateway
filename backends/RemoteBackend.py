from __future__ import annotations

import json
import httpx
import os
from collections.abc import AsyncGenerator
from typing import Any

import gateway
from .backend import Backend

BACKEND_URL = os.environ.get("BACKEND_URL", "")


class RemoteBackend(Backend):
    async def generate(
        self, prompt: str, request_id: str, stream: bool = False
    ) -> str | AsyncGenerator[str, None]:
        if stream:
            return self._forward_stream(prompt, request_id)
        return await self._forward(prompt, request_id)

    async def _forward_stream(
        self, body: dict[str, Any], request_id: str
    ) -> AsyncGenerator[str, None]:
        """Forward a streaming request to BACKEND_URL and return an async generator."""

        url = f"{BACKEND_URL}/v1/chat/completions"
        headers = {"Content-Type": "application/json", "X-Request-ID": request_id}

        # Eager connect — errors propagate before StreamingResponse starts
        client = httpx.AsyncClient(timeout=120)
        request = client.build_request("POST", url, json=body, headers=headers)
        resp = await client.send(request, stream=True)
        try:
            resp.raise_for_status()
        except Exception:
            await resp.aclose()
            await client.aclose()
            raise
        return self._stream_lines(client, resp)

    async def _forward(self, body: dict[str, Any], request_id: str) -> str:
        """Forward non-streaming request to BACKEND_URL and return string."""

        url = f"{BACKEND_URL}/v1/chat/completions"
        headers = {"Content-Type": "application/json", "X-Request-ID": request_id}

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            try:
                return resp.json()
            except ValueError as err:
                raise gateway.BackendJSONError() from err

    async def _stream_lines(
        self, client: httpx.AsyncClient, resp: httpx.Response
    ) -> AsyncGenerator[str, None]:
        """Yield SSE data lines, then close the connection."""
        try:
            async for line in resp.aiter_lines():
                if line and line.startswith("data:"):
                    yield line + "\n\n"
        finally:
            await resp.aclose()
            await client.aclose()

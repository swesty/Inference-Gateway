from __future__ import annotations

import httpx
from collections.abc import AsyncGenerator
from typing import Any

import gateway
from .backend import Backend


class RemoteBackend(Backend):
    def __init__(self, name: str, url: str, type: str = "remote") -> None:
        super().__init__(name, type=type)
        self.url = url

    async def health_check(self) -> dict[str, str]:
        """Check backend connectivity via GET /health."""
        if "YOUR_" in self.url:
            return {"status": "error", "detail": "placeholder URL"}
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.url}/health")
                content_type = resp.headers.get("content-type", "")
                if "text/html" in content_type:
                    return {"status": "error", "detail": "HTML response (not an API)"}
                resp.raise_for_status()
                return {"status": "ok"}
        except httpx.ConnectError:
            return {"status": "error", "detail": "connection refused"}
        except httpx.TimeoutException:
            return {"status": "error", "detail": "timeout"}
        except httpx.HTTPStatusError as exc:
            return {"status": "error", "detail": f"HTTP {exc.response.status_code}"}

    async def generate(
        self, body: dict[str, Any], request_id: str, stream: bool = False
    ) -> str | AsyncGenerator[str, None]:
        if stream:
            return self._forward_stream(body, request_id)
        return await self._forward(body, request_id)

    async def _forward(self, body: dict[str, Any], request_id: str) -> dict[str, Any]:
        """Forward non-streaming request and return parsed JSON."""
        url = f"{self.url}/v1/chat/completions"
        headers = {"Content-Type": "application/json", "X-Request-ID": request_id}

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            try:
                return resp.json()
            except ValueError as err:
                raise gateway.BackendJSONError() from err

    async def _forward_stream(
        self, body: dict[str, Any], request_id: str
    ) -> AsyncGenerator[str, None]:
        """Forward a streaming request and return an async generator."""
        url = f"{self.url}/v1/chat/completions"
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

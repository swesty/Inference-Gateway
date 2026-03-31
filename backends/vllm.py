from __future__ import annotations

import os
from typing import Any
from collections.abc import AsyncGenerator

import httpx

import gateway
from .remote import RemoteBackend


class VllmBackend(RemoteBackend):
    """Backend for vLLM-hosted models with beam search and TLS support."""

    def __init__(self, name: str, url: str) -> None:
        super().__init__(name, url, type="vllm")
        self.tls_verify = os.environ.get("VLLM_TLS_VERIFY", "true").lower() != "false"

    def _prepare_body(self, body: dict[str, Any]) -> dict[str, Any]:
        """Prepare request body, injecting vLLM-specific parameters."""
        out = dict(body)
        technique = out.pop("technique", None)
        if technique == "beam_search":
            out["use_beam_search"] = True
            out["best_of"] = 4
        return out

    async def _forward(self, body: dict[str, Any], request_id: str) -> dict[str, Any]:
        url = f"{self.url}/v1/chat/completions"
        headers = {"Content-Type": "application/json", "X-Request-ID": request_id}
        body = self._prepare_body(body)

        async with httpx.AsyncClient(timeout=120, verify=self.tls_verify) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            try:
                return resp.json()
            except ValueError as err:
                raise gateway.BackendJSONError() from err

    async def _forward_stream(
        self, body: dict[str, Any], request_id: str
    ) -> AsyncGenerator[str, None]:
        url = f"{self.url}/v1/chat/completions"
        headers = {"Content-Type": "application/json", "X-Request-ID": request_id}
        body = self._prepare_body(body)

        client = httpx.AsyncClient(timeout=120, verify=self.tls_verify)
        request = client.build_request("POST", url, json=body, headers=headers)
        resp = await client.send(request, stream=True)
        try:
            resp.raise_for_status()
        except Exception:
            await resp.aclose()
            await client.aclose()
            raise
        return self._stream_lines(client, resp)

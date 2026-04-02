from __future__ import annotations

import os
from typing import Any

from .remote import RemoteBackend


class VllmBackend(RemoteBackend):
    """Backend for vLLM-hosted models with beam search and TLS support."""

    def __init__(self, name: str, url: str) -> None:
        tls_verify = os.environ.get("VLLM_TLS_VERIFY", "true").lower() != "false"
        super().__init__(name, url, type="vllm", verify=tls_verify)

    def _prepare_body(self, body: dict[str, Any]) -> dict[str, Any]:
        """Prepare request body, injecting vLLM-specific parameters."""
        out = dict(body)
        technique = out.pop("technique", None)
        if technique == "beam_search":
            out["use_beam_search"] = True
            out["best_of"] = 4
        return out

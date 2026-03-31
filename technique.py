"""Technique resolution and optional engine routing."""

from __future__ import annotations

import json
import os
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backends import Backend
    from config import BackendRegistry

# Technique → port offset for auto engine routing
_PORT_OFFSETS: dict[str, int] = {
    "baseline": 0,
    "chunked_prefill": 1,
    "speculative": 2,
    "beam_search": 3,
}


def resolve_technique(headers: dict[str, str], body: dict) -> str:
    """Resolve the technique label for a request.

    Priority: X-Technique header > metadata.technique in body > "baseline".
    """
    header_val = headers.get("x-technique")
    if header_val:
        return header_val

    metadata = body.get("metadata")
    if isinstance(metadata, dict):
        tech = metadata.get("technique")
        if isinstance(tech, str) and tech:
            return tech

    return "baseline"


def get_server_profile() -> str:
    """Return the server profile label from env, default "default"."""
    return os.environ.get("VLLM_SERVER_PROFILE", "default")


def resolve_engine_backend(technique: str, registry: BackendRegistry) -> Backend | None:
    """Optionally override backend selection based on technique.

    Returns a VllmBackend if engine routing env vars are configured,
    or None to use normal registry lookup.
    """
    from backends import VllmBackend

    # Explicit JSON mapping takes priority
    map_json = os.environ.get("VLLM_BACKEND_MAP_JSON")
    if map_json:
        mapping = json.loads(map_json)
        url = mapping.get(technique)
        if url:
            return VllmBackend(f"engine-{technique}", url)
        return None

    # Auto port-offset routing
    if os.environ.get("VLLM_AUTO_ENGINE_ROUTING", "").lower() == "true":
        default = registry.get_default()
        if not hasattr(default, "url"):
            return None
        offset = _PORT_OFFSETS.get(technique, 0)
        base_url = re.sub(r":(\d+)$", lambda m: f":{int(m.group(1)) + offset}", default.url)
        if base_url == default.url and offset != 0:
            return None
        return VllmBackend(f"engine-{technique}", base_url)

    return None

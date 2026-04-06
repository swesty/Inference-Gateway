"""Golden-set incident loader."""

from __future__ import annotations

import json
from pathlib import Path

from triage_agent.models import Incident

_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "golden_incidents.json"


def load_incidents(path: str | Path | None = None) -> list[Incident]:
    """Load incidents from a JSON file (defaults to built-in golden set)."""
    p = Path(path) if path else _DEFAULT_PATH
    with open(p) as f:
        data = json.load(f)
    return [Incident(**item) for item in data]

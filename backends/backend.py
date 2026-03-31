from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import Any


class Backend(ABC):
    def __init__(self, name: str, type: str) -> None:
        self.name = name
        self.type = type

    @abstractmethod
    async def generate(
        self, body: dict[str, Any], request_id: str, stream: bool = False
    ) -> str | AsyncGenerator[str, None]:
        raise NotImplementedError

    async def health_check(self) -> dict[str, str]:
        """Check backend health. Override for remote connectivity checks."""
        return {"status": "ok"}

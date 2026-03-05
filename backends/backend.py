from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import Any


class Backend(ABC):
    def __init__(self, name: str) -> None:
        self.name = name

    @abstractmethod
    async def generate(
        self, body: dict[str, Any], request_id: str, stream: bool = False
    ) -> str | AsyncGenerator[str, None]:
        raise NotImplementedError

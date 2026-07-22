from abc import ABC, abstractmethod
from typing import Any


class IntegrationClient(ABC):
    system_name: str

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        raise NotImplementedError

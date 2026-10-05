from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any


class ProviderState(str, Enum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OFFLINE = "offline"


class BaseProvider(ABC):
    name: str
    enabled: bool = True
    state: ProviderState = ProviderState.UNKNOWN

    def __init__(self, name: str, enabled: bool = True, state: ProviderState = ProviderState.UNKNOWN):
        self.name = name
        self.enabled = enabled
        self.state = state

    @property
    def is_healthy(self) -> bool:
        return self.enabled and self.state == ProviderState.HEALTHY

    @abstractmethod
    def fetch(self) -> Any:
        raise NotImplementedError

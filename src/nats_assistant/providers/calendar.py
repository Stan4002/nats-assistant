from abc import ABC, abstractmethod
from datetime import datetime

from nats_assistant.core.calendar import CalendarEventBatch, CalendarState


class CalendarProviderError(Exception):
    def __init__(self, status: CalendarState):
        self.status = status
        super().__init__("Calendar provider unavailable")


class CalendarProvider(ABC):
    name: str

    @abstractmethod
    def availability(self) -> CalendarState:
        """Local readiness check; must not start authentication."""
        raise NotImplementedError

    @abstractmethod
    def list_events(self, start: datetime, end: datetime) -> CalendarEventBatch:
        """Return normalized events overlapping [start, end), with bounded I/O."""
        raise NotImplementedError

import logging
import threading
import time
from datetime import datetime, time as dt_time, timedelta, timezone
from zoneinfo import ZoneInfo

from nats_assistant.config import Settings
from nats_assistant.core.calendar import CalendarEventBatch, CalendarState, CalendarSummary
from nats_assistant.core.calendar_context import build_calendar_summary
from nats_assistant.providers.calendar import CalendarProvider, CalendarProviderError

logger = logging.getLogger(__name__)


class CalendarCache:
    def __init__(self, provider: CalendarProvider | None, settings: Settings):
        self.provider = provider
        self.settings = settings
        self.batch: CalendarEventBatch | None = None
        self.fetched_at: datetime | None = None
        self.last_state: CalendarState = CalendarState.NOT_CONNECTED
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._poll_interval = settings.calendar_refresh_seconds
        self._retry_delay = 5.0
        self._last_logged_state: CalendarState | None = None

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.settings.timezone)

    def _record_state(self, state: CalendarState) -> None:
        if self._last_logged_state != state:
            logger.info("Calendar state changed: %s -> %s", self._last_logged_state or "unknown", state)
            self._last_logged_state = state
        self.last_state = state

    def _window_for(self, now: datetime) -> tuple[datetime, datetime]:
        start_local = datetime.combine(now.date(), dt_time.min, tzinfo=now.tzinfo or self.timezone)
        horizon_local = datetime.combine(
            now.date() + timedelta(days=self.settings.calendar_lookahead_days),
            dt_time.min,
            tzinfo=now.tzinfo or self.timezone,
        )
        return start_local, horizon_local

    def summary_for(self, now: datetime, *, status: CalendarState | None = None, stale: bool | None = None) -> CalendarSummary:
        if self.batch is None:
            summary = CalendarSummary(status=status or self.last_state, updated_at=self.fetched_at, stale=bool(stale))
            return summary

        summary = build_calendar_summary(self.batch, now, max_events=self.settings.calendar_max_events, lookahead_days=self.settings.calendar_lookahead_days)
        summary.status = status or self.last_state
        summary.updated_at = self.fetched_at
        summary.stale = stale if stale is not None else self.last_state != CalendarState.ONLINE
        return summary

    def refresh_now(self) -> CalendarSummary:
        with self._lock:
            now = datetime.now(self.timezone)
            try:
                if self.provider is None:
                    self.batch = None
                    self.fetched_at = None
                    self._record_state(CalendarState.NOT_CONNECTED)
                    self._poll_interval = self.settings.calendar_refresh_seconds
                    self._retry_delay = 5.0
                    return self.summary_for(now, status=CalendarState.NOT_CONNECTED, stale=False)

                state = self.provider.availability()
                if state != CalendarState.ONLINE:
                    self._record_state(state)
                    if state == CalendarState.NOT_CONNECTED and self.batch is None:
                        self._poll_interval = self.settings.calendar_refresh_seconds
                    else:
                        self._retry_delay = min(max(self._retry_delay, 5.0) * 2, 600.0)
                        self._poll_interval = self._retry_delay
                    return self.summary_for(now, status=state, stale=self.batch is not None)

                start_local, horizon_local = self._window_for(now)
                batch = self.provider.list_events(start_local, horizon_local)
                if not isinstance(batch, CalendarEventBatch):
                    raise TypeError("Provider must return normalized calendar events")

                self.batch = batch
                self.fetched_at = datetime.now(timezone.utc)
                self._record_state(CalendarState.ONLINE)
                self._retry_delay = 5.0
                self._poll_interval = self.settings.calendar_refresh_seconds
                return self.summary_for(now, status=CalendarState.ONLINE, stale=False)
            except CalendarProviderError as error:
                self._record_state(error.status)
                self._retry_delay = min(max(self._retry_delay, 5.0) * 2, 600.0)
                self._poll_interval = self._retry_delay
                return self.summary_for(now, status=error.status, stale=self.batch is not None)
            except Exception:
                self._record_state(CalendarState.ERROR)
                self._retry_delay = min(max(self._retry_delay, 5.0) * 2, 600.0)
                self._poll_interval = self._retry_delay
                return self.summary_for(now, status=CalendarState.ERROR, stale=self.batch is not None)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="calendar-cache", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        self.refresh_now()
        while not self._stop.wait(self._poll_interval):
            self.refresh_now()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5)


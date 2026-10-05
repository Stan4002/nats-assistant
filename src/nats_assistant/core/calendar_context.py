from datetime import datetime, time, timedelta, timezone

from nats_assistant.core.calendar import CalendarEventBatch, CalendarState, CalendarSummary
from nats_assistant.providers.calendar import CalendarProvider, CalendarProviderError


def build_calendar_summary(
    provider: CalendarProvider | None,
    now: datetime,
    max_events: int = 20,
    lookahead_days: int = 7,
) -> CalendarSummary:
    if provider is None:
        return CalendarSummary()
    try:
        state = provider.availability()
        if state != CalendarState.ONLINE:
            return CalendarSummary(status=state)
        start = datetime.combine(now.date(), time.min, tzinfo=now.tzinfo)
        tomorrow = datetime.combine(now.date() + timedelta(days=1), time.min, tzinfo=now.tzinfo)
        horizon = datetime.combine(now.date() + timedelta(days=lookahead_days), time.min, tzinfo=now.tzinfo)
        start_utc, tomorrow_utc = start.astimezone(timezone.utc), tomorrow.astimezone(timezone.utc)
        horizon_utc, now_utc = horizon.astimezone(timezone.utc), now.astimezone(timezone.utc)
        batch = provider.list_events(start, horizon)
        if not isinstance(batch, CalendarEventBatch):
            raise TypeError("Provider must return normalized calendar events")
        events = sorted(
            (event for event in batch.events if event.status != "cancelled" and
             event.end.astimezone(timezone.utc) > start_utc and
             event.start.astimezone(timezone.utc) < horizon_utc),
            key=lambda event: (event.start.astimezone(timezone.utc), event.id),
        )
        today = [event for event in events if event.start.astimezone(timezone.utc) < tomorrow_utc]
        upcoming = next((event for event in events if event.start.astimezone(timezone.utc) >= now_utc), None)
        return CalendarSummary(
            status=CalendarState.ONLINE,
            today_count=len(today),
            next=upcoming,
            events=today[:max_events],
            truncated=batch.truncated or len(today) > max_events,
        )
    except CalendarProviderError as error:
        return CalendarSummary(status=error.status)
    except Exception:
        # Provider failures, including malformed results, never block task data.
        return CalendarSummary(status=CalendarState.ERROR)

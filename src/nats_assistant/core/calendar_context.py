from datetime import datetime, time, timedelta, timezone

from nats_assistant.core.calendar import CalendarEventBatch, CalendarState, CalendarSummary
from nats_assistant.providers.calendar import CalendarProvider, CalendarProviderError


def _summarize_batch(batch: CalendarEventBatch, now: datetime, max_events: int = 20, lookahead_days: int = 7) -> CalendarSummary:
    start = datetime.combine(now.date(), time.min, tzinfo=now.tzinfo)
    tomorrow = datetime.combine(now.date() + timedelta(days=1), time.min, tzinfo=now.tzinfo)
    horizon = datetime.combine(now.date() + timedelta(days=lookahead_days), time.min, tzinfo=now.tzinfo)
    start_utc, tomorrow_utc = start.astimezone(timezone.utc), tomorrow.astimezone(timezone.utc)
    horizon_utc, now_utc = horizon.astimezone(timezone.utc), now.astimezone(timezone.utc)
    events = sorted(
        (
            event for event in batch.events
            if event.status != "cancelled"
            and event.end.astimezone(timezone.utc) > start_utc
            and event.start.astimezone(timezone.utc) < horizon_utc
        ),
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


def build_calendar_summary(
    batch_or_provider: CalendarEventBatch | CalendarProvider | None,
    now: datetime,
    max_events: int = 20,
    lookahead_days: int = 7,
) -> CalendarSummary:
    if isinstance(batch_or_provider, CalendarEventBatch):
        return _summarize_batch(batch_or_provider, now, max_events=max_events, lookahead_days=lookahead_days)
    if batch_or_provider is None:
        return CalendarSummary(status=CalendarState.NOT_CONNECTED)
    try:
        state = batch_or_provider.availability()
        if state != CalendarState.ONLINE:
            return CalendarSummary(status=state)
        start = datetime.combine(now.date(), time.min, tzinfo=now.tzinfo)
        horizon = datetime.combine(now.date() + timedelta(days=lookahead_days), time.min, tzinfo=now.tzinfo)
        batch = batch_or_provider.list_events(start, horizon)
        if not isinstance(batch, CalendarEventBatch):
            raise TypeError("Provider must return normalized calendar events")
        return _summarize_batch(batch, now, max_events=max_events, lookahead_days=lookahead_days)
    except CalendarProviderError as error:
        return CalendarSummary(status=error.status)
    except Exception:
        return CalendarSummary(status=CalendarState.ERROR)

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from nats_assistant.api.routes import home as home_route
from nats_assistant.api.server import create_app
from nats_assistant.config import Settings
from nats_assistant.core.calendar import CalendarEvent, CalendarEventBatch, CalendarState
from nats_assistant.core.calendar_cache import CalendarCache
from nats_assistant.core.calendar_context import build_calendar_summary
from nats_assistant.providers.calendar import CalendarProvider, CalendarProviderError


def event(event_id, start, end, **kwargs):
    return CalendarEvent(id=event_id, title=event_id, start=start, end=end, source="fake", **kwargs)


class FakeCalendarProvider(CalendarProvider):
    name = "fake"

    def __init__(self, events=(), state=CalendarState.ONLINE, error=None, truncated=False):
        self.events = list(events)
        self.state = state
        self.error = error
        self.truncated = truncated
        self.calls = []

    def availability(self):
        return self.state

    def list_events(self, start, end):
        self.calls.append((start, end))
        if self.error:
            raise self.error
        return CalendarEventBatch(events=self.events, truncated=self.truncated)


NOW = datetime.fromisoformat("2026-10-05T12:00:00+02:00")


def local_noon(tz_name: str = "UTC") -> datetime:
    return datetime.now(ZoneInfo(tz_name)).replace(hour=12, minute=0, second=0, microsecond=0)


def test_calendar_not_connected_without_provider():
    summary = build_calendar_summary(None, NOW)
    assert summary.model_dump() == {
        "status": CalendarState.NOT_CONNECTED, "today_count": 0,
        "next": None, "events": [], "truncated": False,
        "updated_at": None, "stale": False,
    }


def test_online_calendar_empty():
    provider = FakeCalendarProvider()
    summary = build_calendar_summary(provider, NOW)
    assert summary.status == CalendarState.ONLINE
    assert summary.today_count == 0
    assert summary.next is None
    assert summary.events == []
    assert provider.calls[0][0].isoformat() == "2026-10-05T00:00:00+02:00"


def test_today_overlap_sorting_next_and_cancelled():
    future = event("future", "2026-10-05T14:00:00+02:00", "2026-10-05T15:00:00+02:00")
    ongoing = event("ongoing", "2026-10-05T11:00:00+02:00", "2026-10-05T13:00:00+02:00")
    past = event("past", "2026-10-05T09:00:00+02:00", "2026-10-05T10:00:00+02:00")
    tomorrow = event("tomorrow", "2026-10-06T09:00:00+02:00", "2026-10-06T10:00:00+02:00")
    cancelled = event("cancelled", "2026-10-05T12:30:00+02:00", "2026-10-05T13:00:00+02:00", status="cancelled")
    summary = build_calendar_summary(FakeCalendarProvider([tomorrow, future, ongoing, cancelled, past]), NOW)
    assert [item.id for item in summary.events] == ["past", "ongoing", "future"]
    assert summary.today_count == 3
    assert summary.next == future


def test_next_can_be_tomorrow_without_todays_events():
    tomorrow = event("tomorrow", "2026-10-06T09:00:00+02:00", "2026-10-06T10:00:00+02:00")
    summary = build_calendar_summary(FakeCalendarProvider([tomorrow]), NOW)
    assert summary.events == []
    assert summary.next == tomorrow


def test_all_day_and_midnight_boundaries():
    now = datetime(2026, 10, 5, 12, tzinfo=ZoneInfo("Africa/Lusaka"))
    yesterday = event("ended", "2026-10-04T00:00:00+02:00", "2026-10-05T00:00:00+02:00", all_day=True)
    today = event("today", "2026-10-05T00:00:00+02:00", "2026-10-06T00:00:00+02:00", all_day=True)
    utc_overlap = event("utc", "2026-10-04T23:30:00Z", "2026-10-05T00:30:00Z")
    tomorrow = event("tomorrow", "2026-10-06T00:00:00+02:00", "2026-10-07T00:00:00+02:00", all_day=True)
    summary = build_calendar_summary(FakeCalendarProvider([yesterday, tomorrow, utc_overlap, today]), now)
    assert summary.today_count == 2
    assert [item.id for item in summary.events] == ["today", "utc"]
    assert summary.next == tomorrow


def test_dst_day_uses_local_midnights():
    now = datetime(2026, 3, 29, 12, tzinfo=ZoneInfo("Europe/Paris"))
    provider = FakeCalendarProvider([
        event("inside", "2026-03-29T21:30:00Z", "2026-03-29T22:30:00Z"),
        event("outside", "2026-03-29T22:00:00Z", "2026-03-29T23:00:00Z"),
    ])
    summary = build_calendar_summary(provider, now, lookahead_days=1)
    assert summary.today_count == 1
    start, end = provider.calls[0]
    assert start.isoformat() == "2026-03-29T00:00:00+01:00"
    assert end.isoformat() == "2026-03-30T00:00:00+02:00"


def test_preview_limit_does_not_limit_count():
    events = [event(str(hour), f"2026-10-05T{hour}:00:00+02:00", f"2026-10-05T{hour}:30:00+02:00") for hour in range(13, 17)]
    summary = build_calendar_summary(FakeCalendarProvider(events), NOW, max_events=2)
    assert summary.today_count == 4
    assert len(summary.events) == 2
    assert summary.truncated is True
    assert build_calendar_summary(FakeCalendarProvider(truncated=True), NOW).truncated is True


@pytest.mark.parametrize("state", [CalendarState.NOT_CONNECTED, CalendarState.OFFLINE, CalendarState.ERROR])
def test_unavailable_provider_not_queried(state):
    provider = FakeCalendarProvider(state=state)
    assert build_calendar_summary(provider, NOW).status == state
    assert provider.calls == []


@pytest.mark.parametrize("error,state", [
    (CalendarProviderError(CalendarState.OFFLINE), CalendarState.OFFLINE),
    (RuntimeError("secret provider error"), CalendarState.ERROR),
])
def test_home_keeps_task_contract_when_provider_fails(tmp_path, monkeypatch, error, state):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz)

    monkeypatch.setattr(home_route, "datetime", FixedDateTime)
    settings = Settings(data_dir=tmp_path, timezone="Africa/Lusaka", google_calendar_enabled=False)
    app = create_app(settings, calendar_provider=FakeCalendarProvider(error=error))
    with TestClient(app) as client:
        created = client.post("/v1/tasks", json={"title": "Keep tasks", "due": "2026-10-05T14:00:00+02:00"})
        assert created.status_code == 201
        response = client.get("/v1/home")
        assert response.status_code == 200
        payload = response.json()
        assert payload["tasks"]["pending"] == 1
        assert payload["tasks"]["due_today"] == 1
        assert payload["tasks"]["items"][0]["title"] == "Keep tasks"
        assert payload["calendar"]["status"] == state
        assert "secret" not in response.text
        assert client.get("/v1/status").json()["status"] == "online"


def test_home_with_fake_provider_returns_only_normalized_events(tmp_path, monkeypatch):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz)

    monkeypatch.setattr(home_route, "datetime", FixedDateTime)
    provider = FakeCalendarProvider([event("meeting", "2026-10-05T14:00:00+02:00", "2026-10-05T15:00:00+02:00")])
    with TestClient(create_app(Settings(data_dir=tmp_path, timezone="Africa/Lusaka", google_calendar_enabled=False), provider)) as client:
        payload = client.get("/v1/home").json()
        assert payload["calendar"]["status"] == "online"
        assert payload["calendar"]["today_count"] == 1
        assert payload["calendar"]["next"]["id"] == "meeting"
        assert payload["calendar"]["events"][0]["start"] == "2026-10-05T14:00:00+02:00"
        assert payload["tasks"] == {"pending": 0, "due_today": 0, "items": []}


def test_cache_keeps_old_batch_while_provider_is_slow_or_failing(tmp_path):
    now = local_noon("UTC")
    settings = Settings(data_dir=tmp_path, timezone="UTC", google_calendar_enabled=False, calendar_refresh_seconds=30)
    provider = FakeCalendarProvider([event("meeting", now + timedelta(hours=2), now + timedelta(hours=3))])
    cache = CalendarCache(provider, settings)
    cache.refresh_now()
    provider.error = CalendarProviderError(CalendarState.OFFLINE)
    cache.refresh_now()
    summary = cache.summary_for(now)
    assert summary.status == CalendarState.OFFLINE
    assert summary.stale is True
    assert summary.events[0].id == "meeting"


def test_stale_summary_keeps_only_todays_events_when_offline(tmp_path):
    settings = Settings(data_dir=tmp_path, timezone="Africa/Lusaka", google_calendar_enabled=False, calendar_refresh_seconds=30)
    today = event("today", NOW + timedelta(hours=1), NOW + timedelta(hours=2))
    later = event("later", NOW + timedelta(days=1), NOW + timedelta(days=1, hours=1))
    provider = FakeCalendarProvider([later, today])
    cache = CalendarCache(provider, settings)
    cache.refresh_now()
    provider.error = CalendarProviderError(CalendarState.OFFLINE)
    cache.refresh_now()
    summary = cache.summary_for(NOW)
    assert summary.status == CalendarState.OFFLINE
    assert summary.stale is True
    assert [item.id for item in summary.events] == ["today"]
    assert summary.today_count == 1


def test_stale_summary_does_not_use_ended_event_as_next(tmp_path):
    settings = Settings(data_dir=tmp_path, timezone="Africa/Lusaka", google_calendar_enabled=False, calendar_refresh_seconds=30)
    ended = event("ended", NOW - timedelta(hours=2), NOW - timedelta(hours=1))
    provider = FakeCalendarProvider([ended])
    cache = CalendarCache(provider, settings)
    cache.refresh_now()
    provider.error = CalendarProviderError(CalendarState.OFFLINE)
    cache.refresh_now()
    summary = cache.summary_for(NOW)
    assert summary.next is None


def test_stale_summary_excludes_future_day_from_today_count(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        timezone="Africa/Lusaka",
        google_calendar_enabled=False,
        calendar_refresh_seconds=30,
        calendar_lookahead_days=7,
    )
    later = event("later", NOW + timedelta(days=3), NOW + timedelta(days=3, hours=1))
    provider = FakeCalendarProvider([later])
    cache = CalendarCache(provider, settings)
    cache.refresh_now()
    provider.error = CalendarProviderError(CalendarState.OFFLINE)
    cache.refresh_now()
    summary = cache.summary_for(NOW)
    assert summary.today_count == 0


def test_raw_provider_result_is_rejected():
    provider = FakeCalendarProvider()
    provider.list_events = lambda start, end: {"items": [{"summary": "raw Google event"}]}
    assert build_calendar_summary(provider, NOW).status == CalendarState.ERROR


def test_enabled_google_without_auth_keeps_startup_and_home_usable(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", google_calendar_enabled=True,
                        google_calendar_token_path=tmp_path / "missing-token.json")
    with TestClient(create_app(settings)) as client:
        assert client.get("/v1/status").status_code == 200
        response = client.get("/v1/home")
        assert response.status_code == 200
        assert response.json()["calendar"]["status"] == "not_connected"
        assert response.json()["tasks"]["pending"] == 0


@pytest.mark.parametrize("start,end", [
    ("2026-10-05T14:00:00", "2026-10-05T15:00:00+02:00"),
    ("2026-10-05T14:00:00+02:00", "2026-10-05T13:00:00+02:00"),
])
def test_domain_rejects_naive_or_invalid_intervals(start, end):
    with pytest.raises(ValidationError):
        event("invalid", start, end)

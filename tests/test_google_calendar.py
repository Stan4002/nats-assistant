from contextlib import nullcontext
from datetime import datetime
from types import SimpleNamespace

import pytest

from nats_assistant.config import Settings
from nats_assistant.core.calendar import CalendarState
from nats_assistant.providers.calendar import CalendarProviderError
from nats_assistant.providers.google_calendar import GoogleCalendarProvider, normalize_google_event


def raw_event(event_id="event-1", **changes):
    return {
        "id": event_id, "summary": "Meeting", "status": "confirmed",
        "start": {"dateTime": "2026-10-05T14:00:00+02:00"},
        "end": {"dateTime": "2026-10-05T15:00:00+02:00"}, **changes,
    }


def test_normalize_timed_event_whitelists_fields():
    normalized = normalize_google_event(raw_event(attendees=[{"email": "private@example.com"}], access_token="never expose"), "primary", "UTC")
    assert normalized.title == "Meeting"
    assert normalized.description is None
    assert normalized.location is None
    assert normalized.source == "google"
    assert normalized.source_event_id == "event-1"
    assert normalized.start.isoformat() == "2026-10-05T14:00:00+02:00"
    assert "attendees" not in normalized.model_dump()
    assert "access_token" not in normalized.model_dump()


def test_all_day_exclusive_end_and_calendar_timezone():
    normalized = normalize_google_event(raw_event(start={"date": "2026-03-29"}, end={"date": "2026-03-30"}), "work", "Europe/Paris")
    assert normalized.all_day is True
    assert normalized.start.isoformat() == "2026-03-29T00:00:00+01:00"
    assert normalized.end.isoformat() == "2026-03-30T00:00:00+02:00"


def test_timezone_without_offset_and_missing_title():
    normalized = normalize_google_event(raw_event(summary=None,
        start={"dateTime": "2026-10-05T14:00:00", "timeZone": "Africa/Lusaka"},
        end={"dateTime": "2026-10-05T15:00:00", "timeZone": "Africa/Lusaka"}), "primary", "UTC")
    assert normalized.start.utcoffset().total_seconds() == 7200
    assert normalized.title == "Untitled event"


def test_cancelled_tombstone_needs_no_dates():
    assert normalize_google_event({"id": "deleted", "status": "cancelled"}, "primary", "UTC") is None


@pytest.fixture
def provider(tmp_path, monkeypatch):
    pytest.importorskip("google.auth")
    token = tmp_path / "token.json"
    token.write_text("{}")
    settings = Settings(google_calendar_enabled=True, google_calendar_token_path=token, google_calendar_fetch_limit=2)
    provider = GoogleCalendarProvider(settings)
    monkeypatch.setattr(provider, "_load_credentials", lambda: SimpleNamespace(token="fake"))
    return provider


class FakeSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        status, payload = result
        return SimpleNamespace(status_code=status, json=lambda: payload)


START = datetime.fromisoformat("2026-10-05T00:00:00+02:00")
END = datetime.fromisoformat("2026-10-06T00:00:00+02:00")


def test_provider_pagination_ordering_and_bounded_readonly_request(provider, monkeypatch):
    earlier = raw_event("earlier", start={"dateTime": "2026-10-05T13:00:00+02:00"}, end={"dateTime": "2026-10-05T13:30:00+02:00"})
    session = FakeSession([(200, {"items": [raw_event()], "nextPageToken": "page-2"}), (200, {"items": [earlier]})])
    monkeypatch.setattr(provider, "_authorized_session", lambda credentials: nullcontext(session))
    batch = provider.list_events(START, END)
    assert [item.source_event_id for item in batch.events] == ["earlier", "event-1"]
    assert batch.truncated is False
    assert len(session.calls) == 2
    _, options = session.calls[-1]
    assert 0 < options["timeout"] <= 2
    assert options["max_allowed_time"] == options["timeout"]
    assert options["allow_redirects"] is False
    assert options["params"]["singleEvents"] == "true"
    assert options["params"]["showDeleted"] == "false"
    assert "timeZone" not in options["params"]  # Preserve the calendar's all-day timezone.
    assert options["params"]["pageToken"] == "page-2"


def test_provider_fetch_limit_reports_truncation(provider, monkeypatch):
    session = FakeSession([(200, {"items": [raw_event(str(i)) for i in range(3)]})])
    monkeypatch.setattr(provider, "_authorized_session", lambda credentials: nullcontext(session))
    batch = provider.list_events(START, END)
    assert len(batch.events) == 2
    assert batch.truncated is True


def test_refreshed_token_is_saved_privately(provider, monkeypatch):
    credentials = SimpleNamespace(token="old-synthetic", to_json=lambda: '{"token": "new-synthetic"}')
    monkeypatch.setattr(provider, "_load_credentials", lambda: credentials)
    session = FakeSession([(200, {"items": []})])
    original_get = session.get

    def refreshed_get(*args, **kwargs):
        credentials.token = "new-synthetic"
        return original_get(*args, **kwargs)

    session.get = refreshed_get
    monkeypatch.setattr(provider, "_authorized_session", lambda credentials: nullcontext(session))
    assert provider.list_events(START, END).events == []
    token = provider.settings.google_calendar_token_path
    assert token.read_text() == '{"token": "new-synthetic"}'
    assert token.stat().st_mode & 0o777 == 0o600


def test_refresh_error_requires_auth_without_leaking_details(provider, monkeypatch):
    from google.auth.exceptions import RefreshError

    session = FakeSession([RefreshError("refresh_token=synthetic-secret")])
    monkeypatch.setattr(provider, "_authorized_session", lambda credentials: nullcontext(session))
    with pytest.raises(CalendarProviderError) as raised:
        provider.list_events(START, END)
    assert raised.value.status == CalendarState.NOT_CONNECTED
    assert "synthetic-secret" not in str(raised.value)


@pytest.mark.parametrize("status,state", [(401, "not_connected"), (403, "error"), (429, "offline"), (503, "offline")])
def test_google_http_errors_are_controlled(provider, monkeypatch, status, state):
    session = FakeSession([(status, {"error": "refresh_token=secret"})])
    monkeypatch.setattr(provider, "_authorized_session", lambda credentials: nullcontext(session))
    with pytest.raises(CalendarProviderError) as raised:
        provider.list_events(START, END)
    assert raised.value.status == state
    assert "secret" not in str(raised.value)


def test_google_timeout_is_offline(provider, monkeypatch):
    import requests

    session = FakeSession([requests.Timeout("sensitive response")])
    monkeypatch.setattr(provider, "_authorized_session", lambda credentials: nullcontext(session))
    with pytest.raises(CalendarProviderError) as raised:
        provider.list_events(START, END)
    assert raised.value.status == CalendarState.OFFLINE


def test_invalid_google_payload_is_controlled(provider, monkeypatch):
    session = FakeSession([(200, {"items": [{"id": "broken"}]})])
    monkeypatch.setattr(provider, "_authorized_session", lambda credentials: nullcontext(session))
    with pytest.raises(CalendarProviderError) as raised:
        provider.list_events(START, END)
    assert raised.value.status == CalendarState.ERROR


def test_no_token_does_not_query_google(tmp_path):
    provider = GoogleCalendarProvider(Settings(google_calendar_enabled=True, google_calendar_token_path=tmp_path / "absent.json"))
    assert provider.availability() == CalendarState.NOT_CONNECTED
    with pytest.raises(CalendarProviderError) as raised:
        provider.list_events(START, END)
    assert raised.value.status == CalendarState.NOT_CONNECTED

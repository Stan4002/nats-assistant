from contextlib import contextmanager
from datetime import date, datetime, time, timezone
import os
from pathlib import Path
import tempfile
from time import monotonic
from typing import Any, Mapping
from urllib.parse import quote
from zoneinfo import ZoneInfo

from nats_assistant.config import Settings
from nats_assistant.core.calendar import CalendarEvent, CalendarEventBatch, CalendarState
from nats_assistant.providers.calendar import CalendarProvider, CalendarProviderError

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


class GoogleAuthSetupError(Exception):
    """Only controlled messages, never an OAuth response or token."""


def _optional_text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def normalize_google_event(
    payload: Mapping[str, Any], calendar_id: str, calendar_timezone: str
) -> CalendarEvent | None:
    if payload.get("status") == "cancelled":
        return None
    event_id = payload.get("id")
    if not isinstance(event_id, str) or not event_id:
        raise ValueError("Event has no identifier")
    start_data, end_data = payload["start"], payload["end"]
    all_day = "date" in start_data
    if all_day != ("date" in end_data):
        raise ValueError("Event interval has inconsistent types")

    def parse_boundary(value: Mapping[str, Any]) -> datetime:
        zone = ZoneInfo(value.get("timeZone") or calendar_timezone)
        if all_day:
            return datetime.combine(date.fromisoformat(value["date"]), time.min, tzinfo=zone)
        result = datetime.fromisoformat(value["dateTime"])
        return result if result.tzinfo is not None else result.replace(tzinfo=zone)

    title = _optional_text(payload.get("summary"))
    return CalendarEvent(
        id=f"google:{quote(calendar_id, safe='')}:{quote(event_id, safe='')}",
        title=title.strip() if title and title.strip() else "Untitled event",
        description=_optional_text(payload.get("description")),
        start=parse_boundary(start_data),
        end=parse_boundary(end_data),
        all_day=all_day,
        location=_optional_text(payload.get("location")),
        source="google",
        source_calendar_id=calendar_id,
        source_event_id=event_id,
        status=_optional_text(payload.get("status")),
        url=_optional_text(payload.get("htmlLink")),
    )


def _write_token(path: Path, serialized: str) -> None:
    # Settings enforces an external path. Atomic replacement keeps refreshed
    # tokens readable by concurrent requests; mkstemp creates a mode-0600 file.
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".token-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as token_file:
            token_file.write(serialized)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def authenticate_google_calendar(settings: Settings) -> Path:
    if not settings.google_calendar_credentials_path.is_file():
        raise GoogleAuthSetupError("Google desktop OAuth client file is missing; check NATS_GOOGLE_CALENDAR_CREDENTIALS_PATH")
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow

        flow = InstalledAppFlow.from_client_secrets_file(
            str(settings.google_calendar_credentials_path), SCOPES,
            autogenerate_code_verifier=True,
        )
        original_request = flow.oauth2session.request

        def bounded_request(method, url, **kwargs):
            kwargs["timeout"] = settings.google_calendar_timeout_seconds
            return original_request(method, url, **kwargs)

        flow.oauth2session.request = bounded_request
        credentials = flow.run_local_server(
            host="127.0.0.1", bind_addr="127.0.0.1", port=0,
            timeout_seconds=180, open_browser=True, prompt="consent",
        )
        if not credentials.refresh_token or not credentials.has_scopes(SCOPES):
            raise GoogleAuthSetupError("Read-only calendar authorization was not granted; authenticate again")
        _write_token(settings.google_calendar_token_path, credentials.to_json())
        return settings.google_calendar_token_path
    except ImportError:
        raise GoogleAuthSetupError("Install Google support with: python -m pip install -e '.[google]'") from None
    except GoogleAuthSetupError:
        raise
    except Exception:
        raise GoogleAuthSetupError("Google authorization failed or timed out; check OAuth setup and try again") from None


class GoogleCalendarProvider(CalendarProvider):
    name = "google"

    def __init__(self, settings: Settings):
        self.settings = settings

    def availability(self) -> CalendarState:
        if not self.settings.google_calendar_enabled or not self.settings.google_calendar_token_path.is_file():
            return CalendarState.NOT_CONNECTED
        return CalendarState.ONLINE

    def _load_credentials(self):
        from google.oauth2.credentials import Credentials

        try:
            credentials = Credentials.from_authorized_user_file(str(self.settings.google_calendar_token_path))
        except (OSError, ValueError):
            raise CalendarProviderError(CalendarState.NOT_CONNECTED) from None
        if not credentials.has_scopes(SCOPES) or (not credentials.valid and not credentials.refresh_token):
            raise CalendarProviderError(CalendarState.NOT_CONNECTED)
        return credentials

    @contextmanager
    def _authorized_session(self, credentials):
        import requests
        from google.auth.transport.requests import AuthorizedSession, Request

        # Supply our own auth transport to avoid implicit retry loops.
        with requests.Session() as auth_transport:
            with AuthorizedSession(
                credentials, max_refresh_attempts=0,
                refresh_timeout=self.settings.google_calendar_timeout_seconds,
                auth_request=Request(auth_transport),
            ) as session:
                yield session

    def list_events(self, start: datetime, end: datetime) -> CalendarEventBatch:
        if (start.utcoffset() is None or end.utcoffset() is None or
                end.astimezone(timezone.utc) <= start.astimezone(timezone.utc)):
            raise CalendarProviderError(CalendarState.ERROR)
        if self.availability() != CalendarState.ONLINE:
            raise CalendarProviderError(CalendarState.NOT_CONNECTED)
        try:
            import requests
            from google.auth.exceptions import RefreshError, TransportError

            credentials = self._load_credentials()
            previous_token = credentials.token
            limit = self.settings.google_calendar_fetch_limit
            params = {
                "timeMin": start.isoformat(), "timeMax": end.isoformat(),
                "singleEvents": "true", "orderBy": "startTime", "showDeleted": "false",
                "maxResults": limit + 1,
                "fields": "timeZone,nextPageToken,items(id,summary,description,start,end,location,status,htmlLink)",
            }
            url = "https://www.googleapis.com/calendar/v3/calendars/" + quote(self.settings.google_calendar_id, safe="") + "/events"
            events: list[CalendarEvent] = []
            truncated = False
            deadline = monotonic() + self.settings.google_calendar_timeout_seconds
            with self._authorized_session(credentials) as session:
                for page in range(3):
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        raise CalendarProviderError(CalendarState.OFFLINE)
                    response = session.get(url, params=params, timeout=remaining,
                                           max_allowed_time=remaining, allow_redirects=False)
                    if response.status_code == 401:
                        raise CalendarProviderError(CalendarState.NOT_CONNECTED)
                    if response.status_code == 429 or response.status_code >= 500:
                        raise CalendarProviderError(CalendarState.OFFLINE)
                    if response.status_code != 200:
                        raise CalendarProviderError(CalendarState.ERROR)
                    payload = response.json()
                    calendar_timezone = payload.get("timeZone") or self.settings.timezone
                    for raw_event in payload.get("items", []):
                        event = normalize_google_event(raw_event, self.settings.google_calendar_id, calendar_timezone)
                        if event is not None:
                            events.append(event)
                    next_page = payload.get("nextPageToken")
                    if len(events) > limit or (len(events) == limit and next_page):
                        truncated = True
                        break
                    if not next_page:
                        break
                    params["pageToken"] = next_page
                    truncated = page == 2
            if credentials.token != previous_token:
                _write_token(self.settings.google_calendar_token_path, credentials.to_json())
            events.sort(key=lambda event: (event.start.astimezone(timezone.utc), event.id))
            return CalendarEventBatch(events=events[:limit], truncated=truncated)
        except CalendarProviderError:
            raise
        except ImportError:
            raise CalendarProviderError(CalendarState.ERROR) from None
        except RefreshError:
            raise CalendarProviderError(CalendarState.NOT_CONNECTED) from None
        except (requests.Timeout, requests.ConnectionError, TransportError):
            raise CalendarProviderError(CalendarState.OFFLINE) from None
        except Exception:
            # Deliberately discard error bodies and credential exception text.
            raise CalendarProviderError(CalendarState.ERROR) from None

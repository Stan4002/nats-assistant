# NATS Assistant

NATS Assistant is the local backend/core for my personal desktop assistant. It is separate from the GNOME presentation client, NATS HUD.

## Relationship to NATS HUD

- NATS Assistant = backend/core
- NATS HUD = GNOME presentation client

The assistant owns local state, provider integration boundaries, normalization, and service APIs. NATS HUD remains a client and presentation layer only.

## Current milestone

This project is in Milestone 5: read-only calendar integration and unified daily context.

The service currently exposes:

- `GET /v1/status`
- `GET /v1/home`
- `GET /v1/tasks`
- `POST /v1/tasks`
- `GET /v1/tasks/{task_id}`
- `PATCH /v1/tasks/{task_id}`
- `DELETE /v1/tasks/{task_id}`
- `GET /v1/captures`
- `POST /v1/captures`
- `GET /v1/captures/{capture_id}`
- `PATCH /v1/captures/{capture_id}`

The backend is authoritative for task summaries and capture inbox state. The passive HUD reads task and home information from `/v1/home` when available and falls back to its last successful cached values when the backend is unreachable, preserving a graceful offline UI without hardcoded demo tasks.

Quick entry is available via the `nats-assistant` console script:

```bash
nats-assistant quick task --title "Review release notes"
nats-assistant quick capture --text "Remember to sync with design"
```

## Architecture direction

Tasks are stored locally in SQLite. The `tasks` table keeps normalized NATS task data; API routes delegate persistence to a repository. Task source defaults to `nats`. Datetimes are stored in UTC and due dates must include a timezone. `NATS_TIMEZONE` controls the local timezone used for the home view's due-today count; it defaults to the system timezone when available, otherwise UTC.

The production database is `~/.local/share/nats-assistant/nats.db`. Tests use temporary SQLite databases.

Calendar providers sit behind a provider-neutral interface. This keeps provider-specific logic out of routes and the UI, and keeps tasks usable if a provider is unavailable.

## Setup

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

Run the server:

```bash
uvicorn nats_assistant.main:app --host 127.0.0.1 --port 8765 --reload
```

Run tests:

```bash
pytest -q
```

## Local API checks

```bash
curl http://127.0.0.1:8765/v1/status
curl http://127.0.0.1:8765/v1/home
```

Create and list local tasks:

```bash
curl -X POST http://127.0.0.1:8765/v1/tasks \
  -H 'Content-Type: application/json' \
  -d '{"title":"Test task"}'

curl http://127.0.0.1:8765/v1/tasks
```

Tasks support `title`, optional `description`, `completed`, `priority` (`low`, `normal`, `high`, `critical`), optional timezone-aware `due`, `source`, and generated timestamps and ID. List results put incomplete tasks first, then order them by due date and creation time. Add `?completed=true` or `?completed=false` to filter.

## Security baseline

The service remains local-only. Calendar access is read-only and initiated by the backend; no calendar write actions, model integrations, or system-control actions are implemented.

## Calendar architecture

`GoogleCalendarProvider` → `CalendarProvider` → normalized `CalendarEvent` → home aggregation → `/v1/home`.

`core/calendar.py` owns the event and summary schemas. `providers/calendar.py` defines provider identity, a local `availability()` check, and `list_events(start, end)`. Providers return a normalized `CalendarEventBatch`, never raw API dictionaries. `core/calendar_context.py` selects today's events and the next future event independently of Google. Other providers can implement the same interface; tests inject one through `create_app(..., calendar_provider=...)`.

Existing task, capture, and top-level home fields are unchanged. The additive calendar contract is:

```json
{
  "calendar": {
    "status": "not_connected",
    "today_count": 0,
    "next": null,
    "events": [],
    "truncated": false
  }
}
```

Statuses are `online`, `offline` (transport failure, timeout, or temporary API unavailability), `not_connected` (disabled or missing/revoked authorization), and `error` (configuration, permissions, or invalid provider data). Errors contain no provider responses or credentials and never prevent task aggregation.

Each event has `id`, `title`, `description`, timezone-aware `start` and `end`, `all_day`, `location`, `source`, `source_calendar_id`, `source_event_id`, `status`, and `url`. Optional fields can be null. Google IDs are namespaced by calendar; descriptions and locations may be absent. Cancelled events are excluded, recurring instances are expanded, and events are ordered by start time. All-day dates become local midnight intervals in the calendar's timezone; their end is exclusive.

`NATS_TIMEZONE` defines today's midnight boundaries, including DST. `events` contains events overlapping today, including ongoing and multi-day events. `next` is the first event starting at or after now within the lookahead window, possibly tomorrow; it excludes events already in progress. `today_count` is computed before the response preview limit. Retrieval is bounded too: if the fetch limit, pagination budget, or preview limit truncates results, `truncated` is true. In a fetch-truncated result, the count is a lower bound and `next` may be unavailable beyond the fetched events. A query spans local midnight today through local midnight after the configured lookahead days.

**HUD calendar integration follows once this backend contract is stable.** Milestone 5 backend work does not modify the HUD's existing calendar presentation.

## Google Calendar setup

Google support is optional. Install the extra into the existing virtualenv:

```bash
.venv/bin/python -m pip install -e '.[dev,google]'
```

In [Google Cloud Console](https://console.cloud.google.com/), create/select a project, enable the Google Calendar API, configure the OAuth consent screen, and create an OAuth client with application type **Desktop app**. If the consent screen is in testing, add your Google account as a test user. Download its client JSON to an external directory, not this repository. See Google's [Python setup guide](https://developers.google.com/workspace/calendar/api/quickstart/python).

```bash
mkdir -p ~/.config/nats-assistant/google
chmod 700 ~/.config/nats-assistant/google
# Move your downloaded Desktop OAuth client JSON to:
# ~/.config/nats-assistant/google/client_secret.json
chmod 600 ~/.config/nats-assistant/google/client_secret.json

export NATS_TIMEZONE=Africa/Lusaka
export NATS_GOOGLE_CALENDAR_CREDENTIALS_PATH="$HOME/.config/nats-assistant/google/client_secret.json"
export NATS_GOOGLE_CALENDAR_TOKEN_PATH="$HOME/.local/share/nats-assistant/google/token.json"
export NATS_GOOGLE_CALENDAR_ID=primary

.venv/bin/nats-assistant calendar google auth
```

Only this explicit command opens a browser. It requests `https://www.googleapis.com/auth/calendar.readonly`, uses desktop OAuth with PKCE and a loopback callback on `127.0.0.1`, and waits up to 180 seconds for approval. The token is atomically written with mode `0600` outside the repository. The OAuth client file and stored access/refresh tokens are private local files, never source assets. Existing tokens refresh automatically during event reads; normal startup never requests interactive authorization.

Enable the provider and start/restart the service with the same environment:

```bash
export NATS_GOOGLE_CALENDAR_ENABLED=true
.venv/bin/uvicorn nats_assistant.main:app --host 127.0.0.1 --port 8765
curl http://127.0.0.1:8765/v1/status
curl http://127.0.0.1:8765/v1/home
```

| Setting | Default | Purpose |
|---|---|---|
| `NATS_GOOGLE_CALENDAR_ENABLED` | `false` | Enable Google reads |
| `NATS_GOOGLE_CALENDAR_CREDENTIALS_PATH` | `~/.config/nats-assistant/google/client_secret.json` | Desktop OAuth client file used by auth command |
| `NATS_GOOGLE_CALENDAR_TOKEN_PATH` | `~/.local/share/nats-assistant/google/token.json` | Saved user token, used by service |
| `NATS_GOOGLE_CALENDAR_ID` | `primary` | Calendar ID; shared calendars may use their own ID |
| `NATS_GOOGLE_CALENDAR_TIMEOUT_SECONDS` | `2` | Network timeout and event-read time budget; range `(0, 30]` |
| `NATS_GOOGLE_CALENDAR_FETCH_LIMIT` | `200` | Retrieval cap; range `1–1000`, at most three pages |
| `NATS_CALENDAR_MAX_EVENTS` | `20` | Today's response preview cap; range `1–100` |
| `NATS_CALENDAR_LOOKAHEAD_DAYS` | `7` | Upcoming search window; range `1–31` |
| `NATS_TIMEZONE` | System timezone or `UTC` | Daily home boundaries |

Config paths expand `~` and are rejected if they resolve inside this source checkout. No auth files are created until you authenticate or refresh an existing token. Network I/O uses explicit timeouts with no event polling loop or calendar writes. The home route runs in FastAPI's worker pool; provider errors become controlled states. Token refresh and HTTP requests are individually bounded; this is not a guarantee of a strict wall-clock response deadline.

To disable Calendar, set `NATS_GOOGLE_CALENDAR_ENABLED=false` and restart the service. `/v1/home` continues returning tasks, with calendar status `not_connected`.

Troubleshooting:

- `not_connected`: check provider enablement and token path; rerun `calendar google auth` if consent/token is missing, expired without a refresh token, revoked, or lacks the read-only scope. OAuth apps in Google's testing mode may need periodic reauthorization.
- `offline`: check connectivity, proxy settings, API rate limits, and timeout settings. Retry a home read; tasks remain available.
- `error`: install the Google extra, confirm the Calendar API is enabled, verify calendar access/ID, and check that the OAuth client is a Desktop app. Raw Google errors are deliberately hidden from the home response.
- Provider-enabled home requests may take longer than disabled requests. If your client timeout is shorter than calendar I/O, adjust its timeout or reduce the provider timeout; no separate polling loop is introduced.

## Calendar validation

```bash
.venv/bin/python -m pytest -q
git diff --check
```

Calendar tests use fake providers and mock Google transport/OAuth; test socket connections are blocked. They cover disabled/missing auth, empty and populated calendars, all-day events, timezone/DST boundaries, next-event selection, ordering, result caps, failures without task loss, payload isolation, and private token storage. They do not contact Google or require real credentials.

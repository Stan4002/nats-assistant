# NATS Assistant

NATS Assistant is the local backend/core for my personal desktop assistant. It is separate from the GNOME presentation client, NATS HUD.

## Relationship to NATS HUD

- NATS Assistant = backend/core
- NATS HUD = GNOME presentation client

The assistant owns local state, provider integration boundaries, normalization, and service APIs. NATS HUD remains a client and presentation layer only.

## Current milestone

This project is in Milestone 5.5: persistent configuration, official server startup, and user-service autostart.

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

Run the server using the installed CLI (activation is only a development convenience):

```bash
.venv/bin/nats-assistant serve
```

For normal use, configure the user service below. `nats_assistant.main:app` remains compatible with direct Uvicorn development workflows.

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

.venv/bin/nats-assistant config set timezone Africa/Lusaka
.venv/bin/nats-assistant config set google_calendar_id primary
# Optional overrides for non-default external OAuth file locations:
export NATS_GOOGLE_CALENDAR_CREDENTIALS_PATH="$HOME/.config/nats-assistant/google/client_secret.json"
export NATS_GOOGLE_CALENDAR_TOKEN_PATH="$HOME/.local/share/nats-assistant/google/token.json"

.venv/bin/nats-assistant calendar google auth
```

Only this explicit command opens a browser. It requests `https://www.googleapis.com/auth/calendar.readonly`, uses desktop OAuth with PKCE and a loopback callback on `127.0.0.1`, and waits up to 180 seconds for approval. The token is atomically written with mode `0600` outside the repository. The OAuth client file and stored access/refresh tokens are private local files, never source assets. Existing tokens refresh automatically during event reads; normal startup never requests interactive authorization.

Enable the provider persistently, then start the server or restart an installed service:

```bash
.venv/bin/nats-assistant config set google_calendar_enabled true
.venv/bin/nats-assistant serve
# If the user service is already running, use service restart instead.
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

To disable Calendar persistently, run `nats-assistant config set google_calendar_enabled false` and restart the service. `NATS_GOOGLE_CALENDAR_ENABLED=false` is still a process-level override. `/v1/home` continues returning tasks, with calendar status `not_connected`.

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

## Persistent configuration

The shared settings API reads `~/.config/nats-assistant/config.toml`. If `XDG_CONFIG_HOME` is set, it uses `$XDG_CONFIG_HOME/nats-assistant/config.toml`; `NATS_CONFIG_FILE` can select another file. A missing file is a valid first-run state: the server uses defaults and Calendar is disabled. Malformed TOML, unsupported keys, or invalid effective values fail startup with a controlled error.

```toml
timezone = "Africa/Lusaka"
google_calendar_enabled = true
google_calendar_id = "primary"
```

Precedence is explicit `Settings(...)` arguments, then `NATS_` environment variables, then persisted TOML values, then defaults. No working-directory `.env` file is loaded. Existing environment overrides continue to work, but an export in a terminal is not a persistent setting for a future login. Service installation pins the selected config file path in the generated unit; it does not copy terminal exports into that file.

```bash
.venv/bin/nats-assistant config set timezone Africa/Lusaka
.venv/bin/nats-assistant config set google_calendar_enabled true
.venv/bin/nats-assistant config set google_calendar_id primary
.venv/bin/nats-assistant config get timezone
.venv/bin/nats-assistant config show
```

`show` and `get` report effective values. `set` validates the persisted values independently of environment overrides and preserves the previous file on validation failure. It atomically writes mode `0600` files, creating the config directory with mode `0700` when needed. Settings apply to a running API server after restart. This read/write API can later support a settings GUI; no GTK settings application is implemented yet.

Known configurable keys include `host`, `port`, `timezone`, `data_dir`, `database_file`, the Google enablement/calendar-ID/path/timeout/fetch-limit settings, and calendar preview/lookahead limits. OAuth file **paths** are settings; OAuth token/client-secret **contents** are never settings. Unknown keys, including `access_token`, `refresh_token`, and `client_secret`, are rejected. Default OAuth locations remain `~/.config/nats-assistant/google/client_secret.json` and `~/.local/share/nats-assistant/google/token.json`. Config commands never open or print their contents. Keep these files private; do not paste credentials into any ordinary setting.

`serve` binds `127.0.0.1:8765` by default. `host`/`NATS_HOST` must be a loopback IP address, and `port`/`NATS_PORT` must be in `1–65535`. Uvicorn owns SIGTERM/SIGINT handling and graceful shutdown; startup/shutdown and HTTP logs go to the terminal or user journal. Startup creates providers without launching OAuth. Enabled Google reads load the existing token on `/v1/home`, refresh it when possible, and require interactive authorization again only if credentials have expired without refresh access or have been revoked. Missing auth exposes `not_connected` and tasks continue working.

## Login startup with systemd

Install the backend package first. For this checkout the existing virtualenv is sufficient; no root or virtualenv activation is required:

```bash
.venv/bin/nats-assistant service install
.venv/bin/nats-assistant service enable
# Stop any manually running Uvicorn server before starting the service.
.venv/bin/nats-assistant service start
.venv/bin/nats-assistant service status
```

`install` writes `$XDG_CONFIG_HOME/systemd/user/nats-assistant.service`, defaulting to `~/.config/systemd/user/nats-assistant.service`, and runs `systemctl --user daemon-reload`. It does not enable or start the service. `enable` enables login startup; `start` starts this session's instance. The unit is wanted by the user's `default.target`, with restart on failure after three seconds. It runs as the logged-in user, and ends when the user service manager stops; this milestone does not configure lingering or system-wide services.

The shipped template is `src/nats_assistant/nats-assistant.service.in`. A generated unit has this structure (placeholder paths are substituted and quoted safely):

```ini
# Generated by nats-assistant service install.
[Unit]
Description=NATS Assistant
After=network-online.target

[Service]
Type=simple
Environment="NATS_CONFIG_FILE=<absolute user config path>"
ExecStart="<resolved nats-assistant executable>" serve
Restart=on-failure
RestartSec=3
UMask=0077

[Install]
WantedBy=default.target
```

No `EnvironmentFile` is needed: the application reads TOML itself. Units contain no OAuth credentials or copied environment secrets. Executable discovery prefers `nats-assistant` alongside the running Python interpreter, then the invoked console script, then PATH. A development unit points to the existing virtualenv's executable; future packages can provide `/usr/bin/nats-assistant` or another packaging-managed location without changing the service architecture. Moving/removing a development virtualenv requires reinstalling the unit. The installer refuses to overwrite units it did not generate. The template is included in Python package data.

Commands and logs:

```bash
nats-assistant service restart
nats-assistant service stop
nats-assistant service disable
systemctl --user status nats-assistant
journalctl --user -u nats-assistant -f
```

In the development checkout use `.venv/bin/nats-assistant` when the command is not on PATH. Service commands invoke fixed `systemctl --user` argv lists, never a shell. `status` preserves systemctl's nonzero exit code when the unit is inactive or missing.

Uninstall the generated service (stops it, disables autostart, removes the unit, and reloads the user manager):

```bash
.venv/bin/nats-assistant service uninstall
```

Uninstall preserves the SQLite database, config file, and OAuth files. Delete those separately only if you intend to remove your data or authorization.

Runtime troubleshooting:

- Calendar is `not_connected` after login: check `config get google_calendar_enabled`, the installed unit's `NATS_CONFIG_FILE`, and the token path. Persist settings instead of relying on terminal exports. Restart after edits. Service online, provider enabled, token present, and Calendar API online are separate states; `/v1/status`, `config show`, and `/v1/home.calendar.status` expose the existing relevant information without adding endpoints.
- Invalid config: correct the TOML/known values; errors omit supplied values and OAuth response contents. `config set` can replace a well-formed invalid value, but syntax errors or unsupported keys must first be fixed in the file.
- Port already in use: stop the manually launched development server before `service start`. Keep port `8765` for the current HUD client, which uses that port.
- Missing executable after moving a checkout: rerun `service install` using the new installed executable, then restart.
- Unsupported executable path: systemd rejects executable names containing quotes or backslashes; use a checkout/install location without those characters. Spaces, percent signs, and dollar signs are handled by the generator.
- User manager unavailable: run service setup in a normal logged-in user session with systemd; do not use `sudo`. `serve` remains available for manual operation.
- OAuth revoked/expired: authorization is always explicit via `calendar google auth`; normal startup never opens a browser.

Runtime tests isolate config files and mock all systemctl calls. They cover persistence across fresh processes, precedence, validation/redaction, private writes, serve arguments, service generation/management, and task availability with Google disabled or unauthenticated. They do not enable or start the real user service.

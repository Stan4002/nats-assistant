# Calendar module

## Purpose

The calendar module keeps the home endpoint responsive while still surfacing a useful summary of upcoming events. It normalizes provider data into a local model and caches the last successful result so requests do not block on a slow or failing Google Calendar call.

## Data model

- `CalendarEvent`: normalized event with timezone-aware start/end, optional metadata, and status.
- `CalendarEventBatch`: the provider result for a time window, plus `truncated`.
- `CalendarSummary`: the response contract used by `/v1/home`, including `status`, `today_count`, `next`, `events`, `truncated`, `updated_at`, and `stale`.

See [src/nats_assistant/core/calendar.py](../../src/nats_assistant/core/calendar.py).

## Background refresh

The app owns a `CalendarCache` that polls the provider on a configurable interval and stores the last successful batch. A refresh lock prevents overlapping polls, and provider failures keep the last good batch available while marking the summary stale.

See [src/nats_assistant/core/calendar_cache.py](../../src/nats_assistant/core/calendar_cache.py).

## Request-time behavior

The home route uses the cache instead of making a provider call in the request path. This keeps `/v1/home` fast even when Google is slow or unavailable.

See [src/nats_assistant/api/routes/home.py](../../src/nats_assistant/api/routes/home.py) and [src/nats_assistant/api/server.py](../../src/nats_assistant/api/server.py).

## Providers and privacy

Providers implement a small interface that exposes `availability()` and `list_events(start, end)`. The backend normalizes results before they reach the response layer. No raw provider payloads are exposed to the client. Secrets and credentials remain outside the repository and are never logged.

See [src/nats_assistant/providers/calendar.py](../../src/nats_assistant/providers/calendar.py).

## Known issues

- Cached data is intentionally stale when the provider fails; the UI must treat `stale=true` as a degraded but usable state.
- A provider returning a non-normalized result is rejected to avoid leaking raw provider data into the app.

# 0001: keep a background calendar cache

- Status: accepted
- Date: 2026-10-25

## Context

The home endpoint previously called Google Calendar synchronously while building the response. Slow provider responses blocked the request path and could fail the whole home summary even when task data was otherwise healthy.

## Decision

We added a background `CalendarCache` that refreshes the provider on an interval and stores the last successful `CalendarEventBatch`. Home requests now read from the cache instead of calling the provider directly. If the provider fails, the last successful result is kept and marked `stale=true`.

## Consequences

- `/v1/home` remains responsive while calendar refreshes happen in the background.
- The app can report degraded but usable calendar state during outages.
- We accept a small delay before fresh provider data appears after recovery.

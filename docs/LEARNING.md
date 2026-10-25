# Learning log

## 2026-10-25: calendar cache and stale summaries

We built a background calendar refresh so `/v1/home` no longer blocks on a slow Google call. The flow is:

1. Create the app and set `app.state.calendar_cache` in [src/nats_assistant/api/server.py](../src/nats_assistant/api/server.py).
2. Start the cache during the FastAPI lifespan so it begins polling before requests are served.
3. `CalendarCache.refresh_now()` checks provider availability and fetches a normalized `CalendarEventBatch` when the provider is online.
4. When the provider is offline or raises an error, the cache keeps the previous batch and marks the summary stale instead of dropping the data.
5. The home route calls `cache.summary_for(now_local)` instead of hitting the provider directly, so task and capture data still return quickly.

Read the files in this order:

- [src/nats_assistant/core/calendar.py](../src/nats_assistant/core/calendar.py)
- [src/nats_assistant/core/calendar_context.py](../src/nats_assistant/core/calendar_context.py)
- [src/nats_assistant/core/calendar_cache.py](../src/nats_assistant/core/calendar_cache.py)
- [src/nats_assistant/api/server.py](../src/nats_assistant/api/server.py)
- [src/nats_assistant/api/routes/home.py](../src/nats_assistant/api/routes/home.py)

Try this yourself: swap the fake provider for a slow one in tests and confirm the home response still returns promptly while `stale` flips to true.

To undo the cache, remove the `CalendarCache` startup in the app lifespan and restore direct provider calls in the home route.

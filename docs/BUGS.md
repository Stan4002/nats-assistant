# Known bugs and fixes

## 2026-10-25: stale calendar cache kept empty event list

- Symptom: a stale calendar summary showed the wrong `today_count` and `next`. Events from the whole cached lookahead window were counted as today, and `next` could be an event that had already ended.
- Cause: `CalendarCache.summary_for` had a special `if effective_stale:` branch that built `CalendarSummary` straight from `self.batch.events` and skipped time filtering. The first reported empty-list symptom came from tests that hard-coded past dates (for example 2026-10-05); those events were outside the current day, and that was wrongly treated as a cache bug.
- Fix: stale summaries use the same `build_calendar_summary` path as online ones. Only `status`, `updated_at`, and `stale` differ.
- Verification: three regression tests in `tests/test_calendar.py` cover offline stale filtering of today's events, a cached event that ended an hour before a fixed `now` not becoming `next`, and a cached event three days later not counting toward `today_count`.

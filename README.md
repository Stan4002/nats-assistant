# NATS Assistant

NATS Assistant is the local backend/core for my personal desktop assistant. It is separate from the GNOME presentation client, NATS HUD.

## Relationship to NATS HUD

- NATS Assistant = backend/core
- NATS HUD = GNOME presentation client

The assistant owns local state, provider integration boundaries, normalization, and service APIs. NATS HUD remains a client and presentation layer only.

## Current milestone

This project is in Milestone 2: local task domain and persistence.

The service currently exposes:

- `GET /v1/status`
- `GET /v1/home`
- `GET /v1/tasks`
- `POST /v1/tasks`
- `GET /v1/tasks/{task_id}`
- `PATCH /v1/tasks/{task_id}`
- `DELETE /v1/tasks/{task_id}`

Providers are not implemented yet.
HUD integration is not implemented yet.

## Architecture direction

Tasks are stored locally in SQLite. The `tasks` table keeps normalized NATS task data; API routes delegate persistence to a repository. Task source defaults to `nats`. Datetimes are stored in UTC and due dates must include a timezone. `NATS_TIMEZONE` controls the local timezone used for the home view's due-today count; it defaults to the system timezone when available, otherwise UTC.

The production database is `~/.local/share/nats-assistant/nats.db`. Tests use temporary SQLite databases.

The long-term model is a local FastAPI service with provider interfaces behind a future abstraction layer. This keeps provider-specific logic out of the UI and keeps the assistant resilient if a provider is unavailable.

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

This milestone intentionally keeps the service local-only and does not implement provider access, system control, or network callers.

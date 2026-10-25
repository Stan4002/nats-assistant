# AGENTS.md — rules for AI coding agents (Codex etc.)

Put this file at the ROOT of the repo (nats-assistant, and a copy in nats-desktop). Agents read it before working.

## Project
NATS is a personal assistant ecosystem running locally on Ubuntu (GNOME, Wayland):
- `nats-assistant` (this repo): Python/FastAPI backend, SQLite, systemd user service on 127.0.0.1:8765. It owns ALL data and logic.
- `nats-hud`: GNOME Shell extension. Presentation only. Never put assistant logic in GNOME Shell.
- `nats-desktop`: full desktop app (planned). A client of this API.

Architecture rules that must not be broken:
1. Backend is the only owner of data. Clients display and send intents.
2. Outside services (Google, Ollama, email, weather) sit behind provider interfaces (see `providers/base.py`, `providers/calendar.py`). Routes and UI never see raw provider responses.
3. A failing provider must never break unrelated features (tasks must work if calendar/LLM is down).
4. Local only: bind to loopback, no cloud calls unless a task explicitly says so. Secrets never go in config.toml, git, logs or tests.
5. Never send messages, emails or reply on the user's behalf. Drafts only, unless a task explicitly adds an approved, narrow, opt-in auto-reply.
6. Private data (journal, finance, message text) is never logged and never goes to the HUD in full.

## Git workflow (strict)
- Never commit to `main`. Create a branch from an up-to-date `main`: `feature/<short-name>` or `fix/<short-name>`.
- Small commits, one idea each, message format `type: what and why` (feat, fix, docs, test, refactor).
- Do not push, merge, rebase, force-push or delete branches. Stop and tell the user the branch is ready for review.
- Do not touch files outside the task's scope.

## Quality
- Python >=3.11 compatible. Add `from __future__ import annotations` in new modules that use `list[...]` style hints inside classes with methods named like builtins.
- Run before finishing: `python -m pytest -q` (from the venv). Tests use temporary SQLite DBs and must not open real network sockets.
- New behaviour needs tests, including the failure path.
- Follow the existing layout: models in `core/`, storage in `storage/`, routes in `api/routes/`, registered in `api/server.py`.
- Prefer small readable code over clever code. The owner is learning and must be able to follow it.

## Documentation duty (the owner wants to learn and reverse engineer everything)
For EVERY task, before finishing, create or update:
1. `docs/modules/<name>.md` — purpose, data, endpoints, providers, privacy, known issues.
2. `docs/decisions/NNNN-<title>.md` — an ADR for each real choice (why X over Y, what we gave up).
3. `docs/LEARNING.md` — add a dated entry: what was built, how it works step by step, which files to read in what order, one thing to try yourself, and how to undo it.
4. `CHANGELOG.md` — one line per user-visible change.
5. `docs/BUGS.md` — any bug hit: symptom, cause, fix, how it was verified.
6. Comments explain WHY, not WHAT. Name things plainly.

## When unsure
Stop and ask. Do not guess about auth, data deletion, migrations, or anything touching the user's accounts.

## Useful commands
```
source .venv/bin/activate
python -m pytest -q
nats-assistant service restart
journalctl --user -u nats-assistant -n 50 --no-pager
curl http://127.0.0.1:8765/v1/status
```

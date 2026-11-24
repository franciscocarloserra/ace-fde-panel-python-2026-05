# AGENTS.md

Cadence: FastAPI workflow-automation API. Postgres (SQLAlchemy), Redis, Celery workers. Python 3.11.

Read this before changing code. It applies to humans and AI agents alike.

## Source of truth
- Mounted routes are whatever `app/main.py` includes. README and ARCHITECTURE are partly stale (they list endpoints that don't exist); check the code before trusting them.
- Grep for prior attempts before writing something new (e.g. `app/middleware/throttle.py` is an unfinished rate limiter). Finish or replace it explicitly; don't add a parallel one.

## Commands
```
make install      # deps + editable package
make test         # pytest, no coverage
make lint         # ruff check .
make format       # ruff format .
make typecheck    # mypy --strict on typed modules
```
`docker compose up -d` starts Postgres + Redis. No migrations yet: tables come from `Base.metadata.create_all(engine)`.

## Code
- Layers: `routes/` (HTTP only) → `services/` (logic) → `repositories/` (DB access, see `repositories/base.py` protocol). Routes don't query the DB directly.
- New modules are fully typed and pass `mypy --strict`; add them to the `typecheck` target in the Makefile.
- Ruff currently reports existing errors on the repo. Don't add new ones: files you touch must be clean.
- No new code in `app/utils/helpers.py`; put it next to where it's used.
- Tunable values (limits, timeouts, windows) as named constants or settings in `app/config.py`, not inline.

## Tests
- Every change ships tests that assert the acceptance criteria (status codes, headers, side effects). A test that only checks something exists doesn't count.
- No real external services in unit tests: `fakeredis` for Redis, FastAPI `dependency_overrides` for dependencies (the override must be a callable, e.g. `lambda: fake`).
- Tests use `sqlite:///./test.db` (see `conftest.py`); `make clean` removes it if a rerun fails on leftover data.

## Git and review
- Conventional commits: `feat(scope): ...`, `fix(scope): ...`, `test: ...`, `chore: ...`. No "fix", "stuff", "wip" messages.
- One branch per ticket: `feat/<topic>`, `fix/<topic>`. WIP stays on the branch; main only gets work that meets the ticket.
- Review checks the ticket's acceptance criteria against the tests, not only that CI is green.

## Known pitfalls
- SQLAlchemy is unpinned; 2.x defaults to psycopg 3. Use `postgresql+psycopg2://` in `DATABASE_URL`.
- Workflow steps run through `_default_resolver`, which is a stub: integrations (`services/integrations/`) aren't wired in yet.

# luxion-backend

Python backend for [Luxion](../README.md): FastAPI service + agent core.

## Run

```powershell
.\.venv\Scripts\python.exe -m luxion     # http://127.0.0.1:8756
```

## Develop

```powershell
.\.venv\Scripts\pip.exe install -e ".[dev]"
.\.venv\Scripts\pytest.exe               # tests
.\.venv\Scripts\ruff.exe check .         # lint
.\.venv\Scripts\ruff.exe format .        # format
.\.venv\Scripts\alembic.exe upgrade head # apply migrations
.\.venv\Scripts\alembic.exe revision --autogenerate -m "..."  # new migration
```

## Structure

| Path | Purpose |
|------|---------|
| `luxion/api/` | FastAPI app factory, routes (`/api/health`, `/api/version`) |
| `luxion/config/settings.py` | All configuration (`LUXION_*` env vars, nested `__`) |
| `luxion/database/` | SQLAlchemy models (`Conversation`, `Message`) + engine/session |
| `luxion/logging_setup.py` | JSON logging, rotating files, secret redaction |
| `alembic/` | Schema migrations |
| `tests/` | pytest suite (17 tests) |

## Endpoints

- `GET /api/health` — status, version, database check, uptime
- `GET /api/version` — version info

## Conventions

- Ports: `8756` (configurable via `LUXION_SERVER__PORT`).
- Never hardcode secrets — use `LUXION_LLM__API_KEY_ENV` or `.env`.
- Schema changes: edit `luxion/database/models.py`, then autogenerate a migration.

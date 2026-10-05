# Luxion

**Personal AI agent for Windows** — a local-first, tool-based, multimodal desktop
assistant. The user describes what they want; Luxion determines how to accomplish it.

> Full requirements: [`prd.md`](prd.md) · Living status log: [`memory.md`](memory.md) ·
> UI design rules: [`design-system/luxion/MASTER.md`](design-system/luxion/MASTER.md)

## Stack

| Layer | Tech |
|-------|------|
| Desktop shell | Tauri 2 (Rust) — `frontend/src-tauri/` |
| Frontend | React 19 · TypeScript · Vite 8 · Tailwind 4 — `frontend/` |
| Backend | Python ≥3.11 · FastAPI · SQLAlchemy · Alembic — `backend/` |
| Database | SQLite (dev) → PostgreSQL + pgvector (Phase 5) |
| Local AI | Ollama (Phase 1+) |

## Repository layout

```
Luxion/
├── prd.md                  # Product requirements (source of truth)
├── memory.md               # Project memory — updated after every phase
├── design-system/luxion/   # Persisted design system (ui-ux-pro-max skill)
├── .opencode/skills/       # Agent skills (ui-ux-pro-max, …)
├── backend/                # Python API + agent core
│   ├── luxion/             # app, config, database, logging, api
│   ├── alembic/            # migrations
│   └── tests/              # pytest suite
├── frontend/               # React app + Tauri shell
│   ├── src/                # UI (dashboard shell today)
│   └── src-tauri/          # Tauri 2 (crate `luxion`)
└── scripts/dev.ps1         # runs backend + frontend together
```

## Quick start

```powershell
# 1. Backend  -> http://127.0.0.1:8756
cd backend
python -m venv .venv
.\.venv\Scripts\pip.exe install -e ".[dev]"
.\.venv\Scripts\python.exe -m luxion

# 2. Frontend -> http://localhost:5173   (new terminal)
cd frontend
npm install
npm run dev

# …or both at once:
.\scripts\dev.ps1

# Desktop window
cd frontend
npx tauri dev
```

Configuration lives in `.env` (copy from `.env.example`), all variables prefixed
`LUXION_`. Secrets are never hardcoded.

## Tests & checks

```powershell
cd backend
.\.venv\Scripts\pytest.exe        # 17 tests
.\.venv\Scripts\ruff.exe check .  # lint
.\.venv\Scripts\ruff.exe format .

cd ..\frontend
npm run build                     # tsc + vite
npm run lint                      # oxlint
```

## Current status

**Phase 0–4 complete** (architecture, Luxion core + OpenRouter provider,
context manager, tool framework: 9 built-in tools, autonomy matrix +
per-tool overrides, confirmations, audit log, agent loop, Settings → Tools).
See [memory.md](memory.md) for the phase log, decisions, and what's next
(Phase 5: Memory).

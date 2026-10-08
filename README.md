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
│   │   ├── context/        # context assembly (tokens, budget, injection)
│   │   ├── llm/            # provider adapters (ollama, openrouter, mock)
│   │   ├── memory/         # memory store, extraction, recall
│   │   ├── rag/            # chunking, embeddings, sqlite-vec store
│   │   ├── repository/     # workspace scan, index, code retrieval
│   │   ├── tools/          # tool framework + 13 builtins
│   │   └── voice/          # mic, STT, TTS, wake word
│   ├── alembic/            # migrations
│   └── tests/              # pytest suite (406 tests)
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
.\.venv\Scripts\pytest.exe        # 406 tests (1 skipped)
.\.venv\Scripts\ruff.exe check .  # lint
.\.venv\Scripts\ruff.exe format --check .

cd ..\frontend
npm run build                     # tsc + vite
npm run lint                      # oxlint
```

## Current status

**Phase 0–5c complete** — architecture; Luxion core + provider adapters
(Ollama / OpenRouter, tap-to-switch, model pinning); context manager; tool
framework with 13 built-ins + autonomy matrix, confirmations and audit log;
capabilities & consent (OS probe, app consents, risk engine); voice
(faster-whisper STT, pyttsx3/OmniVoice TTS, wake word, barge-in); memory store
+ RAG index + extraction + `remember`/`recall`/`forget`; repository indexing +
`search_code` + `/api/repository`.

**In progress: Phase 5d** — Settings → Memory UI + context injection
(memory + repository context into the system prompt). See
[memory.md](memory.md) for the phase log, the 5d plan, and what's next
(Phase 6: browser agent).

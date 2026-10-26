<p align="center">
  <img src="frontend/public/logo.png" width="180" alt="Luxion logo" />
</p>

<h1 align="center">Luxion</h1>

<p align="center">
  <b>Personal AI agent for Windows</b> — local-first, tool-based, multimodal.<br/>
  You describe what you want; Luxion figures out how to do it.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/phase-11%20%C2%B7%20vision%20%2B%20hardware-0ea5e9?style=flat-square&labelColor=020a16" alt="Phase 11" />
  <img src="https://img.shields.io/badge/tests-792%20passed-10b981?style=flat-square&labelColor=020a16" alt="792 tests passing, 1 skipped" />
  <img src="https://img.shields.io/github/actions/workflow/status/HarshJangra816/LUXION_AI_AGENT/ci.yml?style=flat-square&labelColor=020a16&label=CI" alt="CI" />
  <img src="https://img.shields.io/badge/tools-70-10b981?style=flat-square&labelColor=020a16" alt="70 tools" />
  <img src="https://img.shields.io/badge/license-MIT-10b981?style=flat-square&labelColor=020a16" alt="MIT license" />
  <img src="https://img.shields.io/badge/Tauri-2-24C8DB?style=flat-square&logo=tauri&logoColor=white" alt="Tauri 2" />
  <img src="https://img.shields.io/badge/React-19-61DAFB?style=flat-square&logo=react&logoColor=black" alt="React 19" />
  <img src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.11+" />
  <img src="https://img.shields.io/badge/100%25-local-black?style=flat-square" alt="Runs 100% local" />
</p>

<p align="center">
  <a href="#demo">Demo</a> ·
  <a href="#screenshots">Screenshots</a> ·
  <a href="#what-luxion-does-today">Features</a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="#roadmap">Roadmap</a> ·
  <a href="SETUP.md">Setup guide</a> ·
  <a href="#contributing">Contributing</a>
</p>

---

## Demo

A 22-second tour of the running app — Dashboard → Chat → Memory → Settings
(real capture, no mocks). Recorded before the Tools/Integrations split, so the
clip shows the older Settings layout; the app itself has since moved those
cards into their own pages (see [SETUP.md](SETUP.md)):

<p align="center">
  <video src="docs/assets/demo.webm" controls muted loop playsinline width="820" poster="docs/assets/dashboard.png">
    Your browser does not support the video tag — see <a href="docs/assets/demo.webm">demo.webm</a>.
  </video>
</p>

## Screenshots

| Dashboard | Chat |
|:---------:|:----:|
| <img src="docs/assets/dashboard.png" alt="Dashboard — 3D AI core with live system HUD" /> | <img src="docs/assets/chat.png" alt="Chat — streaming conversation with voice composer" /> |

| Memory & knowledge | Integrations → Browser agent |
|:------------------:|:------------------------:|
| <img src="docs/assets/memory.png" alt="Memory — stored memories, context injection, embeddings" /> | <img src="docs/assets/settings-browser.png" alt="Browser agent card (Phase 6) — now under Integrations" /> |

<details>
<summary><b>More of Settings</b> — provider adapters (Ollama, OpenRouter, OpenAI-compatible)</summary>

<img src="docs/assets/settings.png" alt="Settings — AI provider adapters (Ollama, OpenRouter, OpenAI-compatible)" />

</details>

## What Luxion does today

Everything below is **shipped and tested** (Phases 0–11a), except where marked
*in progress*:

- **Chat that acts** — streaming replies driven by a **70-tool agent loop**:
  files, memory, repository search, browser, desktop, code, web, mail and
  vision. Every call passes an autonomy matrix with confirmations and an
  audit log.
- **Memory that compounds** — durable facts, preferences and tasks are
  extracted from finished turns, ranked by hybrid vector + keyword recall,
  and injected into every future prompt.
- **Repository knowledge** — indexes your project files (chunked, embedded,
  SQLite-vec) so `search_code` and chat answers start from *your* code.
- **Browser agent** — a Playwright-driven Chromium can open pages, search,
  click, type, extract, download and upload; plus YouTube
  (search / open / play / pause / seek / volume) and Wikipedia
  (search + article summaries over plain HTTP).
- **Desktop automation** — list and focus windows, read a window's controls
  through UI Automation, press keys, type, click, adjust volume/brightness.
- **Coding agent** — analyse a repository, grep it, edit files surgically, run
  commands and tests, and drive `git` / `gh` — the "fix this project" loop
  works end to end (red → edit → green → commit).
- **Web intelligence** — seven **keyless** sources: DuckDuckGo search,
  Open-Meteo weather, RSS/Atom + Hacker News, TVMaze movies, Yahoo finance,
  Cloudflare speed test and a `zoneinfo` world clock — every answer carries a
  provenance stamp.
- **Communication** — send and read **email** over SMTP/IMAP, message
  **WhatsApp** through a persistent WhatsApp Web session (QR login), and raise
  **Windows toast notifications**. No API keys, no business onboarding.
- **Vision** — Luxion can *look*: `analyze_image` reads a picture file and
  `analyze_screenshot` captures the screen, both handed to a **vision model**
  through the same provider you already use (a local `qwen2.5vl:3b` next to a
  cloud chat model, or the other way round). It also has **eyes and text**:
  `capture_camera` grabs a webcam frame (OpenCV) and `ocr_image` pulls the
  writing out of any picture — RapidOCR locally when installed, the vision
  model when it is not. The camera is only ever opened by an explicit call, so
  loading Settings never lights the webcam indicator.
- **Voice** — wake word, push-to-talk, streaming STT (faster-whisper),
  TTS replies (SAPI5 or the local OmniVoice model), barge-in while speaking.
- **Your models, your machine** — Ollama by default (fully offline),
  OpenRouter or any OpenAI-compatible endpoint; tap-to-switch in Settings
  without a restart.
- **Permission layers** — OS privacy probes → app consents → account sources
  → per-tool risk engine. A denied mic, screen, terminal or keyboard really
  does block the tool.
- **Local-first** — SQLite, files on disk, secrets only in `.env`. Nothing
  leaves the machine unless a cloud provider is explicitly selected.

## Stack

| Layer | Tech |
|-------|------|
| Desktop shell | Tauri 2 (Rust) — `frontend/src-tauri/` |
| Frontend | React 19 · TypeScript · Vite 8 · Tailwind 4 · three.js — `frontend/` |
| Backend | Python ≥3.11 · FastAPI · SQLAlchemy · Alembic — `backend/` |
| Memory + RAG | SQLite (+ sqlite-vec) · fastembed · hybrid vector + keyword retrieval |
| Local AI | Ollama (default) · OpenRouter · OpenAI-compatible |
| Browser | Playwright (Chromium) · YouTube DOM · Wikipedia REST |
| Desktop | pywinauto / UI Automation · Win32 `ctypes` · pycaw · WinRT |
| Voice | faster-whisper STT · pyttsx3 / OmniVoice TTS |
| Communication | `smtplib` · `imaplib` · WhatsApp Web · WinRT toast |
| Web data | `httpx` · stdlib `xml.etree` (RSS/Atom) · `zoneinfo` (world clock) |
| Vision | Pillow (encode/downscale) · vision models over Ollama / OpenAI-compatible · OpenCV (webcam) · RapidOCR (optional, exact-text OCR) |

## Quick start

> Full walkthrough — prerequisites, model setup, first-run checklist, a guide
> to every page, the permissions model and troubleshooting: **[SETUP.md](SETUP.md)**.

```powershell
# 0. Config — copy .env.example to .env and edit (all vars prefixed LUXION_)
copy .env.example .env

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

The browser agent needs Chromium once:

```powershell
cd backend
.\.venv\Scripts\python.exe -m playwright install chromium
```

## Repository layout

```
Luxion/
├── prd.md                  # Product requirements (source of truth)
├── memory.md               # Project memory — updated after every phase
├── SETUP.md                # Setup + user guide (install, pages, permissions)
├── CONTRIBUTING.md         # Contributor guide (setup, conventions, quality gates)
├── docs/assets/            # README screenshots + demo clip
├── design-system/luxion/   # Persisted design system (ui-ux-pro-max skill)
├── .opencode/skills/       # Agent skills (ui-ux-pro-max, …)
├── backend/                # Python API + agent core
│   ├── luxion/             # app, config, database, logging, api
│   │   ├── browser/        # Playwright session manager (Phase 6)
│   │   ├── calendar/       # .ics sources + events (Phase 3.5)
│   │   ├── coding/         # analyzer, grep, terminal, git/gh (Phase 8)
│   │   ├── context/        # context assembly (tokens, budget, injection)
│   │   ├── desktop/        # Windows control: windows, UIA, input (Phase 7)
│   │   ├── email/          # SMTP send, IMAP read, MIME, drafts (Phase 10)
│   │   ├── llm/            # provider adapters (ollama, openrouter, mock)
│   │   ├── memory/         # memory store, extraction, recall
│   │   ├── notify/         # Windows toast notifications (Phase 10)
│   │   ├── rag/            # chunking, embeddings, sqlite-vec store
│   │   ├── repository/     # workspace scan, index, code retrieval
│   │   ├── security/       # capabilities + consent layer
│   │   ├── tools/          # tool framework + 70 builtins
│   │   ├── vision/         # image pipeline, camera, OCR, model calls (Phase 11)
│   │   ├── voice/          # mic, STT, TTS, wake word
│   │   ├── web/            # search, weather, news, movies, finance… (Phase 9)
│   │   └── whatsapp/       # WhatsApp Web session + DOM ops (Phase 10)
│   ├── alembic/            # migrations
│   └── tests/              # pytest suite (793 tests)
├── frontend/               # React app + Tauri shell
│   ├── src/                # UI (dashboard, chat, memory, tools, integrations, settings)
│   └── src-tauri/          # Tauri 2 (crate `luxion`)
├── scripts/dev.ps1         # runs backend + frontend together
└── OmniVoice/              # git submodule — upstream TTS model (do not edit here)
```

## Tests & checks

```powershell
cd backend
.\.venv\Scripts\pytest.exe        # 793 tests (1 skipped)
.\.venv\Scripts\ruff.exe check .  # lint
.\.venv\Scripts\ruff.exe format --check .

cd ..\frontend
npm run build                     # tsc + vite
npm run lint                      # oxlint
```

## Current status

**Phases 0–10 complete, Phase 11 complete (11a + 11b + 11c)** — architecture;
streaming chat + provider adapters (Ollama / OpenRouter / OpenAI-compatible,
tap-to-switch); context manager; tool framework with **70 built-ins**, autonomy
matrix, confirmations and audit log; capabilities & consent (OS probe, app
consents, risk engine); voice (STT, TTS, wake word, barge-in); memory store +
RAG index + context injection; repository indexing + `search_code`; browser
agent (Playwright + YouTube + Wikipedia); computer automation (Windows control
+ `input_control` capability); coding agent (analyzer, grep, edit, terminal,
git/gh); web intelligence (seven keyless sources with provenance stamps);
communication (email over SMTP/IMAP, WhatsApp Web, Windows toasts); and
**vision** (image + screenshot analysis through a vision model on your existing
provider, webcam capture, OCR, and **voice + face second-factor authentication**
— MFCC/DTW voiceprints and YuNet/SFace faceprints, templates kept on this
machine). See [memory.md](memory.md) for the full phase log and
[SETUP.md](SETUP.md) for the user guide.

## Roadmap

| | Phase | Status |
|--|-------|--------|
| ✅ | 0–10 | Architecture → communication (see above) |
| ✅ | 11 | Vision + Hardware — **complete** (vision core, camera + OCR, voice/face auth) |
| 🚧 | 12 | 3D Orb — **12a done** (all 11 status states, voice-reactive, click-to-listen); 12b pending (Tauri floating window + tray) |
| ⬜ | 13 | Advanced Agent |

## Contributing

Contributions are welcome — code, tools, web sources, tests, docs and UI work
all count. Start with **[`CONTRIBUTING.md`](CONTRIBUTING.md)**, which covers:

- **Setup** — prerequisites, backend/frontend/dev-script walkthrough, Playwright
  and Ollama steps.
- **Conventions** — Ruff (line length 100), Tailwind v4 tokens in `@theme`, the
  `.editorconfig` rules, and the one-way import rule between backend packages.
- **Adding a tool** — the `Tool`/`ToolSpec` contract, risk tiers, capability
  gating and where to register it.
- **The permission model** — the four layers, and why a denied capability is a
  hard block no autonomy level can override.
- **Quality gates** — the exact commands that must be clean before a push.

Two rules worth calling out up front:

1. **FOSS-first.** Phases 8, 9 and 10 each shipped *zero* new Python
   dependencies — the standard library and free CLIs are preferred. If a change
   needs a new package, justify it in the PR.
2. **`memory.md` is updated in the same PR.** It is the living project log; a
   behaviour change without a log entry is incomplete.

Good first issues are labelled `good first issue` — scoped so a new contributor
can finish them in an evening.

## Docs

- [`SETUP.md`](SETUP.md) — install, run, page-by-page guide, permissions model, troubleshooting
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — how to contribute: setup, conventions, adding a tool, quality gates
- [`prd.md`](prd.md) — full requirements (source of truth)
- [`memory.md`](memory.md) — living status log, phase notes, gotchas
- [`design-system/luxion/MASTER.md`](design-system/luxion/MASTER.md) — UI design rules
- http://127.0.0.1:8756/docs — live Swagger/OpenAPI reference while the backend runs

## License

MIT — see [`LICENSE`](LICENSE). Contributions are licensed under the same
terms; see [`CONTRIBUTING.md`](CONTRIBUTING.md) for the contribution guide.

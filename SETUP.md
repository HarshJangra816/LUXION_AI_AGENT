# Luxion — Setup & User Guide

Everything you need to install Luxion, connect an AI model, and use every
feature. Windows 10/11 only (the desktop-automation and TTS features are built
on Windows APIs).

---

## 1. What Luxion is

A **local-first personal AI agent**: a FastAPI backend (Python 3.11+) with a
React 19 + Vite frontend, packaged as an optional Tauri 2 desktop app. You
chat with a local or cloud LLM; when a request needs an action, the model calls
one of **66 tools** on your machine — files, browser, desktop apps, code,
calendar, live web data, email, WhatsApp, Windows notifications, **image
analysis** and **webcam capture + OCR**. Every capability has a permission gate
you control.

---

## 2. Prerequisites

| Requirement | Version | Needed for | Notes |
|---|---|---|---|
| **Windows** | 10/11 | everything | Desktop automation, TTS and toast notifications are Windows-native |
| **Python** | 3.11+ | backend | `python --version` |
| **Node.js** | 20+ (LTS ok) | frontend | `node --version` |
| **Ollama** | latest | local LLM (recommended) | https://ollama.com — install pulls a background service |
| **Rust** | stable | *optional* — Tauri desktop shell | https://rustup.rs — skip if you only use the browser UI |
| **git** | any | *optional* — coding-agent git/gh tools | git + GitHub CLI (`gh`) are detected and shown in Tools |

Nothing else is required: all Python dependencies (voice, RAG, browser,
desktop, web, e-mail, **camera + OCR**) install with the backend — there are no
API keys for the web tools (all seven web sources are keyless), and the
communication tools (email, WhatsApp, notifications) use **your own accounts**,
not a paid API. OpenCV and RapidOCR are free/open-source; RapidOCR is optional
(`ocr_engine=vision` transcribes with your vision model instead).

---

## 3. Install

Open **PowerShell** in the project root.

### 3.1 Configure

```powershell
Copy-Item .env.example .env
notepad .env
```

The defaults work for a local setup. The values you may want to change now:

- `LUXION_LLM__PROVIDER` — `ollama` (default, local) or `openrouter` / `openai` (cloud)
- `LUXION_APP__DATA_DIR` — where the database and settings files live (default: `<project>\database`)

Every variable is documented inline in `.env.example`; see
[§9 Configuration reference](#9-configuration-reference).

### 3.2 Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\pip.exe install -e ".[dev]"
```

Then install the Playwright browser once (drives the `browser_*` tools):

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
```

### 3.3 Frontend

```powershell
cd ..\frontend
npm install
cd ..
```

### 3.4 Model (pick one)

**Option A — Ollama (fully local, recommended):**

```powershell
ollama pull qwen3.5:2b        # small + fast; or a bigger model if you have RAM
ollama serve                  # usually already running as a service
```

Any Ollama model works (`llama3.2`, `gemma3`, `deepseek-r1`, …). Luxion
auto-detects the first model the adapter reports; you can also pick the model
per adapter in **Settings → AI provider**.

**Option B — OpenRouter (one key, 500+ cloud models):** put the key in `.env`:

```ini
LUXION_LLM__PROVIDER=openrouter
LUXION_LLM__MODEL=deepseek/deepseek-chat
LUXION_LLM__API_KEY=sk-or-v1-...
```

Or leave `LUXION_LLM__PROVIDER=ollama` in `.env` and just **tap the OpenRouter
adapter in Settings** once the key is in your environment — adapters switch at
runtime, no restart.

---

## 4. Run

### Option A — everything at once

```powershell
.\scripts\dev.ps1
```

Starts backend **and** frontend (creates the venv on first run). Ctrl+C stops
both. Open **http://localhost:5173**.

### Option B — separately

```powershell
# Terminal 1 — backend on http://127.0.0.1:8756
cd backend
.\.venv\Scripts\python.exe -m luxion

# Terminal 2 — frontend on http://localhost:5173
cd frontend
npm run dev
```

Useful backend URLs:

- http://127.0.0.1:8756/api/health — health probe (the Dashboard dot uses this)
- http://127.0.0.1:8756/docs — interactive API docs (Swagger UI)

### Option C — desktop app (Tauri)

```powershell
cd frontend
npm install
npx tauri dev
```

Compiles the Rust shell (first run takes a few minutes) and opens a native
window that hosts the same UI. For an installer: `npx tauri build`.

---

## 5. First-run checklist

1. **Start** with `.\scripts\dev.ps1` and open http://localhost:5173.
2. **Dashboard** — the status dot turns green when the backend is reachable;
   each subsystem chip shows its state.
3. **Settings → AI provider → Test connection** — verifies the model endpoint
   and lists the models it reports. If it fails, check §11 Troubleshooting.
4. **Tools → Permissions & capabilities** — grant what you want the agent to
   use. Nine capabilities are registered; notable defaults:
   - **Screen capture** is *prompted* — the model can't take screenshots until
     you press **Allow** here.
   - **Terminal** is **OFF** — command execution, tests, installs and git tools
     stay denied until you enable it (this is deliberate).
   - **Keyboard & mouse control** (`input_control`) gates the raw-injection
     desktop tools (type, click, hotkeys).
   - **Microphone / speaker** — required for voice; **camera / location** are
     probed read-only from the Windows privacy settings. The **camera**
     capability gates `capture_camera` and the Vision card's webcam buttons —
     Windows must allow Luxion's webcam access.
5. **Memory → Index files** — point it at a folder (e.g. a notes or project
   directory) so retrieval-augmented answers work. The first index downloads
   the embedding model once (~220 MB, cached).
6. **Integrations** — every family ships enabled **except e-mail**, which stays
   off until you point it at an SMTP/IMAP server (see the Email card).
7. **Try it** — go to Chat and use one of the [example prompts](#8-example-prompts).

---

## 6. Using Luxion — page by page

The left sidebar (bottom bar on mobile): **Dashboard · Chat · Memory · Tools ·
Integrations · Settings**.

### Dashboard

System health at a glance: backend status, model, provider, autonomy level,
tool/capability counts, memory stats, and quick actions (Start chat, Open
settings). All numbers are live from the API.

### Chat

The main surface.

- **Ask anything.** Streaming replies; the composer shows a live **usage meter**
  (tokens sent vs. the context budget).
- **Tool chips.** When the model calls a tool you see the call as a chip —
  done → green outline, running → amber pulse, error → red.
- **Confirmations.** Higher-risk actions pause and ask **Allow / Deny**
  (180 s timeout, then they are refused). You are always in the loop. A tool
  you always want can be switched to **Allow** in the Tools card instead
  (`<data_dir>/tool_permissions.json`).
- **Stop** aborts a reply mid-stream.
- **Voice input** — the mic button has two modes (toggle in Settings →
  Integrations → Voice):
  - **Push-to-talk**: hold to record, release to transcribe (15 s budget).
  - **Live mic + wake word**: say *"Hey Luxion"*, wait for the beep, then speak.
- **Usage & context** — the meter tooltip and Settings → Context & usage show
  exactly how the window is split (system prompt / summary / history).

### Memory

What Luxion remembers, and how retrieval works.

- **Memory & knowledge card** (collapsible):
  - Create / list / search memories with kinds: `fact`, `preference`, `task`,
    `project`, `episode`.
  - **Repository index**: choose a folder, press **Index files**, then ask
    questions about that codebase — relevant files are injected into chat
    context automatically.
  - Config: memory limits, retrieval strength (top-k, min score), and the
    per-stream injection switches (memories / repository).

### Tools

Two collapsible cards:

- **Tools** — the full catalog (**66 tools**) grouped by family with risk
  badges (low / medium / high / critical). Per-tool override: **Autonomy
  default / Allow / Ask first / Deny**. "Recent tool activity" is the audit
  log (newest first). Autonomy level and the high-risk guardrail still apply
  on top of your choice — the stricter decision wins.
- **Permissions & capabilities** — the *hard gate* that runs before tool
  permissions: when a capability is off, the matching tools are denied no
  matter what. Windows privacy switches (mic, screen capture) open in Windows
  Settings; in-app consents (terminal, keyboard & mouse, notifications) are
  toggled right here. Includes the **Calendar sources** panel: connect a local
  `.ics` file (writable) or subscribe to a Google/Apple/Outlook iCal URL
  (read-only).

### Integrations

One collapsible card per subsystem — each has its own status chips, Refresh
and Save:

- **Voice** — push-to-talk vs. live mic, wake word ("hey luxion"), TTS on/off,
  voice picker with preview, wake-word sensitivity. Hardware is gated by the
  mic/speaker capabilities.
- **Email** — send and read mail through your own account: SMTP to send
  (smtplib), IMAP to read (imaplib), both stdlib. The family ships **off**
  until you fill in an SMTP/IMAP host. **Test servers** reaches both legs
  once without sending anything; drafts created by the `email_draft` tool are
  listed here until `email_send_draft` sends them. The password is **never**
  typed into the UI — it lives in `.env` (`LUXION_EMAIL__SMTP_PASSWORD`) or in
  the env var you name (`LUXION_EMAIL__SMTP_PASSWORD_ENV`).
- **WhatsApp** — message your contacts through WhatsApp Web (Playwright session
  with a persistent profile — the login survives restarts). **Connect** launches
  the session and shows the login **QR**: scan it once with your phone
  (Settings → Linked devices). Sending is browser automation, so WhatsApp Web
  redesigns can break it; the `whatsapp://` protocol hand-off to the desktop
  app is the fallback path.
- **Notifications** — Windows toast notifications raised through a stdlib-only
  PowerShell call. **Send test** fires a real toast. Tune the title prefix,
  on-screen duration, sound and the cooldown that guards against spam; the
  **notifications** capability is the hard gate.
- **Browser agent** — Playwright Chromium. Toggle enabled/headless (watch it
  work by turning headless off), search engine, timeouts. Powers
  `browser_*` and `youtube_*`; Wikipedia tools use plain HTTP and work even
  when this is off.
- **Desktop automation** — drive this machine's apps: list/focus windows,
  read a window's controls, press keys, type, click, volume/brightness.
  Turning it off makes every `desktop_*` tool answer "disabled".
- **Coding agent** — repository analysis, grep, file edits, terminal, git and
  GitHub CLI. Shows detected `git` / `gh`. Command execution additionally
  needs the **terminal** capability (off by default).
- **Web intelligence** — seven keyless sources: web search, weather, news,
  movies, finance, internet speed, world clock. **Test sources** probes each
  one live and reports per-tool latency.
- **Vision** — let Luxion *look*. Name a **vision model** (`qwen2.5vl:3b`,
  `llama3.2-vision`, `minicpm-v`, `llava:7b` …) and the `analyze_image` /
  `analyze_screenshot` tools hand pictures to it. The call rides the **same
  provider you already use**, so there is no new key — a local vision model can
  sit next to a cloud chat model (fill **Endpoint** to point somewhere else).
  **Test endpoint** checks the model is there without spending a vision call;
  **Analyze screen** captures the display and shows the answer (needs the
  screen-capture consent). Limits: images per request, longest edge, max
  payload, timeout, plus the **default prompt** used when the model asks
  nothing specific.

  Below that, two more panels:

  - **Webcam capture** — **Test camera** probes indices 0–3 and lists the
    devices it can open (**indices**), **Capture frame** grabs a frame and
    shows a live preview plus the saved `data\captures\*.png` path; leave
    **Question** empty to grab a still without spending a vision call, or
    type one to have the model describe it. Needs the **camera** capability.
    **The camera is only opened by these buttons and by `capture_camera` —
    loading Settings never touches the webcam.** Tune device index, frame
    size (default 1280×720) and warm-up frames in the **Camera** column;
    **Save** writes them to `vision.json`.
  - **Read text (OCR)** — enter an image path, pick an **engine** and press
    **Read text**. `auto` (default) uses **RapidOCR** when the package is
    installed — exact, local, free, with per-line boxes — and falls back to
    your vision model when it is missing *or* finds nothing; `vision`
    always transcribes through the model. Shows line count, elapsed ms and
    the transcription. Works with Vision turned off when RapidOCR is present,
    because neither path costs a model call.

### Settings

Four collapsible cards:

- **AI provider** (open by default) — status, credentials, reachability
  (**Test connection**), and **Installed provider adapters**: tap any adapter
  (Ollama, OpenAI, OpenAI-compatible, OpenRouter, Mock) to switch instantly;
  the choice persists across restarts. Per-adapter **model** field with
  suggestions; **Reset to .env** restores the file defaults.
- **Context & usage** — the context budget (window / reserve / reply headroom /
  spendable), lifetime token spend, a bar of the **last turn's** actual window
  split, and the last 5 turns' token counts.
- **Appearance** — interface font, display (mono) font, text size, accent
  colour (presets + custom picker) with a live preview strip.
- **Graphics** — 3D core quality (High/Medium/Low with particle/ring/DPR
  profiles), background brightness, and the detected
  `prefers-reduced-motion` state.

Every card remembers whether you left it open or closed, in your browser.

---

## 7. Permissions model (how decisions are made)

Four layers, resolved **strictest-wins** for every tool call:

1. **Capability hard gate** — OS privacy (mic, camera, location) and in-app
   consents (speaker, screen capture, notifications, keyboard & mouse, terminal,
   calendar). Off ⇒ tool denied, always — no autonomy level can override it.
   Controlled in **Tools → Permissions & capabilities**.
2. **Family master switch** — each family (browser / desktop / code / web /
   email / whatsapp / notify) has an enabled flag in its Integrations card.
   Off ⇒ that family's tools report "disabled".
3. **Autonomy level** (0–5, `LUXION_SECURITY__AUTONOMY_LEVEL`) — which risk
   tiers run without asking: `0 AnswerOnly` (no tools) … `5 AdvancedAutonomy`
   (most things run; high-risk still confirms).
4. **Per-tool override** — your Allow / Ask first / Deny in the Tools card,
   plus the built-in guardrail that always asks for `high`/`critical` risk
   unless autonomy is 4–5 *and* you allowed it.

A confirmation prompt always wins over everything. If a tool always asks and
you never want it to, set it to **Allow** in the Tools card — the choice is
stored in `<data_dir>/tool_permissions.json` and survives restarts.

---

## 8. Example prompts

Try these in Chat (they exercise every family; the model decides which tools
to use):

**Everyday**
- "Summarise the weather in Tokyo this week."
- "What's the latest tech news on Hacker News?"
- "What time is it in Sydney right now?"
- "Run an internet speed test."

**Files & memory** (index a folder first)
- "Remember that my preferred editor is VS Code."
- "What do you know about my projects?"
- "Summarise the README in my indexed notes folder."

**Browser**
- "Search the web for 'local LLM benchmarks 2026' and summarise the top 3
  results."
- "Open YouTube and find a 10-minute video about FastAPI."

**Desktop**
- "What windows do I have open?"
- "Switch to my music player and pause it."
- "Set volume to 30%."

**Communication**
- "Draft an email to alex@example.com summarising today's meeting — don't send
  it yet."
- "Send that draft to alex@example.com."
- "What came in my inbox since yesterday?"
- "WhatsApp +919812345678: I'm on my way."
- "Notify me when the backup finishes."

**Coding** (terminal capability must be ON)
- "Analyse the repository at D:\Projects\my-app — what does it do?"
- "Find every TODO in this codebase."
- "Run the test suite and tell me what failed."

**Calendar**
- "What's on my calendar this week?"

**Vision** (name a vision model in Integrations → Vision first)
- "Look at D:\Projects\my-app\docs\diagram.png and explain the architecture."
- "What's on my screen right now?"
- "Read the text in this screenshot and list the errors."

**Camera + OCR** (need no vision model when RapidOCR is installed)
- "Take a photo with my webcam."
- "What do you see in front of the camera?"
- "Extract all the text from D:\Documents\receipt.png."

**Voice** — press the mic (or say "Hey Luxion") and speak any of the above.

---

## 9. Configuration reference

Settings resolve in this order, later wins:

```
built-in defaults  →  .env  →  process env vars  →  <data_dir> overlay files
```

The overlay JSONs are written by the UI (Settings / Integrations / Tools), so
anything you set there overrides `.env` until you reset it. `.env` itself is
read from the project root.

### Key variables (full list in `.env.example`)

| Group | Variables | Purpose |
|---|---|---|
| App / server | `LUXION_APP__ENVIRONMENT`, `LUXION_APP__DATA_DIR`, `LUXION_SERVER__HOST/PORT` | data location, bind address (default `127.0.0.1:8756`) |
| LLM | `LUXION_LLM__PROVIDER/MODEL/BASE_URL/API_KEY/TEMPERATURE/MAX_TOKENS/REQUEST_TIMEOUT_S/THINK/SYSTEM_PROMPT` | active provider defaults |
| Context | `LUXION_CONTEXT__TOTAL_BUDGET_TOKENS`, `..._RESERVE_TOKENS`, `..._KEEP_RECENT_MESSAGES`, `..._SUMMARY_*`, `..._KNOWLEDGE_MAX_CHARS` | how much window each turn sends |
| Security | `LUXION_SECURITY__AUTONOMY_LEVEL` (0–5), `..._ALLOWED_WORKSPACES`, `..._TERMINAL_TIMEOUT_S` | autonomy + which folders file tools may touch |
| Tools | `LUXION_TOOLS__ENABLED/MAX_ITERATIONS/TIMEOUT_S/MAX_EXPOSED/LOG_LIMIT/CONFIRM_TIMEOUT_S/PLUGIN_DIRS` | tool framework limits, custom plugin dirs |
| Voice | `LUXION_VOICE__*` | STT (whisper model), TTS (SAPI5/OmniVoice), wake word, VAD, mic device |
| RAG | `LUXION_RAG__*` | embedding model, chunking, retrieval, memory extraction |
| Browser | `LUXION_BROWSER__ENABLED/HEADLESS/SEARCH_ENGINE/*_TIMEOUT_S` | Playwright agent |
| Desktop | `LUXION_DESKTOP__ENABLED/UI_AUTOMATION/COORDINATE_FALLBACK/MAX_ELEMENTS` | Windows control |
| Code | `LUXION_CODE__ENABLED/COMMAND_TIMEOUT_S/MAX_OUTPUT_CHARS` | coding agent |
| Web | `LUXION_WEB__ENABLED/TIMEOUT_S/MAX_RESULTS/NEWS_ITEMS/SEARCH_REGION/TEMPERATURE_UNIT/SPEED_*` | the seven web sources |
| Vision | `LUXION_VISION__ENABLED/MODEL/PROVIDER/BASE_URL/API_KEY_ENV/PROMPT/MAX_IMAGES/MAX_DIMENSION/MAX_BYTES/TIMEOUT_S` | the vision model + image limits (the model call reuses your chat provider, so no new key is usually needed) |
| Vision (camera) | `LUXION_VISION__CAMERA_INDEX/CAMERA_WIDTH/CAMERA_HEIGHT/CAMERA_WARMUP_FRAMES` | webcam device and requested frame size (default index 0, 1280×720, 3 warm-up frames) |
| Vision (OCR) | `LUXION_VISION__OCR_ENGINE/OCR_PROMPT` | `auto` \| `rapidocr` \| `vision` (default `auto`) and the prompt used when the vision model transcribes instead of RapidOCR |
| Email | `LUXION_EMAIL__ENABLED/SMTP_HOST/SMTP_PORT/SMTP_SECURITY/SMTP_USERNAME/SMTP_PASSWORD/SMTP_PASSWORD_ENV/IMAP_HOST/IMAP_PORT/FROM_NAME/FROM_ADDRESS/SIGNATURE/TIMEOUT_S/READ_LIMIT` | send via SMTP, read via IMAP — the password lives in `.env` only, never in the overlay |
| WhatsApp | `LUXION_WHATSAPP__ENABLED/HEADLESS/PROFILE_DIR/TIMEOUT_S/LOGIN_TIMEOUT_S` | WhatsApp Web automation (persistent login profile) |
| Notifications | `LUXION_NOTIFY__ENABLED/APP_NAME/DEFAULT_DURATION_S/SOUND/COOLDOWN_S` | Windows toast notifications |
| Logging | `LUXION_LOGGING__LEVEL/JSON_LOGS/CONSOLE` | log format + verbosity |

### Files in the data directory (`<project>\database` by default)

| File | Written by | Contains |
|---|---|---|
| `luxion.db` | backend | chats, messages, memories, usage ledger |
| `llm_provider.json` | Settings UI | active adapter + per-adapter model |
| `voice.json` | Voice card | voice/wake/TTS overrides |
| `rag.json` | Memory card | embedding model, retrieval knobs |
| `browser.json` / `desktop.json` / `code.json` / `web.json` | Integrations cards | per-family overrides |
| `vision.json` | Vision card | vision model, endpoint and image limits |
| `email.json` / `whatsapp.json` / `notify.json` | Integrations cards | communication overrides (never holds the SMTP password) |
| `calendar_sources.json` | Permissions card | connected `.ics` files and iCal subscriptions |
| `capabilities.json` | Permissions card | in-app capability consents |
| `tool_permissions.json` | Tools card | per-tool Allow / Ask / Deny overrides |
| `tool_log.jsonl` | tool framework | audit log (last 500 calls) |
| `email_drafts/` | `email_draft` tool | saved drafts (one JSON per draft) |
| `whatsapp_profile/` | WhatsApp session | the persistent browser profile — keeps the login |
| `downloads/` | browser_download | files the agent downloads |

---

## 10. Verify your install (optional)

```powershell
# Backend tests + lint  (793 tests, ~56 s)
cd backend
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .

# Frontend lint + build
cd ..\frontend
npm run lint
npm run build

# Live API smoke — hit the running backend
cd ..
Invoke-RestMethod http://127.0.0.1:8756/api/health
Invoke-RestMethod http://127.0.0.1:8756/api/tools | Select-Object -ExpandProperty tools | Measure-Object
```

(The full end-to-end tool check is an internal script — `scripts/verify_tools_live.py`
— and lives outside the repo. If you write your own, set
`$env:PYTHONIOENCODING='utf-8'` first: the console otherwise crashes printing
tool results on cp1252.)

---

## 11. Troubleshooting

| Symptom | Fix |
|---|---|
| Dashboard dot red / "backend unreachable" | Backend not running or wrong port. Check the `dev.ps1` window; `Invoke-RestMethod http://127.0.0.1:8756/api/health`. |
| `Address already in use` on 8756 | A previous backend is still running: `Get-Process python \| Where-Object {$_.Path -like '*Luxion*'} \| Stop-Process`, or change `LUXION_SERVER__PORT`. |
| **Test connection** fails (Ollama) | `ollama serve` then confirm `Invoke-RestMethod http://127.0.0.1:11434/api/tags`. Pull a model if none: `ollama pull qwen3.5:2b`. |
| Chat replies "hang" while streaming | You're running the backend with `--reload`; the dev reloader swallows streamed chunks. Start it without `--reload` (the default for `python -m luxion`). |
| Browser tools answer "run `python -m playwright install chromium`" | Do exactly that with the venv's Python (§3.2). |
| Terminal / run_command always denied | The **terminal** capability is off by default — enable it in **Tools → Permissions & capabilities**. |
| Email tools answer "disabled" | The e-mail family ships **off** — fill in the SMTP/IMAP hosts in **Integrations → Email** and set `LUXION_EMAIL__ENABLED=true` in `.env`. |
| Email tool says "authentication failed" | Most hosts want an **app password**, not the account password (Gmail: 2-Step Verification → App passwords). |
| WhatsApp card shows no QR | **Connect** launches a fresh WhatsApp Web session; the QR appears once the page loads (up to ~15 s). It is rendered in the card from a screenshot, so headless is fine. Scan it from WhatsApp → Settings → Linked devices. |
| Notifications do not appear | The **notifications** capability must be on, and Windows focus-assist/"Do not disturb" must be off. **Send test** fires a real toast. |
| Voice mic does nothing | Grant the **microphone** capability; on first use the whisper model (~150 MB for `base.en`) downloads once. |
| First memory index is slow | The embedding model (~220 MB) downloads once, then indexing is CPU-bound; watch the Memory card for progress. |
| Wake word triggers while TTS speaks | Speaker echo — use headphones, or enable barge-in only in quiet rooms (Voice card). |
| `analyze_image` answers "vision is turned off" | Turn the family on in **Integrations → Vision** (or `LUXION_VISION__ENABLED=true`). |
| `analyze_image` answers "no model" / gibberish | The chat model can't see. Set **Vision model** to a vision checkpoint (`ollama pull qwen2.5vl:3b`) and press **Test endpoint**. |
| `capture_camera` / **Test camera** says it could not open | Missing, busy in another app, or blocked — check **Settings → Privacy → Camera** on Windows and that the **camera** capability is allowed. `POST /api/vision/cameras` lists the indices the driver reports. |
| **Capture frame** saved but the preview looks black | Point it at a lit subject and try again; the driver needs a few frames to settle auto-exposure, which is what **Warm-up frames** skips. Raise it (e.g. 5) if the first frame is still dark. |
| `ocr_image` answers "no model" / an empty result | Set **OCR engine** to `auto` (RapidOCR, if `rapidocr-onnxruntime` is installed) for exact text, or `vision` and confirm the vision model above is reachable. |
| `ocr_image` answers "RapidOCR is not installed" | `pip install rapidocr-onnxruntime` in the backend venv, or switch the engine to `vision` — the fallback needs no package. |
| Weird `�` crashes in PowerShell scripts | Set `$env:PYTHONIOENCODING='utf-8'` before running Python scripts by hand. |
| Chat answer mentions "thinking" but never answers | A reasoning model with `LUXION_LLM__THINK=true`; set it to `false` (default) until you want raw thinking streams. |

**Where to look when something breaks**

- Backend console output (structured JSON logs; `LUXION_LOGGING__LEVEL=DEBUG`
  for more)
- `<data_dir>/tool_log.jsonl` — every tool call with result + duration
- Browser devtools console (F12) for frontend errors
- http://127.0.0.1:8756/docs — the live Swagger/OpenAPI endpoint reference
- [memory.md](memory.md) — phase notes, known gotchas and open follow-ups

---

## 12. Reset & uninstall

- **Reset one thing** — each card has a reset affordance (e.g. Settings →
  *Reset to .env*, Tools → *Reset all overrides*), or delete the specific
  overlay JSON in `<data_dir>`.
- **Factory reset** — stop Luxion, delete the data directory (default
  `<project>\database`): removes the database, all overlays, the audit log and
  downloads. Everything rebuilds on next start; `.env` is untouched.
- **Uninstall** — delete the project folder (and the data directory if you
  set it elsewhere). Optional cleanup: `ollama rm <model>`, the HuggingFace
  cache (`~\.cache\huggingface`) for whisper models, and the fastembed cache
  for embeddings.

---

Happy agenting. Phases 0–10 are shipped and tested, and **Phase 11a (the
vision core)** and **Phase 11b (the webcam + OCR)** landed on top of them;
**11c (voice + face authentication)** is next, followed by Phase 12 (3D orb
behaviour) and Phase 13 (advanced agent). See the roadmap in [prd.md](prd.md)
and the live status in [memory.md](memory.md).

# Luxion — Project Memory

> Living document. **Update after every phase.** Read this first when resuming work.
> Companion to `prd.md` (source of truth for requirements) and
> `design-system/luxion/MASTER.md` (source of truth for UI design).

---

## Current Status

| Field | Value |
|-------|-------|
| **Current phase** | Phase 5 — Memory + RAG: **5a ✅**, **5b ✅**, **5c ✅**, **5d ✅**; **Phase 6 — Browser Agent ✅** (2026-10-11, committed `9c240f9`); **Phase 7 — Computer Automation ✅** (2026-10-15, committed `e528940`); **Phase 8 — Coding Agent ✅** (2026-10-15, committed `70f02ff`); **Phase 9 — Web Intelligence ✅** (2026-10-20, committed `ca27319`); **UI restructure ✅** (2026-10-20, collapsible settings cards + Tools/Integrations nav pages); **Phase 10 — Communication ✅** (2026-10-20, committed `87c65b1`); **Phase 11 — Vision + Hardware: 11a ✅** (2026-10-21) |
| **Next phase** | **Phase 11b — camera capture + OCR** (adds `opencv-contrib-python`; optional `rapidocr-onnxruntime`), then **Phase 11c — voice + face authentication** (adds the `biometrics` capability). After that: **Phase 12 — 3D Orb interaction** (core in place), **Phase 13 — Advanced Agent**. Near-term follow-ups: eyeball the new Integrations cards; live-verify a real SMTP/IMAP probe, the WhatsApp QR login and a toast on this machine |
| **Last updated** | 2026-10-21 (Phase 11a — vision core: image plumbing in the providers, `luxion/vision/`, `analyze_image` + `analyze_screenshot`, `/api/vision`, Settings → Vision card) |
| **Backend tests** | **744 passing**, 1 skipped (gh CLI), `ruff check` + `ruff format --check` clean (210 files) — +32 from Phase 11a |
| **Frontend build** | `tsc -b && vite build` OK (exit 0), `oxlint` clean — `lib/vision.ts` + `VisionCard.tsx` added this session |
| **Tauri shell** | `cargo check` OK (icons still the old Vite logo) |
| **Git** | main branch, **all pushed to `origin/main`** (2026-10-21): Phase 9 as `ca27319`, **UI restructure as `3d8f77b` (own commit)**, SETUP.md as `fad6cb8`, Phase 10 as `87c65b1`, docs refresh as the last commit. Earlier: Phase 7 `e528940`, Phase 8 `70f02ff`. README refreshed with logo, screenshots (`docs/assets/`), demo video |
| **Default adapter** | **Ollama**, model **pinned to `qwen3.5:2b`** in `database/llm_provider.json` (was auto-detect → `nemomix-local:latest`, since deleted from Ollama); `llm.think=false` |
| **Permission layers** | 4: OS privacy gates (read-only probe) → app consents → account sources → tool risk engine (Phase 3). Capability check runs **before** the risk engine. Voice re-uses the same gate (`microphone`, `speaker`); desktop input injection uses `input_control` (Phase 7); command execution uses `terminal` (Phase 8, **default OFF**). |
| **FOSS-first rule** | (user, 2026-10-15) prefer free/open-source like OpenCode: stdlib + FOSS CLIs only — Phase 8 added **zero** new Python deps (stdlib subprocess/re/tomllib + the user's own git/gh), **Phase 9 also added zero** (stdlib `xml.etree`/`zoneinfo`/`csv`/`json` + the existing `httpx`; every web source is keyless) and **Phase 10 added zero** (stdlib `smtplib`/`imaplib`/`base64`/`subprocess` + the existing `playwright` + a built-in PowerShell call; WhatsApp/email/notify need no API keys or business onboarding). Keep new phases on this diet. |

---

## Phase Log

### Phase 0 — Architecture ✅ (2026-09-30)

**Delivered**

- `backend/` — FastAPI app factory (`luxion/api/app.py`), config system
  (`luxion/config/settings.py`, env vars prefixed `LUXION_`, nested `__`),
  structured JSON logging with secret redaction (`luxion/logging_setup.py`),
  SQLAlchemy models `Conversation`/`Message`, Alembic migration
  `db17a276b611_initial_schema_conversations_messages`, health endpoints
  `/api/health` + `/api/version`, 17 tests.
- `frontend/` — React 19 + TypeScript + Vite 8 + Tailwind 4 dashboard shell,
  backend health polling (5s), Vite proxy `/api → 127.0.0.1:8756`.
- `frontend/src-tauri/` — Tauri 2 shell (crate `luxion`, identifier
  `com.luxion.desktop`, 1120×740 window, min 900×600).
- `scripts/dev.ps1` — starts backend + frontend together.
- READMEs: root + backend.

**Bugs fixed in pre-existing backend code**

1. `settings.py:49` — docstring ended with 4 quotes → SyntaxError (broke all imports).
2. `tests/test_health.py` — `TestClient` used without import → collection error.
3. `luxion/database/__init__.py` — missing `get_session_factory` export.
4. `LoggingConfig.json` field shadowed `BaseModel.json()` → renamed `json_logs`
   (env var now `LUXION_LOGGING__JSON_LOGS`).
5. `test_workspaces_string_parsing` — asserted `/` paths, Windows `Path` normalizes to `\`.

**Design work (ui-ux-pro-max skill)**

- Generated + persisted design system → `design-system/luxion/MASTER.md`.
- Direction: **Glassmorphism**, dark tech + status green, Fira Sans (body) /
  Fira Code (headings), slate palette (`#0F172A` bg, `#22C55E` accent).
- Dashboard restyled accordingly; fonts bundled locally via `@fontsource`
  (latin subsets only) — no CDN, works offline in Tauri.

---

### Phase 1 — Luxion Core ✅ (2026-09-30) + visual overhaul

**Backend (47 tests, ruff clean)**

- **LLM abstraction**: `luxion/llm/` — `base.py` (provider protocol),
  `registry.py`, `types.py`, `errors.py`, `system_prompt.py`, providers
  `mock`, `ollama`, `openai_compat` (no new Python deps; `httpx` only).
- **Routes**: `GET/POST /api/conversations`, `GET/DELETE
  /api/conversations/{id}`, `POST /api/conversations/{id}/messages`
  (SSE `StreamingResponse` via `api/sse.py`), `GET /api/llm/status`,
  `GET /api/llm/health`, plus the Phase 0 health/version routes.
- **Services**: `services/chat.py` (persist + stream), `services/conversations.py`.
- Config: provider/base_url/model/api_key via `LUXION_LLM__*` env vars.

**Frontend**

- `features/chat/ChatPage.tsx` — conversation list, SSE token streaming,
  `initialDraft` hand-off from the dashboard ask bar.
- `features/settings/SettingsPage.tsx` — LLM provider section, **Graphics**
  (quality / brightness / reduced-motion readout) and **Appearance**
  (interface font, display font, text size, accent colour + live preview).
- `lib/aiState.tsx` (AI state machine + click pulse), `lib/graphics.tsx`
  (quality presets, `brightness` 0.4–1), `lib/appearance.tsx` (fonts/scale/
  accent provider, re-points `--color-accent` / `--color-tint` at runtime).
- **Blueprint AI core** (`components/three/`, React Three Fiber, code-split
  behind `lazy(() => import('./components/three/AI3DCore'))`): `CoreCore`,
  `CoreShell`, `CoreWireframe`, `CoreRings`, `CoreParticles`, `CoreField`,
  `CoreHUD` (real FPS / energy / AI-state read-out), `coreDrive.tsx`.
- `components/Logo.tsx` (`public/logo.png`, black plate dropped with
  `mix-blend-mode: lighten`, SVG fallback), `GlassPanel`, `AIStatus`,
  `AmbientBackground`, `StatusDot`, `icons.tsx`.
- **Galaxy layer** `components/GalaxyField.tsx` (inside `AmbientBackground`,
  below the canvas and the readability scrim): two box-shadow star sheets
  (seeded PRNG, clustered on a galactic band through the core), two cool
  nebulae, and an **amber bokeh drift** across the top of the view — 26 blurred
  warm blobs at 65 % opacity, faded downward and **mask-punched out around the
  core** (`radial-gradient(circle 320px at 53.7% 40%, …)`) so it never sits on
  the orb. Pure CSS, no new deps, neutralised by the global reduced-motion rule.
  The old orb-centred conic swirl + halo were removed at the user's request.
- **Readability**: `@theme` tokens, `.scrim` gradient (0 → 0.05 @38 % →
  0.55 @54 % → 0.88 @100 %), raised panel opacities, `--lux-scale` on `html`.

**Critical bug found & fixed**

Design tokens were declared in a plain `:root` block, so Tailwind 4 never
generated `bg-panel` / `text-ink` / `bg-accent` / `text-muted` etc. — panels
rendered transparent and text was invisible. Tokens must live in **`@theme`**
in `src/index.css`. Verified: `.bg-panel` ×11 in the built CSS.

**HUD overlap fix (dashboard)**

The SYS / RENDER / MODE / CHARGE labels are drawn by `CoreHUD` at fixed
viewport coordinates, so content scrolling past could slide underneath them.
`DashboardPage` is now **one scroll container** whose first child is a
reserved core band:

1. core band — `h-[46vh] min-h-[280px]` strip (inside the scroller) held for
   the WebGL core + HUD;
2. everything else (greeting hero, form, metrics, recent activity) flows
   normally below it, so the page scrolls as a single sheet.

`CoreHUD` box = `top-[36%] h-[min(320px,30vh)] w-[min(820px,calc(100vw-17rem))] left-[calc(50%+7.5rem)]`
and the invisible core click target = `size-[clamp(130px,17vw,210px)]`; both
were sized so they stay inside the core band (verified for 500–1200 px
viewport heights), which also stops the target from swallowing clicks on
content.

**HUD recedes on scroll** — `DashboardPage`'s scroller publishes
`--lux-core-scroll` (0 → 1 over the first 160 px, rAF-throttled, reset on
unmount); `.hud-parallax` inside `CoreHUD` maps it to
`translateY(-56px) scale(1-0.18) blur(0→2.5px) opacity(1-1.25·p)` — the labels
move back and vanish as content scrolls past, with zero React re-renders.
That is the *only* scroll var left: the hero's sticky travel/pin/fade
(`--lux-hero-move` / `--lux-hero-fade`, `.dash-hero*` rules) was built and
then **reverted at the user's request** — no pinned panel, no frosted bar,
no border around the greeting/logo/slogan. The hero just scrolls away
naturally with the page; do not re-add sticky chrome there.

**Note on the orange bokeh in screenshots**: that is the *core's own* warning
colour (`coreDrive.tsx` `STATE_COLOR.warning = '#fbbf24'`) on the halo/particle
sprites while the backend is offline — not the galaxy layer. User chose to
leave the orb exactly as-is (state feedback intact).

---

### Phase 1 addendum — OpenRouter provider ✅ (2026-10-01)

User chose OpenRouter as the cloud provider (Ollama **stays** the shipped
default — PRD §3.3 local-first). Rejected the "free unlimited tokens" idea:
no such thing exists; open-source repos only *pool* free rate-limited tiers
(`open-free-llm-api/awesome-freellm-apis`, `0xzr/freellmpool`,
`dklymentiev/free-llm-api-stack`, LiteLLM/new-api/one-api). Those remain an
optional later add-on — anything OpenAI-compatible plugs in via
`LUXION_LLM__BASE_URL`, no Luxion changes.

**Backend**

- `llm/providers/openrouter.py` — `OpenRouterProvider(OpenAICompatProvider)`:
  base URL falls back to `https://openrouter.ai/api/v1` when the configured
  one is empty **or** still the Ollama sentinel, `X-Title: Luxion` header,
  `default_api_key_env = "OPENROUTER_API_KEY"`.
- `config/settings.py` — new `OLLAMA_BASE_URL` constant (= old inline default)
  used by `LLMConfig.base_url`; it is now the "unset" sentinel for providers
  that bring their own URL.
- `llm/base.py` — `default_api_key_env` class attr + `api_key` falls back to
  it; `base_url` property moved/merged (was duplicated → ruff F811) and now
  tolerates empty config.
- `llm/types.py::TokenUsage` — added `cost: float|None` (USD, OpenRouter
  reports it on **every** response, no extra params) and
  `cached_tokens: int|None` (PRD §45).
- `providers/openai_compat.py::_read_sse` — parses `usage.cost` +
  `prompt_tokens_details.cached_tokens` via new `_as_int`/`_as_float` guards.
- `services/chat.py::_persist_assistant` — stores `usage.cost` in
  `messages.meta["cost_usd"]` (**not** a new column — avoids a migration on
  the live `database/luxion.db`; Phase 2's usage service sums it in Python
  from light-weight row queries).
- `api/schemas.py` — `MessageOut.cost_usd`; `build_llm_status` now reports the
  **effective** `provider.base_url` and `api_key_env or provider.default_…`,
  so Settings shows `OPENROUTER_API_KEY` when unset.
- `registry.py` — `openrouter` in `PROVIDER_TYPES` + `PROVIDER_SPECS`
  (auto-appears in the Settings adapter list).
- `.env.example` — documented the 2-line OpenRouter switch.

**Frontend**

- `lib/chat.ts` — `TokenUsage.cost`/`.cached_tokens`,
  `ChatMessageDto.cost_usd`.
- `ChatPage` — header now shows the last turn's meter
  (`12 turns · 120 in · 30 out · $0.0042 tok`) from `ChatDone.usage` live and
  re-derived from `messages` on load; cleared on new/switch/delete.

**Tests**: `tests/test_openrouter_provider.py` (14) — base-url sentinel
behaviour, key-resolution precedence, SSE usage/cost/cached parsing, request
headers, registry + status exposure, cost persistence (present and absent).

**Not done yet (deliberately)**: no live OpenRouter call (no API key here);
enable it yourself with `LUXION_LLM__PROVIDER=openrouter` +
`LUXION_LLM__MODEL=<vendor/model>` + a key.

---

### Phase 2 — Context Manager ✅ (2026-10-01)

PRD §3.2 *Context efficiency*: never send the whole history; trim to fit the
window, summarize what was cut, and show the user where the tokens go.

**Backend — `luxion/context/` package** (imports `services`, never the
reverse; `HistoryRecord` lives in `context/records.py` to break the cycle)

- `tokens.py` — estimator, no tokenizer dep: `CHARS_PER_TOKEN = 4`,
  `MESSAGE_OVERHEAD_TOKENS = 4`, `MIN_KEEP_CHARS = 80`,
  `TRUNCATION_SUFFIX = "\n…[truncated]"`.
- `budget.py` — `ContextConfig → ContextBudget`:
  `total = reserve + response + system + summary + history`, clamped
  `reserve = min(cfg.reserve, total // 2)` and
  `response = min(llm.max_tokens, max(1, total // 4))`.
- `summary.py` — summary prompt/composition + read/write of summary state.
- `compression.py` — what actually got sent: `"summary"` if messages were
  summarized this turn, `"dropped"` if excluded messages are **not yet** in
  the summary (`dropped_count > covered_count`), else `"none"`.
- `manager.py` — `build_context(records, summary, cfg, …)` → trimmed
  messages + `ContextStats`; fails safe (keep everything) if estimation or
  history is unusable.
- `config/settings.py::ContextConfig` — new `keep_recent_messages=6`,
  `summary_enabled=True`, `summary_max_tokens=1200`,
  `summary_min_messages=4`.

**Backend — persistence & API**

- `services/conversations.py` — `history_records()`, `read_summary_state()`,
  `write_summary_state()` (merges into existing meta).
- `services/chat.py` — `_PreparedTurn` carries `records` + `summary`;
  `stream_reply` builds context, persists the summary (own session,
  `run_in_threadpool`, swallows `ConversationNotFound`), attaches `context`
  to `ChatDone` and to the assistant row's `meta`.
- `services/usage.py` — `usage_report()`, `conversation_context()`
  (`allow_summarize=False` → **read-only** preview), `budget_out()`,
  `context_stats_of(meta)`. Costs summed in Python from `messages.meta`
  (still no migration).
- `api/routes/usage.py` — `GET /api/usage`,
  `GET /api/usage/{conversation_id}` (404 via `ConversationNotFound`);
  registered in `api/app.py`.
- `api/schemas.py` — `MessageOut.context`; usage response models re-exported;
  `build_llm_status.api_key_configured` now means *key configured* (a key is
  required **or** a known env var is set), not merely "consumes a key".
- **Security**: a live OpenRouter key was hardcoded in
  `llm/providers/openrouter.py` — restored to `"OPENROUTER_API_KEY"`, moved to
  the gitignored root `.env` (`provider=openrouter`,
  `LUXION_LLM__MODEL=deepseek/deepseek-chat`). **Key should be rotated.**
- `.env.example` — documents every `LUXION_CONTEXT__*` knob.

**Frontend**

- `lib/api.ts` — `ApiError` / `errorFrom` / `request` extracted from
  `lib/chat.ts` (shared by chat, settings, usage).
- `lib/chat.ts` — `ContextStats`, `ChatMessageDto.context`,
  `ChatDone.context`.
- `lib/usage.ts` — usage types + `getUsage()` / `getConversationContext()` /
  `formatTokens()` / `formatCost()`.
- `ChatPage` — header usage line now appends the live context meter
  (`ctx X/Y`), merged from `ChatDone.context` and re-derived on load.
- `SettingsPage` — new **Context & usage** section: budget grid (window,
  reserve, reply headroom, spendable), lifetime totals (messages, tokens in/
  out, spend), policy line, `ContextBar` with compression badge + sent/kept/
  dropped/summarized, recent-turn list, Refresh.

**Tests**: `tests/test_context_manager.py` (tokens, budget clamps, drop,
keep-recent truncation, summary, fallback, meta round-trip, persist,
stream-reply E2E) + `tests/test_usage_api.py` (report, per-conversation
context, read-only preview, 404). **79 passing.**

**HUD fix (folded in)**: `CoreHUD.tsx` SYS `top-6` → `top-1`, RENDER
`bottom-16` → `bottom-1` — labels now clear of the orb content.

**Not verified live**: no browser pass — only `pytest`, `ruff`, `oxlint`,
`tsc`/`vite build`. Ask the user to eyeball the Settings section.

---

### Phase 3 — Tool Framework ✅ (2026-10-01)

**Delivered — backend (`backend/luxion/tools/`)**

- `base.py` — `ToolRisk`/`PermissionLevel`, `ToolError`, `ToolArgumentError`,
  `ToolSpec` (+`as_openai()`), `ToolResult`, `ToolContext`, `Tool` ABC,
  `validate_args()` (JSON-Schema check: required, unknown keys, types).
- `registry.py` — `ToolRegistry`, `build_registry()`, cached
  `get_registry(settings)` / `reset_registry()`.
- `permissions.py` — `AUTONOMY_MATRIX` (6 levels × 4 risks), `STRICTNESS`,
  `PermissionEngine` with **two layers**: the matrix and the
  `require_confirmation_high/critical` guardrails (`max()` of the two), plus a
  user override file `<data_dir>/tool_permissions.json` (per-tool or
  `category:<name>`). Override wins; corrupt file falls back to defaults.
- `audit.py` — append-only JSONL `<data_dir>/tool_log.jsonl`, trimmed to
  `tools.log_limit`, secrets redacted (`key|token|password|secret|credential|
  auth`), output clipped to 2 000 chars. Deliberately a file, **not** a DB
  column — no migration on the live SQLite DB (same call as `cost_usd`).
- `confirmations.py` — `ConfirmationManager`; the answer is stored on the entry
  *and* a future, so `resolve()` may arrive before `wait()` attaches (and it no
  longer requires a running event loop inside `create()`).
- `executor.py` — `prepare()` → optional confirmation → `run()`, or one-shot
  `execute()`. Every outcome lands in the audit log (`_finish`), including
  unknown tool / bad args. `get_executor()` caches by registry+engine key.
- `loader.py` — the 9 built-ins plus `plugin_dirs` scanning for `*.py` exposing
  `TOOLS = [...]` or `register(registry)`; a broken plugin logs and is skipped.
- `router.py` — `select_tools()` (PRD §19): ranks tag/name/description overlap
  even when everything fits under `max_exposed`, relevance-filters when it does
  not, falls back to the ranked head when nothing matches.
- `builtin/` — `time_tools` (get_time, get_date), `system` (system_stats),
  `screenshot` (PIL `ImageGrab`), `files` (`resolve_in_workspace` +
  read_file/write_file), `apps` (open/close application: Start-Menu search /
  `os.startfile`, psutil + `PROTECTED_PROCESS_NAMES`), `web` (open_url, blocks
  `javascript:/file:/data:/vbscript:`). Risks per PRD §20: low/low/…/medium for
  write_file, high for launch+kill.

**Delivered — LLM + agent loop**

- `llm/types.py` — `ToolSchema`, `ToolCall` (+`from_fragments`),
  `ChatMessage.tool_calls`/`tool_call_id`, `TokenUsage.merge()`,
  `StreamDone.tool_calls`.
- `llm/base.py` + all three providers take `tools=`; OpenAI-compatible parses
  incremental `tool_calls` fragments and sends `stream_options.include_usage`;
  Ollama uses its native `tools` field; mock implements the `USE_TOOL <name>
  [json]` trigger (fires once, suppressed when the last role is `tool`).
- `llm/system_prompt.py` — `build_system_prompt(settings, tools)` appends the
  tool guide only when tools are offered; a custom `LUXION_LLM__SYSTEM_PROMPT`
  still overrides verbatim.
- `services/chat.py` — the agent loop: `finish_reason=tool_calls` → permission
  → execute → repeat, capped by `tools.max_iterations` (exhaustion emits
  `error: tool_loop_exhausted`). New SSE events `tool` (start → ok/error/
  denied/timeout/invalid_args) and `confirm`. **Only the final assistant
  message is persisted**; tool rounds live in `meta["tools"]`, so provider
  history never contains an orphaned `tool_calls` message.

**Delivered — API**

- `api/routes/tools.py` (mounted at `/api/tools`): `GET /` catalog (name,
  risk, category, schema, effective permission + reason + override, autonomy
  level, per-risk defaults), `GET /exposed?q=`, `GET|PUT|DELETE /permissions`,
  `GET /log`, `GET|POST /confirmations[/{id}]`, `POST /{name}/run`.

**Delivered — frontend**

- `lib/tools.ts` — catalog/permissions/log/confirmations/run fetchers + types.
- `lib/chat.ts` — `ChatTool`, `ChatConfirm`, `ChatDone.tools`,
  `ChatMessageDto.tools`, `StreamHandlers.onTool/onConfirm`.
- `MessageBubble.tsx` — tool chips above the reply (click to expand
  arguments/output/error), an Allow/Deny confirmation card, `ToolRunView`.
- `ChatPage.tsx` — folds `tool` frames into the live bubble (matches provider
  call id), shows `confirm` and resolves it via `POST /confirmations/{id}`,
  hydrates `meta.tools` on load, AI state → working/warning.
- `SettingsPage.tsx` — new **Tools** section: autonomy badge, per-tool
  permission select (Autonomy default / Allow / Ask first / Deny) with the
  decision reason, Reset all overrides, recent audit log, disabled banner.
- `icons.tsx` — `TerminalIcon`, `ShieldIcon`, `CheckIcon`, `XIcon`.

**Config**: `SettingsToolsConfig` (`enabled`, `max_iterations=6`,
`timeout_s=30`, `max_exposed=16`, `log_limit=500`, `confirm_timeout_s=180`,
`plugin_dirs`); `allowed_workspaces` default = project root and an **empty
env string now falls back to it** (an empty `LUXION_SECURITY__ALLOWED_…=`
used to lock every file tool out). `.env.example` documents `LUXION_TOOLS__*`.

**New deps**: `pillow` (screenshot), `psutil` (process tools), `tzdata`
(Windows has no IANA tz database — `zoneinfo` needs it).

**Tests**: `tests/test_tools.py` (30 — registry/schema/permissions/executor/
workspace/audit/router/plugins), `tests/test_tool_agent.py` (11 — tool rounds,
autonomy 0, deny override, approve/decline, prompt cleanup, iteration cap,
tools disabled), `tests/test_tools_api.py` (13), +2 in `test_settings.py`.
**132 passing.**

**Fixes found while testing**: `select_tools` returned the registry unranked
when under the cap (the `/exposed` preview was useless); `create()`
required a running event loop; `set_override(…, None)` left an empty file.

**Not verified live**: no browser pass — only `pytest`, `ruff`, `oxlint`,
`tsc`/`vite build`. Ask the user to eyeball the tool chips, the Allow/Deny
card and the Settings → Tools section.

---

### Settings addendum — tap-to-switch provider adapters ✅ (2026-10-02)

User request: switch the active adapter **directly from Settings by tapping
it**, and make **Ollama the default**.

**Backend**

- `config/provider_override.py` (new) — the persisted choice:
  `ProviderSelection {active, models[adapter]}`, file
  `<data_dir>/llm_provider.json`, `load/save/clear`. Writes are
  write-then-rename; reads tolerate a UTF-8 BOM (PowerShell 5.1 writes one)
  and a corrupt/unknown file is logged and **ignored** (never fatal).
- `config/settings.py` — `SELECTABLE_PROVIDERS` (ids, in sync with
  `llm.registry.PROVIDER_TYPES` via a test), `SELECTED_BASE_URLS` per adapter
  (`ollama`/`openai_compatible` → keep `LUXION_LLM__BASE_URL`, `openai` →
  `api.openai.com/v1`, `openrouter`/`mock` → `""` so each provider falls back
  to its own endpoint), and `apply_provider_selection()` called from
  `get_settings()`. Priority is now defaults → `.env` → `LUXION_*` env →
  **selection file**. A model id is only remembered per adapter; an adapter
  `.env` describes keeps its configured model, others auto-detect (model ids
  do not transfer — `deepseek/…` sent to Ollama would 404).
- `api/routes/llm.py` — `PUT /api/llm/provider {provider, model?}` (400 on an
  unknown id) and `DELETE /api/llm/provider` (back to `.env`); both
  `await aclose_provider()` → `reset_settings_cache()` → return the rebuilt
  `LLMStatus`, so **no restart** and one round trip for the UI.
- **Secrets**: the selection file stores *no* keys (test asserts the shape) —
  `LUXION_LLM__API_KEY` stays in `.env` and is read by whichever adapter is
  active.

**Config**

- `.env`: `LUXION_LLM__PROVIDER=ollama`, `LUXION_LLM__MODEL=` (auto — an
  Ollama default must not carry `deepseek/deepseek-chat`), key unchanged.
- `.env.example`: documents the four-layer priority + the OpenRouter switch.
- `.gitignore`: added `database/*.json[.tmp]` (runtime state) + `api_key`.
- `database/llm_provider.json` seeded locally (gitignored) with
  `active=ollama` + `models.openrouter=deepseek/deepseek-chat`, so tapping
  OpenRouter restores the previous working setup immediately.

**Frontend**

- `lib/chat.ts` — `setLlmProvider(provider, model?)` / `resetLlmProvider()`.
- `SettingsPage` — new `AdapterCard`: inactive cards are the button
  (“tap to activate”), the active one shows a ✓ **active** chip + a **Model**
  input (suggestions come from `health.models`, i.e. *Test connection*) with
  Save; “Reset to .env” button in the section header; switch errors render
  next to the list; `health` is cleared on switch (it described the old
  adapter). Copy updated (the section no longer claims settings only come
  from `.env`).

**Tests**: `tests/test_provider_switch.py` (22) — store round-trip / corrupt /
BOM, registry-sync guard, override precedence (incl. env-model seeding and
base-url table), PUT/DELETE happy path, persistence across rebuild, 400/422,
no-secrets check. **154 passing.**

**Live smoke test** (backend on port 8761, real `.env`):
`ollama(ollama, auto) → openrouter(deepseek ✓, openrouter.ai ✓) →
ollama(llama3.2) → mock → reset → ollama`, unknown id → 400.

**Not verified**: the browser UI pass — a stale backend (old code, started
before this change) is holding port 8756; **restart `scripts/dev.ps1`** to
pick up the new routes, then eyeball the adapter cards.

---

### Phase 3.5 — Capabilities & Consent ✅ (2026-10-02)

**Why**: PRD §39 "Hardware access must be permission-controlled" + §55 Privacy
required a layer *above* the tool risk engine — "may Luxion use the mic at
all?" is not answerable by autonomy levels. Decisions taken with the user:
build the full framework now, **backend Python mic capture** for Phase 4,
calendar = source abstraction + ICS (Google/Apple/Outlook all publish secret
iCal URLs → zero credentials), speaker = explicit in-app toggle (Windows has
no speaker permission).

**Delivered — backend**

- `luxion/security/capabilities.py` — `Capability` registry (7 entries) and
  `CapabilityStore`. Three kinds:
  - **os** (`microphone`, `camera`, `location`) — read-only probe of
    `HKCU\…\CapabilityAccessManager\ConsentStore\<key>`, desktop-app
    `NonPackaged` gate first → states `granted | blocked_by_os | unavailable`;
    action = `open_settings` (`ms-settings:privacy-*`). **Never writes OS
    state.**
  - **app** (`speaker`, `screen_capture`, `notifications`; defaults all ON so
    nothing existing breaks) — persisted `<data_dir>/capabilities.json`,
    actions `grant | deny | reset`.
  - **account** (`calendar`) — derived from connected sources, never stored.
  - `check(id)` → `CapabilityDecision {state, allowed, reason}`; corrupt file
    → defaults, never fatal.
- **Enforcement**: `ToolSpec.requires` (base.py) + gate in
  `ToolExecutor.prepare()` *before* `engine.decide()` → `status="denied"`,
  `decision.source="capability"`, model sees
  `capability '<id>' denied: <reason>`. Autonomy 5 cannot override. Only
  `take_screenshot → screen_capture` seeded so far.
- `luxion/calendar/` — `sources.py` (own RFC 5545 subset: unfold, DATE /
  floating / UTC / TZID / DURATION parsing, single-pass unescape, 75-octet
  folding, atomic writes) + `LocalIcsSource` (read/write) +
  `IcsSubscriptionSource` (read-only httpx fetch, validated on connect);
  `registry.py` — `<data_dir>/calendar_sources.json`, `add/remove/list/events/
  create_event`, duplicates and non-ics files rejected with user-facing
  messages. Agent-facing calendar tools **deferred** to their own phase.
- **API**: `routes/capabilities.py` — `GET /api/capabilities`,
  `POST /api/capabilities/{id}` `{action, source, target, label, id}`
  (404 unknown id, 400 wrong action / connect errors).
- `ToolInfo.requires` + capability-aware catalog: `/api/tools` shows
  `permission=deny, reason="capability: …"` while a capability is off.

**Delivered — frontend**

- `lib/capabilities.ts` (types, `getCapabilities`, `capabilityAction`,
  `STATE_LABEL`/`STATE_CLASS`).
- Settings → new **Permissions & capabilities** card (ShieldIcon, between
  Tools and Appearance): per-capability row = label + state chip + kind tag +
  description + reason, *Windows settings* / *Allow ↔ Turn off* buttons,
  calendar source list with per-source Remove; below it a **Calendar sources**
  connect form (local .ics path / iCal URL / label, Disconnect all).
- `ToolInfo.requires` + a `tint` chip in `ToolRow` showing the required
  capability.

**Tests**: `tests/test_capabilities.py` (25) — registry shape, read-only OS
probe, probe-driven states, consent round-trip + corrupt file, unknown
capability, calendar state follows sources, report shape, executor gate
(denied at autonomy 5 / allowed when granted / only screenshot declares one),
ICS parse of every common form, local create→read round-trip, escape
round-trip (found + fixed a real `_unescape` bug: chained replaces dropped
literal backslashes — now single-pass regex), subscription read-only,
registry persistence/duplicates/junk, `create_event` needs a writable source,
API round trip + 404/400 + catalog reflection. **179 passing.**

**Live smoke** (port 8762, real `.env`): registry probe reports Allow for all
three OS gates on this machine; speaker deny/grant/reset; mic `grant` → 400,
unknown → 404; calendar connect (real `.ics` created) → duplicate 400 →
disconnect; `screen_capture` off → `/api/tools` `take_screenshot` = deny
"capability: you turned Screen capture off in Luxion"; no leftover state.

**Also**: `.gitignore` += `database/*.ics`.

**Not verified**: the browser UI pass for the new card (stale backend still
holds 8756 — restart `scripts/dev.ps1`).

---

## Conventions & Decisions

- **Layout**: `backend/` + `frontend/` (with `frontend/src-tauri/`) at repo root.
  PRD §50 suggests `app/…` — we deliberately deviated; keep the flat layout.
- **Backend**: Python ≥3.11, sync SQLAlchemy (see `session.py` docstring for
  rationale), SQLite dev / PostgreSQL later, ports `8756`.
- **Config**: never hardcode — `LUXION_*` env vars, `.env` at project root,
  `.env.example` is the documented list.
- **Frontend**: Tailwind v4 tokens **must** live in `@theme` (never plain
  `:root`) in `src/index.css`; they mirror `design-system/luxion/MASTER.md`.
  Add new UI tokens there, not inline hex. `--color-accent`/`--color-tint` are
  re-pointed at runtime by `lib/appearance.tsx`.
- **3D rules**: three.js stays code-split; R3F v9 bridges React context into
  the Canvas (safe to call `useAIState`/`useGraphics` inside it); drive values
  that change per-frame live in mutable `coreDrive` state. **Do not modify
  `CoreCore` / `CoreShell` / `CoreWireframe` / `CoreRings` / `CoreParticles` /
  `CoreField` without asking** — the core visuals are approved as-is.
- **A11y checklist** (from skill, applies to all future UI): cursor-pointer on
  clickables, 150–300ms transitions, visible focus, `prefers-reduced-motion`,
  no emoji icons (use SVG), contrast ≥ 4.5:1.
- **Windows / PowerShell**: never bulk-edit files with `p.replace` in
  PowerShell — it corrupted JSX before (`<` → `d`). Use the edit/write tools
  or a literal `.Replace()` in a script file.
- **Secrets**: `opencode.json` (21st.dev MCP key) is gitignored. Never commit keys.
- **FOSS-first** (user, 2026-10-15): prefer free/open-source like OpenCode —
  stdlib and FOSS CLIs over new package dependencies wherever possible.
  Phase 8 added **zero** Python deps on this rule (stdlib + the user's own
  `git`/`gh`); keep new phases on this diet and justify any new dep.
- **Permission model (4 layers)**: OS privacy gates (probed **read-only**,
  Luxion only opens `ms-settings:`) → app consents
  (`<data_dir>/capabilities.json`) → account sources (calendar registry) →
  tool risk engine. A capability check always runs **before**
  `PermissionEngine.decide()` — denial is a hard block no autonomy level can
  override; never let a tool bypass `ToolSpec.requires`. Speaker has no OS
  permission (playing audio needs none) — it is an app consent, default ON.

---

## Tooling Installed

| Tool | Where | Notes |
|------|-------|-------|
| **21st.dev MCP** | `./opencode.json` | remote MCP, tools: `search`, `get_component`, `get_theme`, `search_picker`, … **Requires opencode restart to load.** |
| **ui-ux-pro-max skill** | `.opencode/skills/ui-ux-pro-max/` | run `python .opencode/skills/ui-ux-pro-max/scripts/search.py "<query>" --design-system` (Windows: `python`, not `python3`). Project design system already persisted. |
| Backend venv | `backend/.venv` | `backend\.venv\Scripts\pytest.exe`, `ruff.exe`, `alembic.exe` |

Other pre-existing skills found in `.opencode/skills/`: `banner-design`,
`brand`, `design`, `design-system`, `slides`, `ui-styling`.

---

## Commands

```powershell
# Backend
cd backend
.\.venv\Scripts\pip.exe install -e ".[dev]"
.\.venv\Scripts\pytest.exe          # tests
.\.venv\Scripts\ruff.exe check .    # lint
.\.venv\Scripts\ruff.exe format .   # format
.\.venv\Scripts\python.exe -m luxion  # serve on 127.0.0.1:8756

# Frontend (browser dev)
cd frontend; npm run dev            # http://localhost:5173 (proxies /api)
cd frontend; npm run lint           # oxlint
cd frontend; npm run build          # tsc -b && vite build

# Desktop app
cd frontend; npx tauri dev          # builds Rust + launches window

# Both together
.\scripts\dev.ps1
```

---

## Open Items / Follow-ups

- [ ] **`p-e-w/heretic` request (user, 2026-10-08)** — user asked to add
  <https://github.com/p-e-w/heretic.git> "so I can get more answers and my AI
  agent gets smarter". Facts established before deciding: Heretic performs
  **directional ablation ("abliteration") on model weights** — it removes
  refusal/safety alignment, it does **not** add knowledge or intelligence, and
  published evaluations show a small *cost* (KL divergence from the original),
  not a gain. It runs offline over HF/PyTorch weights (`pip install heretic-llm`,
  20–30 min for a 4B model on an RTX 3090) — **not feasible on this CPU-only
  box**, and unrelated to the Ollama/OpenAI-compatible API Luxion talks to. It is
  **AGPL-3.0**, so copying its code into Luxion would re-license Luxion AGPL
  (running it as an external process would not). **Awaiting the user's decision**
  before any integration; the real intelligence gains are 5c/5d (RAG +
  context injection), better prompting and the tool loop.

- [x] **Phase 4 remaining — ALL DONE (2026-10-05)**: (1) `frontend/src/lib/voice.ts`
  types + fetchers + `useVoiceEvents`; (2) `MicIcon`/`MicOffIcon`; (3) Composer
  PTT + live-listen toggle; (4) `ChatPage` `/api/voice/events` → `command` →
  streamed chat turn → `POST /api/voice/speak`; (5) Settings → **Voice** card;
  (6) `tests/test_voice.py` + `test_voice_api.py` + `test_voice_tts.py`;
  (7) `pytest` 239 / `ruff` / `oxlint` / `tsc -b && vite build` all clean;
  (8) **live smoke on an alternate port** → see *Phase 4 live smoke* below.
- [ ] **Phase 4 eyeball — the only Phase 4 gap**: wake phrase arms and the next
  utterance runs as a chat turn, PTT fills the composer, a reply is spoken, Stop
  interrupts it. The **mic-denied 400 is already proven at the API level** (no
  need to re-toggle Windows unless you want to see it in the UI).

- [ ] **Run `.\scripts\dev.ps1` for the eyeball** — no stale server is holding
  `127.0.0.1:8756` anymore (verified 2026-10-05), so a fresh start gives you the
  voice routes and `GET|POST /api/capabilities`. The only listener is the smoke
  server on **:8763 (PID 4876)** — stop it when you are done with it.
- [ ] **Eyeball Settings → Permissions & capabilities** (Phase 3.5): state
  chips live, *Windows settings* opens the right Settings page, *Allow/Turn
  off* flips and persists across reload, calendar connect with a blank path
  creates `database/calendar.ics`, per-source Remove works, and denying
  `screen_capture` makes `take_screenshot` in Settings → Tools show
  `deny — capability: …`. In chat, ask for a screenshot while it is off and
  confirm the model gets the capability error.
- [ ] **Eyeball Settings → Installed provider adapters**: tap a card → it
  becomes active (✓ chip), Provider/Model/Base URL fields update without a
  reload, Model input + Save works, “Reset to .env” returns to Ollama.
  Requires a running Ollama for the chat to answer after switching to it.
- [ ] Root file `api_key` (starts `ollama = …`) looks like a secret and was
  **not** gitignored — pattern added; confirm nothing else holds keys.
- [ ] Restart opencode to load the 21st MCP server (config is read at startup).
- [ ] OpenRouter: never called live (no API key in this environment) — user must
  set `LUXION_LLM__PROVIDER=openrouter` + `LUXION_LLM__MODEL=<vendor/model>` +
  a key, then hit Settings → *Test connection*. Cost meter only appears when
  the provider reports `usage.cost` (OpenRouter does; Ollama/mock do not).
- [ ] **Rotate the OpenRouter key** — it was committed in source before being
  moved to `.env` (`sk-or-v1-6bdb…`). Rotate it on openrouter.ai; the key now
  lives only in the gitignored root `.env`.
- [x] **Git — committed & pushed (2026-10-08)**: repo now has **6 commits**
  (… `b3a798d` Phase 4 voice backend, `2a900c0` OmniVoice + voice UI + tests,
  `45d851e` Phase 5 memory + RAG layer, plus this session's Phase 5b/5c +
  `think` fix + docs commit). Working tree clean; no `.env`, no
  `database/*.json` and no API key are tracked.
- [ ] **Re-embed job (follow-up from 5d, deferred by user)** — the embedding
  model can be switched from Settings and `needs_reembed` warns that stored
  vectors belong to the old model, but nothing re-embeds them yet
  (`rebuild_vector_index` only refills vec0 from stored blobs; a real job would
  re-embed chunk text in `rag.reembed_batch` batches, then rebuild + `sync_meta`).
  Until it exists: switch model → keyword-only retrieval for old chunks; the
  workaround is re-running *Index files* after clearing the index, plus
  `DELETE /memory` (memories re-index on next extraction).
- [ ] **Eyeball Settings → Memory & knowledge** (5d): memories list with kind
  chips, add form, search shows scores, clear-all works; toggles + numeric
  rows Save to `rag.json` and "Reset to .env" clears it; embedding-model
  switch shows the amber "re-embed needed" chip; Index-now updates the counts;
  repo preview search returns path:line hits. In chat, a question about a
  project file should get the injected knowledge block (check
  `GET /api/usage/{id}` context preview).
- [ ] **No browser verification yet** — the backend is now proven **live over
  HTTP** (Phase 4 smoke on :8763, see *Phase 4 live smoke*), but no browser has
  rendered the app: ask the user to eyeball HUD labels clear of content, galaxy
  in the blank areas, logo readable, **(Phase 3)** chat tool chips + Allow/Deny
  card + Settings → Tools, **(Phase 3.5)** Permissions & capabilities card,
  **(Settings)** adapter cards, **(Phase 4)** Composer mic/PTT + Settings →
  Voice, **(Phase 5d)** Settings → Memory & knowledge, **(Phase 6)** Browser
  card, **(Phase 7)** Desktop card, **(Phase 8)** Coding card. `vite preview`/headless smoke still aborts (SIGABRT) in this
  environment, so only `pytest`, `ruff`, `oxlint`, `tsc`/`vite` + the HTTP smoke
  count as evidence.
- [ ] Phase 3 tools that need a live machine check: `take_screenshot`
  (PIL `ImageGrab`), `open_application`/`close_application` (Start Menu +
  psutil), `open_url` (default browser). `read_file`/`write_file` are scoped
  to `allowed_workspaces` (default = project root).
- [ ] Tauri `src-tauri/icons/*` still the old (Vite) logo — regenerate with
  `npx tauri icon public/logo.png`.
- [ ] `LUXION_LOGGING__JSON` was renamed to `LUXION_LOGGING__JSON_LOGS` —
  update any external docs/scripts using the old name.
- [ ] Tauri tray / system tray integration not started (Phase 12 per PRD).
- [ ] Starlette TestClient deprecation warning (`httpx` → `httpx2`) — ignore for now.
- [ ] **Restart the backend** (`.\scripts\dev.ps1`, no `--reload`) so the new
  `llm.think=false` → `{"think": false}` payload reaches Ollama; then eyeball a
  chat turn — it should start streaming in ~2 s instead of hanging on
  "streaming".
- [x] **Commit Phase 5d — done (2026-10-10)**: committed as `85ad17a`
  (Phase 5d context injection + Settings Memory UI) and `b065e4d` (sidebar
  Memory nav).
- [x] **Commit Phase 6 — done (2026-10-11)**: committed as `9c240f9` and
  pushed. README later refreshed with logo, `docs/assets/` screenshots and a
  22 s demo webm (regenerate with a Playwright script driving the running
  app — two passes: stills at 2×, video at 1× with `scroll_into_view`, not
  `wait_for`, which matches offscreen DOM).
- [ ] **Root `.env` context-budget values look like typos** —
  `LUXION_CONTEXT__TOTAL_BUDGET_TOKENS=320000000` /
  `RESERVE_TOKENS=400000` (~10000× the intended 32000/4000). Tests are
  insulated via `conftest.py` pins, but a live backend reading this `.env`
  would allow unbounded prompt assembly. **Confirm with the user** whether
  to correct the `.env`.
- [ ] **Eyeball Settings → Browser card** — run `.\scripts\dev.ps1`, open
  Settings, confirm the card renders after Memory, toggles persist, and a
  chat turn can drive `browser_open`/`youtube_search` (Chromium is installed
  at `%LOCALAPPDATA%\ms-playwright`).
- [x] **Commit Phase 7 — done (2026-10-15)**: committed as `e528940` (10
  desktop tools + `input_control` capability + `/api/desktop` + Settings
  Desktop card + 26 tests); memory.md hash recorded via amend.
- [ ] **Eyeball Settings → Desktop card** (Phase 7) — run `.\scripts\dev.ps1`,
  open Settings, confirm the card renders after Browser, toggles persist, the
  status chips (platform / UIA / window count / `input_control`) are live, and
  a chat turn can drive `list_applications` / `type_text` (Notepad test:
  "type hello in notepad").
- [x] **Commit Phase 8 — done (2026-10-15)**: committed as `70f02ff` (11
  coding tools + `terminal` capability + `/api/code` + Settings Coding card +
  49 tests; milestone "fix this project" proven live).
- [ ] **Eyeball Settings → Coding card** (Phase 8) — run `.\scripts\dev.ps1`,
  open Settings, confirm the card renders after Desktop, git/gh chips are
  green, toggles persist, and the **Terminal consent** line reads "not
  allowed" until you grant **Terminal** in Permissions & capabilities. Then in
  chat: "analyze this project" → `analyze_project` reports python/node;
  "grep for get_settings" → hits; after granting Terminal: "run the backend
  tests" → `run_tests` streams pytest output.
- [ ] **Grant the `terminal` capability once** (Phase 8) — it ships **OFF**
  (running commands needs consent, PRD §39); the chat tools explain where to
  grant it, but nothing that executes works until you flip it in Settings →
  Permissions & capabilities.
- [x] **FINISH Phase 9 — `internet_speed` 403 — FIXED (2026-10-20)**: Cloudflare
  `/meta` answers **403 `{}`** unless the request carries an `Origin` *or*
  `Referer` of `https://speed.cloudflare.com` (a browser User-Agent alone is
  NOT enough; `/__down` works with any UA). `luxion/web/http.py` gained a
  per-request `headers=` param on `get_text/get_json/get_bytes/post_bytes`
  (merged over the shared User-Agent); `luxion/web/speed.py` now sends
  `SPEED_HEADERS = {"Origin": "https://speed.cloudflare.com", "Referer":
  "https://speed.cloudflare.com/"}` on all three legs, and `colo` — now a
  **dict** (`{"iata": "DEL", …}`) instead of a string — is normalised by
  `_colo_name()` (dict → `iata` or `city`; str → itself). **7/7 tools
  live-verified** (`Temp\opencode\verify_tools_live.py`: search, weather,
  news, movies, stock, clock, speed — speed reported 5.81 Mbps via DEL,
  ISP JKS BROADBAND). +2 tests in `test_web_sources.py` (colo shapes,
  headers sent).
- [x] **Commit Phase 9 — done (2026-10-20, committed `ca27319`)**: all of
  `luxion/web/`, `webintel.py`, `WebConfig`/`web.json`, `/api/web`, `WebCard`,
  `.env.example` `LUXION_WEB__*`, the 3 new test files + updated tool sets,
  speed fix, memory.md.
- [ ] **Eyeball Settings → Web card** (Phase 9) — run `.\scripts\dev.ps1`,
  open Settings, confirm the card renders after Coding (Globe icon, on +
  keyless chips), **Test sources** button reports `ok` for search / weather /
  news / movies / clock (finance is deliberately not probed), toggles + numbers
  persist through reload, Reset-to-.env restores defaults. Then in chat:
  "weather in tokyo" → `get_weather`; "top tech news" → `get_news`;
  "msft stock" → `stock_quote`; "what time in new york" → `world_clock`.
- [ ] **Eyeball the 3 new Integrations cards** (Phase 10) — run
  `.\scripts\dev.ps1`, open Integrations: **Email** (on/smtp/imap chips, Test
  servers reports per-leg text, drafts list + delete, password row says
  "not configured" until `.env` carries one), **WhatsApp** (Connect launches +
  renders the QR, "scan qr" chip while polling /status every 3 s, flips to
  "linked" after the phone scan, Close tears down), **Notifications** (Send
  test fires a real toast, capability + platform chips). Card order:
  Voice · Email · WhatsApp · Notifications · Browser · Desktop · Coding · Web.
- [ ] **Live-verify Phase 10 transports** — email probe against a real mailbox
  (Gmail needs an app password in `LUXION_EMAIL__SMTP_PASSWORD`), WhatsApp QR
  login once, `email_send` to self. The toast path already fired for real via
  `POST /api/notify/test` during development.
- [ ] **WhatsApp DOM drift is a standing maintenance risk** — selectors live in
  `luxion/whatsapp/web.py`; when WhatsApp Web redesigns, the `whatsapp_*`
  tools fail with a message that points at the file.
- [ ] `AI3DCore` chunk is 888 kB — acceptable for now (lazy-loaded), revisit
  before release.

---

## Phase Status Board

| Phase | Name | Status |
|-------|------|--------|
| 0 | Architecture | ✅ done (2026-09-30) |
| 1 | Luxion Core (chat, LLM abstraction, streaming) | ✅ done (2026-09-30) + visual overhaul + OpenRouter provider (2026-10-01) |
| 2 | Context Manager | ✅ done (2026-10-01) |
| 3 | Tool Framework | ✅ done (2026-10-01) |
| 3.5 | Capabilities & Consent | ✅ done (2026-10-02) — OS probe, app consents, calendar sources, executor hard gate, Settings card |
| 4 | Voice | ✅ done (2026-10-05) — manager, `/api/voice` routes, frontend (`voice.ts`, Composer PTT/live, ChatPage command→turn→speak, Settings → Voice), 239 tests, **live API smoke on :8763**; only the browser eyeball remains |
| 5 | Memory + RAG | ✅ **done (2026-10-10)** — **5a** storage/index (2026-10-05), **5b** extraction + `remember`/`recall`/`forget` + 82 tests (2026-10-08), **5c** repository index + `search_code` + `/api/repository` + 54 tests (2026-10-08), **5d** context injection + `/memory/config` + Settings → Memory card + 34 tests (2026-10-10, committed `85ad17a`) |
| 6 | Browser Agent | ✅ **done (2026-10-11, committed `9c240f9`)** — Playwright manager + 13 tools (`browser_*`, `youtube_*`, `wikipedia_*`), `browser.json` overlay, `/api/browser` routes, Settings → Browser card, 44 tests |
| 7 | Computer Automation | ✅ **done (2026-10-15, committed `e528940`)** — `luxion/desktop/` + 10 tools (`list_applications`, `focus_application`, `list_processes`, `inspect_window`, `click_element`, `press_keys`, `type_text`, `click_at`, `control_volume`, `control_brightness`), `input_control` capability, `desktop.json` overlay, `/api/desktop` routes, Settings → Desktop card, 26 tests; live-verified against real Notepad |
| 8 | Coding Agent | ✅ **done (2026-10-15, committed `70f02ff`)** — `luxion/coding/` (analyzer + grep + terminal + git/gh) + 11 tools (`analyze_project`, `grep_code`, `edit_file`, `run_command`, `run_tests`, `install_dependencies`, `git_status`, `git_diff`, `git_commit`, `git_clone`, `github_prs`), `terminal` capability (default OFF), `code.json` overlay, `/api/code` routes, Settings → Coding card, 49 tests; **milestone "fix this project" proven live** (red → edit → green → commit); zero new Python deps |
| 9 | Web Intelligence | ✅ **done (2026-10-20, committed `ca27319`)** — `luxion/web/` (DDG search, Open-Meteo weather, RSS/HN news, TVMaze movies, Yahoo-only finance, Cloudflare speed, zoneinfo world clock) + 7 tools (`web_search`, `get_weather`, `get_news`, `movie_lookup`, `stock_quote`, `internet_speed`, `world_clock`) → registry **54**, `WebConfig` + `web.json` overlay + `/api/web` (+ `POST /web/probe`) + Settings → Web card, PRD §37 provenance stamps + system-prompt sourcing rules, zero new deps, +61 tests; **7/7 tools live-verified over real HTTP** (speed 403 fixed via `SPEED_HEADERS` + dict-`colo` normalisation) |
| 10 | Communication | ✅ **done (2026-10-20, committed `87c65b1`)** — `luxion/email/` (smtplib send + imaplib read + MIME + drafts), `luxion/whatsapp/` (persistent Playwright Web session + DOM ops + `whatsapp://` protocol), `luxion/notify/` (PowerShell WinRT toast) + 8 tools (`email_draft`, `email_send`, `email_send_draft`, `email_read`, `whatsapp_send`, `whatsapp_read`, `whatsapp_open`, `notify`) → registry **62**, `EmailConfig`/`WhatsAppConfig`/`NotificationConfig` + `email.json`/`whatsapp.json`/`notify.json` overlays + `/api/email` (+ probe + drafts) + `/api/whatsapp` (+ session/QR/close) + `/api/notify` (+ test toast), Settings → Integrations gains **Email · WhatsApp · Notifications** cards, +91 tests, zero new deps; SMTP password env-only everywhere |
| 11 | Vision + Hardware | 🚧 **11a done (2026-10-21)** — vision core: `ImagePayload` on `ChatMessage` (+ Ollama `images[]` / OpenAI `image_url[]` payloads), `luxion/vision/` (`imaging.py` Pillow pipeline + `analyzer.py` provider call), `VisionConfig` + `vision.json` overlay + `/api/vision` (+ probe + analyze) + Settings → Vision card, 2 tools (`analyze_image`, `analyze_screenshot`) → registry **64**, zero new deps, +32 tests. **11b** = camera + OCR (opencv-contrib-python). **11c** = voice/face auth (`biometrics` capability) |
| 12 | 3D Orb | ⬜ (core already in place — Phase 12 = interaction/behaviour) |
| 13 | Advanced Agent | ⬜ |


## Latest Update

### Phase 11a — Vision core (✅ done 2026-10-21)

User-confirmed choices (asked before building): **vision transport = extend the
existing providers**, **camera = `opencv-contrib-python`**, **OCR = vision
model first + optional RapidOCR**, **auth = voice + face, zero extra deps
beyond OpenCV**. Phase 11 ships as **11a → 11b → 11c**.

**11a (this session) — the vision core. Zero new Python dependencies.**

- **`luxion/llm/types.py`** — new `ImagePayload` (`data` = raw base64, no
  `data:` prefix, + `data_url` property) and `ChatMessage.images`.
  Two provider-shaped helpers so the picture travels the *existing* contract:
  `ollama_message_payload()` → sibling `images[]` array of base64 strings;
  `openai_message_payload()` → the multimodal `content` array
  (`text` part + one `image_url` part per image). `as_provider_payload()` is
  untouched, so text-only messages are byte-identical to before.
- **`luxion/llm/providers/ollama.py` + `openai_compat.py`** — one-line switch
  to the new helpers. `OpenRouterProvider` inherits the OpenAI shape.
- **`backend/luxion/vision/`** — new package.
  `imaging.py`: decode (path / bytes / PIL image) → EXIF transpose → downscale
  to `max_dimension` → encode (PNG, JPEG fallback) → base64. Pure Pillow.
  `analyzer.py`: `resolve_vision_llm()` derives `(endpoint, model)` from
  `VisionConfig` (a vision model may differ from the chat model, and the
  endpoint may be a different provider entirely), `analyze_images()` calls
  `provider.complete()`, `probe_vision()` lists the models without spending a
  vision call.
- **`VisionConfig`** (in `settings.py`) + `luxion/config/vision_override.py`
  (`<data_dir>/vision.json`) + `apply_vision_overrides` / `save_vision_overrides`
  wired into `get_settings()`. Knobs: `enabled`, `model`, `provider`,
  `base_url`, `api_key_env`, `prompt`, `max_images`, `max_dimension`,
  `max_bytes`, `timeout_s`.
- **Tools** — `analyze_image` (low, read-only, workspace-scoped) and
  `analyze_screenshot` (low, read-only, **`requires="screen_capture"`**) in
  `tools/builtin/vision.py`. Registry **62 → 64**. `take_screenshot`'s
  capture helper was renamed `grab_screen()` so both tools share it.
- **`/api/vision`** — `GET` (bundle), `PUT /config` (partial overlay,
  `extra="forbid"`), `DELETE /config`, `POST /probe` (reachability, no vision
  call), `POST /analyze` (the live action: a file or the screen).
- **Frontend** — `lib/vision.ts`, `features/settings/VisionCard.tsx`
  (access / endpoint / limits / default prompt / "Test endpoint" / "Analyze
  screen"), `EyeIcon` + `CameraIcon` + `FingerprintIcon` in `icons.tsx`, and
  **Vision** appended to the Integrations page after Web.
- **Tests** — `tests/test_vision.py` (21) + `tests/test_vision_api.py` (11).
  Suite **713 → 745** (744 passing, 1 skipped).
- **Env** — `LUXION_VISION__*` documented in `.env.example`.

**Still to come in Phase 11**

- **11b — camera + OCR.** `luxion/vision/camera.py` (OpenCV webcam capture;
  the machine has an **HP True Vision FHD Camera**, so this is live-verifiable),
  `luxion/vision/ocr.py` (RapidOCR when installed, else the vision model
  transcribes), tools `capture_camera` + `ocr_image`, `camera` capability
  wiring. **Adds `opencv-contrib-python`** (one dep: camera + Haar + SFace)
  and optionally `rapidocr-onnxruntime`.
- **11c — authentication.** `luxion/vision/auth.py`: voiceprint = MFCC + DTW
  over **scipy** (already installed) and face = OpenCV **SFace** embeddings,
  both behind a new **`biometrics`** capability (default OFF). Tools
  `enroll_voice` / `verify_voice` / `enroll_face` / `verify_face`,
  `/api/auth` routes, `AuthCard`. **Zero extra deps beyond OpenCV.**
  `resemblyzer` was rejected — it pins `librosa<0.11` and would downgrade the
  librosa 1.0.0 that OmniVoice needs.

**Capability count stays 9 in 11a** (`analyze_screenshot` reuses the existing
`screen_capture`); 11c adds `biometrics` → 10.

### Phase 10 — Communication (✅ done 2026-10-20, committed `87c65b1`)

User-confirmed transport choices: **email = SMTP + IMAP (stdlib)**,
**WhatsApp = Playwright Web + `whatsapp://` protocol**, **notifications =
PowerShell toast (stdlib)**. Zero new Python deps; no API keys anywhere.

- **`backend/luxion/email/`** — `message.py` (MIME build: plain/html/both,
  header-injection guard, typed + size-capped attachments, RFC 2047-safe,
  signature; Bcc set as a header because smtplib strips it from the wire but
  needs it to address delivery), `smtp_send.py` (SSL/STARTTLS/none, app-password
  hint on auth failure, receipt with refused-recipient map), `imap_client.py`
  (recent-N fetch, previews, subject query, `policy=default` parsing),
  `drafts.py` (12-char id store in `<data_dir>/email_drafts/`).
  **Secrets**: `smtp_password` never reaches the overlay, the API bundle
  (model-serializer strips it), or the patch model (`extra="forbid"`);
  resolution order = named `smtp_password_env` var → `LUXION_EMAIL__SMTP_PASSWORD`.
- **`backend/luxion/whatsapp/`** — `manager.py` (own singleton with
  `launch_persistent_context` at `<data_dir>/whatsapp_profile` — login survives
  restarts; seams `set_whatsapp_launcher`/`reset_whatsapp_manager`),
  `web.py` (search-box → composer → Enter DOM ops, QR grab, message read;
  selector-drift error points at `luxion/whatsapp/web.py`),
  `protocol.py` (`whatsapp://send?phone=&text=` deep link; Windows
  `os.startfile`, fallback `https://wa.me/<phone>?text=…`).
- **`backend/luxion/notify/toast.py`** — builds the WinRT toast XML, encodes it
  UTF-16LE→base64 for `powershell.exe -EncodedCommand` (AUMID of the PS
  shortcut), module-level cooldown, `run_script` subprocess seam.
- **Tools** (registry **54 → 62**): `email_draft` medium, `email_send` /
  `email_send_draft` high, `email_read` medium read-only, `whatsapp_send` high,
  `whatsapp_read` medium read-only, `whatsapp_open` medium (protocol),
  `notify` low + `requires="notifications"` (first non-desktop capability gate;
  `test_only_gated_tools_declare_a_capability` updated).
- **Routes** `/api/email` (+`POST /probe`, drafts list/delete),
  `/api/whatsapp` (+`POST /session` → QR data-URL, `/status`, `/close`),
  `/api/notify` (+`POST /test` fires a real toast) — all registered in
  `app.py`; lifespan closes the WhatsApp manager. `.env.example` gained the
  three sections.
- **Frontend** — `lib/email.ts`/`whatsapp.ts`/`notify.ts` +
  `EmailCard`/`WhatsAppCard`/`NotifyCard` (SettingsCard pattern, ids
  email/whatsapp/notify) added to **Integrations** after Voice; WhatsApp card
  shows the login QR from `POST /api/whatsapp/session` and polls `/status`
  every 3 s until scanned; new `MailIcon`/`PhoneIcon`/`BellIcon`.
- **Tests +91** (620 → 711 passing): `test_email.py` (MIME/injection/Bcc/
  attachments, draft round-trip, fake-`smtplib`/`imaplib` flows incl. auth +
  refused-recipient mapping, tools, API incl. patch-mirror + secret-absence
  assertions), `test_whatsapp.py` (deep links, wa.me fallback, manager with
  fake launcher/pages, DOM ops, selector drift, tools, session API),
  `test_notify.py` (XML build/escape, encode round-trip, cooldown, capability
  gate, tool, API) — plus registry-set updates in `test_tools.py` /
  `test_tools_api.py`.
- Gates: backend 711 passed / 2 skipped, ruff check + format clean (202 files);
  frontend oxlint 0/0, `tsc -b` + `vite build` exit 0. Toast test endpoint was
  exercised for real (`shown: True` — a Windows toast actually fired).
- `SETUP.md` gained the three Integrations bullets, communication example
  prompts, the env-var + data-dir rows (incl. `whatsapp_profile/`), and the
  family list in the permissions section.

### UI restructure — collapsible settings cards + Tools/Integrations pages ✅ (2026-10-20)

User request: the Settings page had grown to 12 sections — make the long
cards collapsible ("dropdown") and move some content into main-menu pages.

- **`components/SettingsCard.tsx` (new)** — shared collapsible card: header
  is one toggle button (icon + title + badge + rotating `ChevronIcon`),
  `actions` sit **outside** the toggle so Refresh/Test presses never collapse
  the card; hint paragraph shows only while open; body stays **mounted** while
  collapsed (no refetch on expand) but is hidden with the
  `grid-rows-[0fr→1fr]` animation and marked `inert` (React 19 boolean) so
  nothing inside is focusable. Open state persisted per card in
  `localStorage["luxion.card.<id>"]`; **first card of a page defaults open,
  rest collapsed** (user's pick). `ChevronIcon` added to `icons.tsx`.
- **Nav split** (user's pick "Tools + Integrations"): `App.tsx` menu is now
  Dashboard · Chat · Memory · **Tools** · **Integrations** · Settings.
  - **`features/tools/ToolsPage.tsx` (new)** — Tools card (defaultOpen) +
    Permissions & capabilities card (incl. calendar sources), moved verbatim
    from Settings with all their state/handlers/`ToolRow`/`RiskBadge` helpers.
  - **`features/integrations/IntegrationsPage.tsx` (new)** — loads the
    capabilities report once (Voice's mic/speaker gates need it) and renders
    Voice (defaultOpen) · Browser · Desktop · Coding · Web cards.
  - **MemoryCard** was *already* rendered by `MemoryPage` — removing it from
    Settings was pure dedup.
  - **Settings** now = AI provider (defaultOpen) · Context & usage ·
    Appearance · Graphics, all as `SettingsCard`s (~1520 → ~870 lines).
- The 6 card components (Voice/Memory/Browser/Desktop/Code/Web) were
  **converted in place**: their `<section>` + header + hint `<p>` became
  `SettingsCard` props (`id` = voice/memory/browser/desktop/coding/web) —
  bodies untouched. Voice's hint now points to *Tools → Permissions &
  capabilities* for the hard gate.
- Gates: `oxlint` clean (51 files), `tsc -b` + `vite build` exit 0.
  **No browser eyeball yet** — ask the user to check the chevrons, the
  collapsed-page length, and that Refresh buttons don't toggle their card.
- **`SETUP.md` (new, 2026-10-20)** — full setup + user guide: prerequisites,
  install (.env / venv / playwright chromium / npm), Ollama vs OpenRouter,
  run options incl. Tauri, first-run checklist, page-by-page usage (post-restructure
  nav), permissions model (4 layers), example prompts, config reference +
  data-dir file table, verify commands (incl. `PYTHONIOENCODING`), troubleshooting
  table, reset/uninstall. Linked from README Quick start. Facts verified against
  `.env.example`, `pyproject.toml` (deps are all base-install; only `dev` extra),
  `settings.py` (`data_dir = <repo>/database`), `scripts/dev.ps1` (no extras needed),
  and no `docs_url` override (so `/docs` Swagger is live).

---

### Phase 9 — Web Intelligence (✅ done 2026-10-20, committed `ca27319`)

- Built `backend/luxion/web/` (search → DuckDuckGo HTML, weather → Open-Meteo,
  news → RSS/Atom + HN, movies → TVMaze, finance → **Yahoo-only**, speed →
  Cloudflare, clock → zoneinfo), 7 new tools → registry **54**,
  `WebConfig` + `web.json` overlay + `/api/web` (+ `POST /web/probe`),
  `lib/web.ts` + Settings → **Web card**, PRD §37 provenance stamps +
  system-prompt sourcing rules. **Zero new Python deps** (FOSS-first).
- User decisions: DDG HTML via httpx, TVMaze, and finance as "Stooq + Yahoo"
  — **shipped Yahoo-only** because Stooq 404s from this machine (every
  parameter variant); Yahoo's v8 chart has OHLCV + 52-week range + volume
  anyway, so nothing was lost.
- Gates green: backend **620 passed, 2 skipped**, `ruff check` + `format
  --check` clean (177 files); frontend `oxlint` clean, `tsc -b` + `vite build`
  exit 0. **7/7 tools live-verified over real HTTP.**
- The `internet_speed` 403 (fixed 2026-10-20): Cloudflare `/meta` needs an
  `Origin`/`Referer` of `speed.cloudflare.com` — `http.py` gained `headers=`,
  `speed.py` sends `SPEED_HEADERS` on all legs and `_colo_name()` normalises
  the now-dict `colo` field. (+2 tests.)

---

### [archived] Phase 4 — Voice, state as of 2026-10-02 — **FINISHED since**
(The "frontend/tests NOT started" lines below were true then and are long
done — see the **Phase 4 (Voice) - FINISHED** section below for the real
end state.)

**Decisions taken earlier (still holding)**: backend Python mic capture
(sounddevice/PortAudio), faster-whisper for STT, pyttsx3/SAPI5 for TTS,
energy VAD segmenter (no webrtcvad), wake word matched in Python against the
transcript. The mic capability gate from Phase 3.5 is reused as a hard block.

**Completed**

- Read PRD Phase 4 block + settings tree voice section (§26 Voice System,
  §33.1, §5.5 STT, §5.6 TTS, §32 Settings → Voice).
- Verified whisper `base.en` is downloaded
  (`~/.cache/huggingface/hub/models--Systran--faster-whisper-base.en`) and
  7 input devices are visible to PortAudio on this machine.
- `luxion/voice/audio.py` · `stt.py` · `tts.py` · `wake.py` — pre-existing
  from the interrupted session, now linted (SIM105/SIM117/F401 fixed).
- **`luxion/voice/manager.py` (new, ~800 lines)** — `VoiceManager`:
  - states `idle | listening | transcribing | speaking`;
  - one capture thread (PortAudio callback → bounded queue, drop-oldest) +
    one STT worker thread + optional playback thread;
  - `Segmenter` with adaptive noise floor + **rolling pre-roll** so the first
    syllable of a wake phrase is never clipped;
  - `start_listening()` / `stop_listening()` / `recognize()` (push-to-talk,
    no wake word, returns `""` when nothing crossed the gate) / `speak()`
    (block or fire-and-forget) / `stop_speaking()`;
  - wake gate in `_publish_command()`: `strip_wake` → arm for
    `wake_arm_s` → emit `command` (armed session skips the phrase);
  - **barge-in**: while TTS plays, sustained level ≥ `max(0.15, gate*4)` for
    `max(min_speech_s, 0.25)` s calls `stop_speaking()` → `spoken` event with
    `interrupted: true` (threshold deliberately high — speaker echo can
    otherwise self-interrupt);
  - capability gate `_require_capability()` before mic **and** speaker;
  - injectable seams for tests: `_mic_factory`, `_player`, `_tts_factory`,
    `_stt_obj`; events fan out to asyncio queues via
    `loop.call_soon_threadsafe` (keep-alive `ping` every 15 s).
- **`luxion/voice/__init__.py` (new)** — package exports.
- **`luxion/config/voice_override.py` (new)** — `<data_dir>/voice.json`
  partial overlay (same contract as `llm_provider.json`: utf-8-sig tolerant,
  write-then-rename, corrupt/unknown file ignored).
- **`config/settings.py`** — new `VoiceConfig` (20 knobs: master, STT, TTS,
  wake, VAD, barge-in, PTT) + `_valid_voice_values()` (drops unknown/invalid
  keys, never fatal) + `apply_voice_overrides()` / `save_voice_overrides()`
  wired into `get_settings()` (priority: defaults → `.env` → env → voice.json).
- **`api/routes/voice.py` (new)** — `GET /api/voice`,
  `POST /api/voice/listen {on}`, `POST /api/voice/recognize {timeout_s}`,
  `POST /api/voice/speak {text, block}`, `POST /api/voice/stop`,
  `GET /api/voice/events` (SSE), `PUT|DELETE /api/voice/config`.
  `VoiceError` → 400. `_rebuild()` restarts the manager after a config write.
  `VoiceConfigPatch` mirrors `VoiceConfig` field-for-field (needs a sync test).
- **`api/sse.py`** — `STREAM_HEADERS` moved here (was private to
  `routes/conversations.py`, which now imports it).
- **`api/app.py`** — registers the voice router; lifespan calls
  `close_voice_manager()` (never constructs one just to close it).
- **`pyproject.toml`** — hard deps added: `numpy`, `sounddevice`,
  `faster-whisper`, `pyttsx3` (all already present in `backend/.venv`).
- **`.env.example`** — full `LUXION_VOICE__*` block (20 vars, documented).

**Verified this session**: `ruff check .` clean, `ruff format .` clean,
`pytest -q` = 179 passing (no regressions), all 8 voice routes present in
the generated OpenAPI schema.

**Frontend NOT started**: `lib/voice.ts`, mic icon, Composer mic button,
ChatPage `command`-event → chat-turn → `speak(reply)` wiring, and the
Settings → Voice card are all still to do.

**Tests NOT written yet**: planned `tests/test_voice.py` (segmenter/pre-roll,
wake arm + command emission, PTT happy/no-speech, capability denials,
barge-in, config overlay) and `tests/test_voice_api.py` (route round trip +
`VoiceConfigPatch` ↔ `VoiceConfig` field sync). Both should inject the fake
mic/STT/TTS seams and monkeypatch
`luxion.api.routes.voice.get_voice_manager`.

## Phase 4 (Voice) - FINISHED, then extended with OmniVoice TTS

**State of the code** (supersedes the "Frontend NOT started" / "Tests NOT written"
notes above):

- Frontend done: `frontend/src/lib/voice.ts` (types + fetchers + useVoiceEvents
  SSE loop), mic/mic-off icons, Composer PTT + live-listen button, ChatPage
  `command` -> chat turn -> `speak(reply)` (queued while a turn is in flight,
  spoken only for voice-initiated turns), Settings -> Voice card (all PRD 32 rows,
  level meter, Save/Discard/Reset-to-.env).
- Backend tests: `tests/test_voice.py`, `tests/test_voice_api.py`,
  `tests/test_voice_tts.py` -> `pytest -q` = 239 passing, `ruff check` +
  `ruff format --check` clean, frontend `npm run lint` / `npx tsc -b` /
  `npm run build` clean.
- `GET /api/voice/config` returns `{config, defaults}`; `save_voice_overrides`
  MERGES into voice.json (never replaces - a PATCH sends only changed fields).
- `manager._tts_factory` is now called as `factory(provider, voice=cfg)`;
  test fakes accept `**_kwargs`.

### OmniVoice as an opt-in TTS provider (user request, Oct 2026)

Repo cloned at `./OmniVoice`, installed editable as `omnivoice 0.2.1` inside
`backend/.venv` (torch 2.14.1+cpu, transformers 5.18, soundfile, librosa).

- `luxion/voice/tts.py`: `OmniVoiceTts` (lazy `OmniVoice.from_pretrained(
  device_map="cpu")`, voice-design prompt, `num_step`, `speed`; PCM16 WAV via
  soundfile) + `get_tts(provider, *, voice=cfg)` + per-model cache with
  `reset_tts_cache()`. Windows SAPI stays the DEFAULT provider; omnivoice is
  one dropdown away in Settings.
- New `VoiceConfig` knobs (mirrored in `VoiceConfigPatch` and in
  `frontend/src/lib/voice.ts` + VoiceCard): `tts_model` ("k2-fsa/OmniVoice"),
  `tts_instruct` ("female, young adult, moderate pitch"),
  `tts_steps` (default 8, ge 4, le 64), `tts_language` ("").
- `tts_rate` maps to OmniVoice's own speed factor `1 + rate/100` clamped to
  0.5..2.0 (no post-resample, pitch stays natural); `tts_volume` = sample gain.
- STT stays faster-whisper: OmniVoice is TTS only (it uses Whisper internally
  just to transcribe a reference clip for cloning).
- OmniVoice instruct is a CONTROLLED vocabulary - "calm"/free text raises
  ValueError, surfaced as TtsError. Valid items: gender, age, pitch, style,
  accent (comma separated, English), dialects for Chinese.
- PRD 5.6 "possible providers" now lists OmniVoice. `.env.example` documents the
  four new `LUXION_VOICE__TTS_*` vars.

**Measured on this machine** (CPU only, 8 logical / torch sees 4 threads):

- model download first run: 4 min 45 s -> 3.0 GB in
  `~/.cache/huggingface/hub/models--k2-fsa--OmniVoice`
- warm process load: ~32 s (paid once per process, cached instance reused)
- synthesis of a 2.8 s sentence: 4 steps ~11 s, 8 steps ~23 s, 16 steps ~47 s
- `dtype=torch.bfloat16` is MUCH slower (125 s) - keep float32
- real output proven: `%LOCALAPPDATA%\Temp\opencode\omni_smoke.wav`
  (24 kHz PCM16, 2.80 s) - `play_wav` accepts any-rate 16-bit PCM
- root `.env` has no `LUXION_VOICE__*` entries, so DELETE /config == defaults

**OPEN ITEMS (deferred by the user, Oct 2026):**

1. ~~Two smoke uvicorn servers still listening: PID 17584 (:8124) and PID 18096
   (:8126)~~ — gone; verified 2026-10-05 (only listener left is the new smoke
   server on **:8763, PID 4876** — `Ctrl+C` in that window when you are done).
2. ~~`database/voice.json` still holds the smoke override~~ — cleared
   2026-10-05 via `DELETE /api/voice/config`; the file is gone and the effective
   config equals the defaults again.
3. Latency strategy NOT decided: no background warm-up yet (the first reply pays
   ~32 s load + synthesis), default stays 8 steps (~23 s/reply). Options on the
   table: 4 steps + warm at startup, keep 8 steps + warm, leave as-is, or add
   Piper (PRD 5.6) as the fast ~real-time local provider.
4. ~~`OmniVoice/` is now a **git submodule** (`url = https://github.com/k2-fsa/OmniVoice.git`,
   branch `main`) but `.gitmodules` is still **untracked** — commit it or drop
   the submodule.~~ — `.gitmodules` committed 2026-10-05.
5. `frontend/src/App.tsx` and `frontend/src/features/dashboard/DashboardPage.tsx`
   were committed in `2a900c0` but are still **unreviewed**.

---

## Phase 4 live smoke ✅ (2026-10-05, port 8763)

Started with `$env:LUXION_SERVER__PORT='8763'; .\.venv\Scripts\python.exe -m luxion`
(real root `.env`). Every call returned the expected result:

| Check | Result |
|-------|--------|
| `GET /api/health` | `status=ok`, `database=ok` |
| `GET /api/voice` | `state=idle`, 20 input devices, `microphone` **granted**, `speaker` **granted**, STT `whisper/base.en` (`loaded:false` until the first session) |
| `GET /api/voice/config` | `{config, defaults}` |
| `PUT /api/voice/config {"tts_steps":8}` | 200 → status; `database/voice.json` **merged** (`tts_steps` added, the rest kept) |
| `POST /api/voice/listen {"on":true}` | `state=listening`, `device` = index 1 `Microphone Array (AMD…)` |
| `GET /api/voice/events` (SSE) | 210 lines / 12 s → **105 `level` frames** (~11/s), framing correct |
| `POST /api/voice/recognize {"timeout_s":5}` | `{"text":""}` — silent room, nothing crossed the gate (correct) |
| `POST /api/voice/speak {block:false}` | `{"started":true,"interrupted":false}` → event `state:speaking` |
| `POST /api/voice/stop` | `{"stopped":true}` → `state:idle` + **`spoken` with `interrupted:true`** |
| `POST /api/voice/listen {"on":false}` | back to `idle` |
| `DELETE /api/voice/config` | `database/voice.json` **deleted**; effective == defaults (`wake_phrase=hey luxion`, `tts_model=k2-fsa/OmniVoice`) |

**Mic-denied path** — the OS consent value was flipped `Allow → Deny` on
`HKCU\…\CapabilityAccessManager\ConsentStore\microphone` **and** its
`NonPackaged` subkey, probed, then **restored to `Allow`** (both verified after):

- `GET /api/voice` → `microphone {allowed:false, state:"blocked_by_os",
  reason:"Microphone is blocked in Windows privacy settings"}`
- `POST /api/voice/listen {"on":true}` → **400** `{"detail":"Microphone is blocked in Windows privacy settings"}`
- `POST /api/voice/recognize` → **400**, same detail

**Gates re-run this session**: backend `pytest` **239 passed** (`addopts = "-q"`
in `pyproject.toml`, so `-q` on the CLI becomes `-qq` and hides the summary —
run plain `pytest` to see the count), `ruff check .` clean,
`ruff format --check .` clean (94 files); frontend `npm run lint` clean and
`npm run build` (`tsc -b && vite build`) OK — only the pre-existing 888 kB
`AI3DCore` chunk warning.

**Still open**: the browser eyeball (wake → chat turn → spoken reply, PTT fills
the composer, Stop interrupts, Settings → Voice card).

**PowerShell 5.1 gotcha**: `curl.exe -d '{"on":true}'` loses the inner quotes →
`json_invalid`. Use `Invoke-RestMethod … -Body '{"on":true}'`, or escape as
`'{\"on\":true}'`. A fresh window has no `$b`, so the SSE call needs the full
URL (`curl.exe -N http://127.0.0.1:8763/api/voice/events`).
---

## Phase 5a — Memory + RAG storage/index layer ✅ (2026-10-05)

Milestone **5a** (of the approved 5a → 5d plan) is done: chunks can be written
into SQLite and retrieved by hybrid (vector + keyword) search.

**Stack (as decided):** `sqlite-vec` 0.1.9 (`vec0` ANN, loaded as an extension —
`enable_load_extension` + `sqlite_vec.load(conn)`, *not* `loadable_extension()`),
FTS5 for keywords, `fastembed` 0.8.1 for embeddings, `HashEmbeddingProvider`
(deterministic sha1 bag-of-tokens) as the offline/test backend. **No PDF/DOCX
support** — only `.md .txt .rst .sql` + source code (`DEFAULT_INDEX_EXTENSIONS`).

**New files**

| File | What it does |
|------|--------------|
| `luxion/rag/__init__.py` | package docs + `init_rag(engine, dim_hint)` |
| `luxion/rag/vector_store.py` | vec0/FTS5 DDL, `write_chunks`, `delete_source`, `vector_search`, `keyword_search`, `hybrid_search` (RRF k=60), `sync_meta`, `rebuild_vector_index` |
| `luxion/rag/schema.sql` | `chunks_fts` FTS5 DDL (`unicode61 remove_diacritics 2`, `chunk_id UNINDEXED`) |
| `luxion/rag/models.py` | `Chunk` (text + float32 BLOB = source of truth) + `RagMeta` (id=1: model, dim, counts, pending_model) |
| `luxion/rag/embeddings.py` | provider protocol, `FastEmbedProvider` (lazy/thread-safe), `HashEmbeddingProvider`, cache/reset |
| `luxion/rag/chunking.py` | prose windows (paragraph/sentence + tail overlap) and line-bounded code chunks with `_is_boundary` |
| `luxion/config/rag_override.py` | `rag.json` 4-layer overlay (mirrors `voice.json`) |
| `tests/test_chunking.py`, `test_embeddings.py`, `test_vector_store.py` | 30 new tests |

**Wiring:** `database/session.py::get_engine()` registers the sqlite-vec
`connect` hook *before* any connection exists (a later hook misses pooled
connections); `init_db()` imports the rag models (so `create_all` sees them),
then `create_all`, then `init_rag()`; `dispose_engine()` calls
`reset_extension_state()`.

**Design points**

- `chunks.embedding` (L2-normalised float32 BLOB) is the source of truth;
  `chunks_vec` is a rebuildable accelerator and `chunks_fts` is derived too —
  losing either costs a rebuild, never data.
- euclidean k-NN on unit vectors ≡ cosine ranking; `min_score` filters on
  cosine, keyword-only hits are always kept (that is what makes identifiers
  retrievable from code).
- **numpy fallback**: when `vec0` is unavailable, `vector_search` scans the
  stored blobs (`SELECT vec_version()` probes availability, cached per engine).
- `rag_meta.dim` decides the vec0 width; `pending_model` is the
  "re-embed needed" signal for Settings → Memory. A configured model change
  never destroys the live index.
- Every list/`IN` filter went through ORM `Chunk.id.in_(...)` — SQLAlchemy's
  `text()` + `bindparam(expanding=True)` does **not** expand here
  (`row value misused`).

**Bugs found and fixed during the 5a smoke**

1. `chunking._LINE_BOUNDARY` had one `)` too many (`unbalanced parenthesis`).
2. `HashEmbeddingProvider` read `range(0, 32, 4)` over a 20-byte sha1 digest
   (`IndexError`) → `range(0, 18, 4)`.
3. `rebuild_vector_index` passed raw bytes to `sqlite_vec.serialize_float32`
   (which packs *floats*) → 4× oversized vectors; stored blobs are already in
   vec0 raw format.
4. `sync_meta` never wrote `model`/`dim` — now only records them once every
   chunk carries that model.

**Gates:** backend `pytest` **269 passed** (239 → 269), `ruff check .` clean,
`ruff format --check .` clean (103 files). `tests/conftest.py` sets
`LUXION_RAG__PROVIDER=hash` so the suite never downloads a model.

**Next:** 5b — memory extraction (summaries + `remember`/`recall`/`forget`),
then 5c — repository indexing/retriever over the working set, 5d — Settings →
Memory UI + context injection.

---

## Phase 5b — memory extraction + remember/recall/forget tools ✅ (2026-10-08)

Milestone **5b** is complete: code, wiring **and** the test files that were
deferred at the end of the last session.

**New files**

| File | What it does |
|------|--------------|
| `luxion/memory/models.py` | `Memory` table (kind/text/hash/source/importance/conversation_id/timestamps), `MEMORY_KINDS = ("fact","preference","task","project","episode")`, `chunk_source` → `memory:{id}` |
| `luxion/memory/store.py` | `remember()` (normalize → dedupe by sha256 hash → `memory_max` cap → indexed), `get_memory`, `list_memories`, `count_memories`, `forget`, `clear_memories`, `index_memory` (falls back to keyword-only when embedding fails) |
| `luxion/memory/recall.py` | `MemoryHit`, `recall()` over `hybrid_search(source_types={"memory"})`, `recent_memories()`, `format_memories()` |
| `luxion/memory/extraction.py` | LLM JSON extractor + heuristic patterns (`My name is…`, `I prefer…`, `don't forget…`), `_load_turns`/`_mark_extracted` idempotency via `conversation.meta["memory_extracted_through"]`, `extract_from_conversation`, `schedule_extraction` |
| `luxion/tools/builtin/memories.py` | `remember` (medium), `recall` (low, read-only), `forget` (medium) — PRD §33.14 commands |
| `luxion/api/routes/memory.py` | `GET/POST /api/memory`, `POST /api/memory/search`, `DELETE /api/memory/{id}`, `DELETE /api/memory` (clear all) → 400 on `ValueError` |

**Wiring:** `tools/builtin/__init__.py` registers the three tools (registry now
ships **12**); `services/chat.py` calls `schedule_extraction(conversation_id,
settings=cfg)` after the `ChatDone` event; `api/app.py` mounts the memory
router; `api/schemas.py` gained `MemoryCreate`/`MemoryOut`/`MemoryListOut`/
`MemorySearchRequest`/`MemorySearchOut`; `RAGConfig` gained
`memory_extraction: bool = True` and `memory_max: int = 500`;
`.env.example` documents `LUXION_RAG__MEMORY_EXTRACTION` / `MEMORY_MAX`.

**Design points**

- Memory chunks reuse the 5a pipeline: `write_chunks` now accepts
  `np.ndarray | None` vectors so an embedding failure still indexes the
  statement for keyword search.
- `hybrid_search` gained `source_types` (over-fetch `breadth = k*4`, then
  `return hits[:k]`) so `recall()` searches only `source_kind='memory'`
  without a second query path.
- Extraction is idempotent: each pass records how far into the conversation it
  read, so a conversation is never harvested twice.
- Store cap: reaching `memory_max` makes `remember()` raise `ValueError`
  ("memory full") rather than growing forever; extraction is skipped silently.

**Tests touched:** `test_tools.py` / `test_tools_api.py` expectations updated
from the 9 initial tools to the 12 bundled tools (memory tools added, plus
risk asserts: `recall=low`, `remember=forget=medium`).

**Housekeeping:** `.gitmodules` (OmniVoice submodule, gitlink already tracked)
committed in the 5b batch → resolves OPEN ITEM 4.

---

## Phase 5b tests ✅ (2026-10-08) — 82 new tests, 269 → 351

Five new files, all green:

| File | Tests | Covers |
|------|-------|--------|
| `tests/test_memory_store.py` | 16 | `normalize_text` (whitespace / trailing punctuation / `MAX_TEXT` word-boundary cap), `memory_hash` case-insensitivity, `remember` → row + FTS/vec chunk, dedupe, empty + unknown-kind `ValueError`s, importance clamp, **`memory_max` ceiling** (filled for real — the field is validated `ge=10`), `get/list/count`, `forget` (row **and** chunk gone, unknown id → `False`), `clear_memories`, **keyword-only indexing when the embedding model is down**, re-index idempotency |
| `tests/test_memory_recall.py` | 14 | exact-phrase hit, relevance ranking, `k`, blank query, unrelated query, **`kinds` filter** (needs both rows retrievable first), model-down → keyword path still answers, `min_score` gates only the *vector* side (exact identifiers survive `0.99`), `MemoryHit.as_dict`, `recent_memories` order/`kinds`, `format_memories` block + character budget + detached rows |
| `tests/test_memory_tools.py` | 18 | `remember` (store / dupe / blank / bad kind → `ToolError memory_rejected` / importance clamp / default kind), `recall` (hits + prompt preview, `k` clamped 1..20, "No memories match", blank query), `forget` (by id, by query, no args, unknown id, unmatched query), **router** surfaces `recall`/`remember` for a memory question under `max_exposed=3`, spec/risk/read-only model, **executor deny at autonomy 0 stores nothing** + confirm/allow levels at autonomy 2 |
| `tests/test_memory_extraction.py` | 18 | all 8 PRD §33.14 heuristics, user-turns-only, `MIN_TEXT`, `MAX_PER_PASS`, fenced/prose/junk JSON parsing (7 parametrised junk cases), unknown-kind + importance repair, whole-pass idempotency, marker written even when nothing is kept, `memory_extraction: False`, unknown conversation, **LLM candidates merged next to heuristics**, LLM-returns-`[]` fallback, `schedule_extraction` (no loop → `None`, in-loop → task, disabled → `None`) |
| `tests/test_memory_api.py` | 16 | `GET /api/memory` (empty, total, `?kind` filter, 400 unknown kind), `POST` (201, dedupe on the same id, `importance` `ge/le` → 422, blank → 400, bad kind → 400), `POST /search` (ranked hits + `preview`, `kinds` filter, 400/422), `DELETE /{id}` (204/404), `DELETE` (clear-all count) |

**Bugs / gotchas found while writing them**

1. `Settings(rag={"memory_max": 1})` → **ValidationError**, `memory_max` is
   `ge=10`; the ceiling test fills the store for real instead of mocking
   `count_memories`.
2. `from luxion.memory import recall` resolves to the **function**, not the
   module (the package re-exports it) — monkeypatching needs
   `importlib.import_module("luxion.memory.recall")`.
3. `POST /api/memory` clamps nothing itself: `MemoryCreate.importance` is
   `ge=0, le=1`, so out-of-range is a **422 from the schema**, not a store
   clamp (the clamp only matters for the tool/LLM path).
4. `init_db()` registered the RAG tables but **not** `memories` — it worked
   only because `api/app.py` imports the memory router before the lifespan runs.
   Added `from luxion.memory import models` next to the rag one in
   `database/session.py::init_db`, so a standalone `init_db()` creates the table.

**Gates:** backend `pytest` **351 passed**, `ruff check .` clean,
`ruff format --check .` clean (115 files); frontend `npm run lint` clean and
`npm run build` exit 0 (no frontend change this session).

**Still open:** 5c — repository indexing/retriever; then 5d — Settings →
Memory UI + context injection. Nothing committed yet.

---

## Phase 5c — repository indexing + retrieval ✅ (2026-10-08)

The RAG layer can now walk the approved workspaces, chunk + embed + prune, and
answer "where is X?" through both an HTTP API and a tool.

**New package `backend/luxion/repository/`**

| File | What it does |
|------|--------------|
| `scanner.py` | `REPO_SOURCE_TYPES = ("doc", "code")`, `normalize_extensions`, `is_excluded` (fnmatch per path part), `iter_files` (sorted `os.walk`, skips symlinks / oversized / missing roots, dedupes roots, stops at `max_files`) |
| `indexer.py` | `IndexReport` (slots + `as_dict()`), `read_text` (NUL-byte ⇒ binary), `draft_hashes`/`stored_hashes`, `index_file → (INDEXED\|UNCHANGED\|SKIPPED\|FAILED, written)`, `_embed_drafts` (batched, all-`None` keyword fallback on `EmbeddingError`), `count_repo_chunks/files`, `prune_missing`, `sync_workspaces`, `sync_blocking`, `schedule_index` |
| `retrieval.py` | `RepoHit` / `FileMatch`, `search_repository`, `files_relevant_to` (≤3 hits/file, ≤5 files), `format_repo_context` (prompt-ready `- path:1-3 [code]` block with a character budget), `relative_path` |
| `__init__.py` | package docstring + exports |

**Wired in:** `RAGConfig` gained `max_file_bytes` (512 KiB), `max_files` (5000),
`index_on_start` (False); `tools/builtin/repository.py` adds the `search_code`
builtin (risk `low`, read-only, category `repository`) — 13 builtins now;
`api/routes/repository.py` adds `GET /api/repository`,
`POST /api/repository/index`, `POST /api/repository/search`; schemas
`RepositoryHitOut/FileOut/StatusOut/IndexOut/SearchRequest/SearchOut`;
`app.py` includes the router and, only when `rag.index_on_start`, schedules one
sync from the lifespan.

### Phase 5c tests ✅ (2026-10-08) — 54 new tests, 351 → 405

| File | Tests | Covers |
|------|-------|--------|
| `tests/test_repository_index.py` | 24 + 1 skip | `iter_files` (extensions, excludes, missing root, symlink skip, `max_files`, `max_bytes`, root dedupe), `read_text` (binary / oversized), `index_file` outcomes + `source_type`/`language`/line numbers, incremental re-run, `draft_hashes` vs `stored_hashes`, `prune_missing`, blank file → `SKIPPED`, `schedule_index` (no loop → `None`, in loop → task, disabled → `None`) |
| `tests/test_repository_search.py` | 20 | exact-identifier retrieval, `k`, blank query, `min_score` floor, memory rows never surface, model-down → keyword path still answers, per-file grouping + hit cap, `format_repo_context` block / budget / matches-without-hits, `relative_path`, `search_code` (hits + line ranges, argument clamps, blank query, no-match copy, disabled RAG, spec/risk/read-only/required, router ranks it first, missing index, memory exclusion, disabled registry) |
| `tests/test_repository_api.py` | 10 | status (enabled/roots/counts/extensions/`index_on_start`), index → reindex is incremental, roots + `indexed_at`, blank file skipped not failed, prune on file removal, search hits/files/preview, grouped vs flat, cosine floor, 422 validation, `rag.enabled=False` ⇒ a no-op pass |

**Bugs / gotchas found while writing them**

1. **Blank chunks outranked real hits.** `chunk_code` emitted a
   `ChunkDraft(text="")` for the empty line a trailing newline creates; it
   embeds to a **zero vector**, and `sqlite_vec` reports `distance=1.0` for that
   (`_cosine` → 0.5), so the empty chunk scored **0.5 — above every real match,
   for every query**. Fixed twice: `chunk_code` now skips a wholly-blank block,
   and `write_chunks` refuses any blank-text draft. The old index test's
   `max(end_line) == len(content.split("\n"))` expectation was wrong too (the
   phantom line is now not indexed) — it asserts `len(content.splitlines())`.
2. **`rag.min_score` was documented but never consulted.** `search_repository`
   now takes `min_score=None` → `get_settings().rag.min_score` (0.2), and
   `RepositorySearchRequest.min_score` defaults to `None` for the same reason.
   Without a floor a nonsense query returns the whole index. Keyword hits
   still bypass the floor, which is what keeps exact identifiers findable.
   *(Note: `memory.recall` still defaults `min_score=0.0` and the memory search
   schema hard-defaults to `0.0`, so `LUXION_RAG__MIN_SCORE` only affects the
   repository path today — a candidate follow-up.)*
3. `_clear_repo` must delete through `vector_store.delete_source` — a bare
   `DELETE FROM chunks` leaves orphan `chunks_vec` rows, and SQLite reuses the
   `rowid`, so the next write trips a UNIQUE constraint.
4. `select_tools(query, registry, settings)` — the query is the **first**
   positional arg (easy to get backwards; the test now also asserts
   `search_code` ranks *first* for "where is the retry backoff handled?").
5. `relative_path` is OS-native (`src\app.py` on Windows) — compare with
   `Path(...)`, not a literal string.

**Gates:** backend `pytest` **405 passed, 1 skipped**, `ruff check .` clean,
`ruff format --check .` clean (124 files); frontend `npm run lint` clean and
`npm run build` exit 0 (no frontend change); `cargo check` exit 0 (no Rust
change).

**Still open:** 5d — Settings → Memory UI + context injection (inject
`format_repo_context` + `format_memories` into the system prompt). Committed
to `main` in the same session.

---

## Phase 5d — Settings → Memory UI + context injection ✅ (2026-10-10, uncommitted)

Milestone **5d** completes Phase 5: retrieved knowledge now reaches the system
prompt every chat turn, and Settings → Memory manages it. Code was written in
an earlier interrupted session (backend A/B already in the working tree,
verified); this session added the tests, the frontend and the docs.

**Delivered — backend A (context injection)**

- `luxion/context/knowledge.py` (new): `memory_context(session, settings, *,
  query="")` — `recall(k=settings.rag.top_k)` with `recent_memories(k=3)`
  fallback when there is no query / no hits; `repository_context(session,
  settings, *, query)` — `files_relevant_to` + `format_repo_context`, skipped
  when `query < MIN_REPO_QUERY_CHARS (3)`; `knowledge_context` splits
  `settings.context.knowledge_max_chars` (half each when both streams are on).
  Everything wrapped in `try/except → ""` — a bad retrieval never kills a turn.
- Settings: `ContextConfig.knowledge_max_chars = 2400` (env-only),
  `RAGConfig.inject_memory=True`, `RAGConfig.inject_repository=True` (persisted
  via `rag.json`).
- `llm/system_prompt.py`: `build_system_prompt(settings, tools=None, *,
  knowledge="")` — appends `Context retrieved for this turn:\n{block}` only
  when non-empty; a custom `LUXION_LLM__SYSTEM_PROMPT` still returns **verbatim**
  (knowledge is not appended to it — keep `tests/test_llm_providers.py`
  equality passing).
- `services/chat.py`: `_PreparedTurn.knowledge`, built in `_prepare_turn`
  (query = user text), passed to `build_system_prompt`.
- `services/usage.py`: query-less knowledge (memory recents only, no repo) in
  `_load_conversation` → the Settings → Context usage preview shows the same
  system prompt the next turn would send.

**Delivered — backend B (`/memory/config`)**

- `api/routes/memory.py`: `RAGConfigBundle` (`config`, `defaults`,
  `needs_reembed`, `chunks`, `vectors`, `embedding_models` from
  `EMBEDDING_MODELS`) + `RAGConfigPatch` (`extra="forbid"`, mirrors every
  `RAGConfig` field, all optional) as `GET/PUT/DELETE /memory/config` —
  declared **before** `@router.delete("/{memory_id}")` (a param route
  registered earlier would swallow `/memory/config` and 422 on the `config`
  string). GET runs `vector_store.sync_meta`; PUT/DELETE run
  `save_rag_overrides` + `reset_settings_cache` + `reset_embedding_provider()`
  (a new model only takes effect once the cached provider is dropped).

**Delivered — frontend**

- `frontend/src/lib/memory.ts` (new): types (`Memory`, `RagConfig`,
  `MemoryConfigBundle`, `EmbeddingModelSpec`, `RepositoryStatus`/`Hit`/`Search…`)
  + fetchers for memory CRUD/search, `/memory/config` bundle/patch/reset and
  `/repository` status/index/search. `MEMORY_KINDS` exported as the shared
  constant.
- `frontend/src/features/settings/MemoryCard.tsx` (new, VoiceCard pattern):
  stored memories list (kind chips, per-row forget) + kind filter + add form +
  search with scores + clear-all; context-injection toggles (inject memories /
  repository / extraction, memory ceiling); retrieval form (enabled, embedding
  model dropdown with dim/size/languages hint, top-k, min-score, chunk size /
  overlap) + **amber "re-embed needed" warning chip** (no button — the job
  does not exist, see follow-up); repository panel (roots/extensions, chunk +
  file counts, Index-now button with report line, retrieval preview search);
  Save / Discard / "Reset to .env" footer (edits persist to `rag.json`).
  Registered in `SettingsPage.tsx` right after `<VoiceCard caps={caps} />`.
- `.env.example`: `LUXION_CONTEXT__KNOWLEDGE_MAX_CHARS=2400`,
  `LUXION_RAG__INJECT_MEMORY=true`, `LUXION_RAG__INJECT_REPOSITORY=true`.
- **Follow-up fix (user report, same day)**: the sidebar **Memory** nav item
  was still `ready: false` in `App.tsx` (a Phase 5 placeholder) — it now
  routes to a new `features/memory/MemoryPage.tsx` that hosts the same
  `<MemoryCard />` (`ready: true`, page meta added, dead `phase`-badge JSX
  removed after it tripped a TS2322 on the narrowed union). The card also
  still lives in Settings between Voice and Appearance.

**Tests — 34 new, 406 → 440**

| File | Tests | Covers |
|------|-------|--------|
| `tests/test_context_knowledge.py` | 22 | memory block (query hits, recents fallback, `max_chars`, inject/rag gates, retrieval exception → `""`), repo block (short-query skip, gates), `knowledge_context` ordering + budget split, `build_system_prompt` append / blank-ignored / custom-prompt-verbatim, e2e `stream_reply` through a recording fake provider asserting the system message carries the knowledge block |
| `tests/test_memory_config_api.py` | 12 | bundle shape + defaults + model catalogue, `RAGConfigPatch` ↔ `RAGConfig` field-sync (mirror of the voice test), PUT merges into `rag.json` + survives reload, empty patch → 400, unknown key → 422, out-of-range value **silently dropped** (overlay contract), DELETE restores env-aware defaults, route ordering vs `/{memory_id}` (`/memory/config` never 422s), model swap keeps chunks and sets `needs_reembed` |

**Gotchas found while writing the tests**

1. **The suite's RAG provider is `hash`** (`conftest.py` sets
   `LUXION_RAG__PROVIDER=hash`), so `test_config_reset_restores_the_defaults`
   must compare against `Settings().rag.model_dump()` — a bare
   `RAGConfig().model_dump()` fails on `provider: hash != fastembed`.
2. **The e2e recorder needs a text delta.** A fake provider that emits only
   `StreamDone` makes `stream_reply` end with `empty_response` (nothing to
   persist) — the system prompt is never observable. Yield one `StreamDelta`
   before the done event.
3. **Invalid overlay values are silently dropped, not rejected** — that is the
   established `rag.json` contract (`_valid_rag_values`), so a PUT with
   `top_k: 0` returns 200 with the field unchanged; the "invalid value" test
   asserts the drop, not a 422. (`RAGConfigPatch` itself 422s only on *unknown
   keys* — `extra="forbid"`.)
4. **`importlib.import_module` for monkeypatching** — `from luxion.context
   import knowledge` binds the functions, so `monkeypatch.setattr(knowledge_mod,
   "recall", …)` needs the module object, same trap as 5b gotcha #2.
5. **No re-embed job exists** (`rag.reembed_batch` is only the indexing batch
   size); per user decision the UI shows `needs_reembed` as a warning chip
   only. Follow-up in Open Items.

**Gates:** backend `pytest` **440 passed, 1 skipped**, `ruff check .` clean,
`ruff format --check .` clean (127 files); frontend `npm run lint` clean and
`npm run build` (`tsc -b && vite build`) exit 0 — only the pre-existing 888 kB
AI3DCore chunk warning. **Not committed** (see Open Items); no browser
verification of the new card yet.

---

## Phase 6 — Browser Agent ✅ (2026-10-11, committed `9c240f9`)

**Delivered**

- **Dependency**: `playwright>=1.40` in `backend/pyproject.toml`; 1.63.0 +
  Chromium installed; verified real headless launch (`title-test: ok`).
- **`luxion/browser/manager.py`** — `BrowserManager` singleton (async-lock lazy
  launch, injectable `launcher` seam so tests never launch a real browser),
  `BrowserSession` (idempotent close), `playwright_launcher` (lazy import →
  clear install-message errors), `get/set/reset/close_browser_manager`.
- **`luxion/config/settings.py`** — `BrowserConfig` (enabled, headless,
  search_engine `duckduckgo|google|bing`, navigation_timeout_s=20,
  action_timeout_s=10, extract_max_chars=8000, user_agent, download_dir) +
  `browser.json` overlay (`config/browser_override.py`, same contract as
  `rag.json`: invalid/unknown values silently dropped, PUT 422 only on unknown
  keys via `extra="forbid"`).
- **13 new builtin tools** (registry now ships **26**):
  `browser_open/search/click/type/extract/download/upload/close` (§33.6),
  `youtube_search/open/control` (§33.7 — DOM eval + shared JS snippets),
  `wikipedia_search/article` (§33.8 — pure httpx against MediaWiki REST, works
  with browser disabled). Risk levels: browser open/click/type/download/upload +
  youtube_open/control = **medium**, everything else **low/read_only** — no new
  capability added (gated by the risk engine like `open_url`). `browser_*`/
  `youtube_*` raise `ToolError("browser automation is disabled …")` when
  `browser.enabled=false`; wikipedia is ungated.
- **`api/routes/browser.py`** — `GET /api/browser` (effective config + defaults
  + live session status), `PUT|DELETE /api/browser/config`; lifespan closes the
  manager in `finally`.
- **Frontend** — `lib/browser.ts` (types + fetchers) + `BrowserCard.tsx`
  (enable/headless toggles, engine select, timeouts, extract limit, session
  status chip with current URL, Save/Discard/Reset-to-.env) wired after
  `<MemoryCard />` in `SettingsPage.tsx`; new `GlobeIcon`.
- **Tests** — 44 new (`test_browser_tools.py`, `test_youtube_wikipedia.py`,
  `test_browser_api.py`) using `FakePage`/`FakeContext`/`FakeBrowser`/`FakePlaywright`
  + `set_browser_launcher` seam; tool-count/risk asserts updated; router-cap
  test now `min(len(registry), max_exposed)` (26 builtins > default 16 exposed).

**Gotchas**

1. **Root `.env` had context-budget typos** — `TOTAL_BUDGET_TOKENS=320000000`
   and `RESERVE_TOKENS=400000` (~10000× the 32000/4000 defaults) broke 3
   pre-existing tests on any tree. Fixed hermetically by pinning
   `LUXION_CONTEXT__TOTAL_BUDGET_TOKENS=32000` / `RESERVE_TOKENS=4000` in
   `tests/conftest.py`. The root `.env` still holds the odd values —
   **flagged for the user, left unchanged**.
2. **Sibling test imports use the bare module name** —
   `from test_browser_tools import FakePage, make_fake_session` (tests/ is not
   a package).
3. **`oxlint` `set-state-in-effect`** — a `void load(signal)` inside
   `useEffect` is flagged even when every `await` precedes the setState;
   MemoryCard is exempt only because its `load` never touches `setLoading` at
   the top. Fix: `.then/.catch/.finally` promise chain in the effect, keep the
   `useCallback` for the Refresh button.

**Gates:** backend `pytest` **484 passed, 1 skipped**, `ruff check .` clean,
`ruff format --check .` clean (135 files); frontend `npm run lint` clean and
`npm run build` exit 0. **Committed `9c240f9` + pushed.** The new card has
not been eyeballed in a running UI yet.

---

## Phase 7 — Computer Automation ✅ (2026-10-15, committed `e528940`)

PRD §33.5/§39 — 10 desktop tools behind a new `input_control` capability,
Windows-only, with the master switch `desktop.enabled`.

**Delivered — backend**

- **`luxion/desktop/` package**: `windows.py` (Win32 enumeration / focus /
  close via `ctypes`), `processes.py` (`top_processes` — psutil, cpu sampling
  pass, ranked by cpu/memory/name), `uia.py` (pywinauto UIA read-only tree,
  lazy import, `available()` probe), `input.py` (**injection layer — see
  gotcha 1**), `controls.py` (volume via `IAudioEndpointVolume`, brightness via
  `WmiMonitorBrightness`/`…Methods`), `errors.py`.
- **10 tools** in `tools/builtin/desktop.py` (registry ships **36**):
  `list_applications` (low), `focus_application` (medium), `list_processes`
  (low), `inspect_window` (low, UIA tree clipped to `max_elements`),
  `click_element` (**medium** — acts on a named control via the a11y tree),
  `press_keys` / `type_text` / `click_at` (**high** — raw injection),
  `control_volume` / `control_brightness` (medium). All raise a clear
  `ToolError` when `desktop.enabled=false`; out-of-range volume/brightness is
  refused, not silently clamped.
- **`input_control` capability** (`security/capabilities.py`, 8th entry, kind
  `app`) — declared by the three high-risk injection tools, checked in
  `ToolExecutor.prepare()` **before** the risk engine (same hard-block path as
  `screen_capture`); Settings can grant/deny/reset it.
- **`config/settings.py`** — `DesktopConfig` (enabled, ui_automation,
  coordinate_fallback, max_elements 5–500, max_processes 5–200, focus_delay_s
  0–3) + `desktop.json` overlay (`config/desktop_override.py`, same contract
  as `rag.json`/`browser.json`).
- **`api/routes/desktop.py`** — `GET /api/desktop` (effective config +
  defaults + live status: platform, UIA availability, window count,
  `input_control` state + reason), `PUT|DELETE /api/desktop/config`.

**Delivered — frontend**

- `lib/desktop.ts` (types + fetchers) + `DesktopCard.tsx` (enable /
  UIA / coordinate-fallback toggles, max elements/processes, focus delay,
  live status chips, Save/Discard/Reset-to-.env) wired after
  `<BrowserCard />` in `SettingsPage.tsx`; new `DesktopIcon`.

**Tests**: 26 new (`test_desktop_tools.py` 19 + `test_desktop_api.py` 7) —
hermetic (real Notepad/psutil walks only in the two integration-style tests),
registry/capability/tool-api tests updated for 36 tools + 8 capabilities.
**510 passed, 1 skipped.**

**Gotchas**

1. **`SendInput` is blocked at machine level on this box** (not a struct
   bug) — proven with `WH_KEYBOARD_LL`/`WH_MOUSE_LL` hooks: `SendInput` (vk,
   unicode, scancode, mouse) returns `1`, `last_error=0`, but **0 events reach
   the input queue**; `keybd_event`/`mouse_event` deliver fine, also from a
   real interactive console. `input.py` therefore probes **once per process**
   (`_probe_backend` → cached `_INJECTION_BACKEND`), prefers `sendinput` where
   it works, and falls back to the legacy APIs. Verified end-to-end against
   real Notepad (type → inspect → click File via UIA invoke → esc → `ctrl+s`
   → `ctrl+w`).
2. **Overlay contract = silently drop out-of-range values** (200 + effective
   default), never 400/422 — same as browser/voice/rag; a test asserting 400
   was wrong. Unknown *keys* still 422 via `extra="forbid"`.
3. `top_processes` drops rows with an empty `name` (a process exiting between
   the priming pass and the read leaves an unnamed row).
4. Notepad orphans from test probes can survive `taskkill` as a non-elevated
   child — close test windows via `ctrl+s`/`ctrl+w`, don't rely on `taskkill`.

**Gates:** backend `pytest` **510 passed, 1 skipped**, `ruff check .` clean,
`ruff format --check .` clean (149 files); frontend `tsc --noEmit` /
`oxlint src` / `npm run build` all clean. `/api/desktop` GET/PUT/DELETE
verified live via TestClient. The Desktop card has not been eyeballed in a
running UI yet.

---

## Phase 8 — Coding Agent ✅ (2026-10-15, committed `70f02ff`)

PRD §34/§35 + §32 (Tools → Terminal/Git) — repository analysis, grep, surgical
editing, a sandboxed terminal, git and GitHub. Milestone *"Fix this project."*
proven live (see below). **Zero new Python dependencies** (user's FOSS-first
rule): stdlib `subprocess`/`re`/`json`/`tomllib` + the user's own `git` and
optional `gh` CLIs.

**Delivered — backend**

- **`luxion/coding/` package**:
  - `analyzer.py` — `analyze_project()`: markers (pyproject/package.json/
    Cargo.toml/go.mod/… → 12 types), language mix (suffix counts, pruned
    walk), package manager (lockfile-aware: uv/poetry/pipenv/pip,
    pnpm/yarn/bun/npm…), detected test/build/lint/run commands, entry points,
    source dirs, and **nested-project discovery** for monorepo roots (Luxion's
    own root has no marker — `backend/pyproject.toml` + `frontend/package.json`
    one level down; reporting "not a repository" there was wrong).
  - `search.py` — grep: literal or regex, `include` glob, binary/NUL sniffing,
    1 MB file cap, 200-hit cap, skips `.git`/`node_modules`/build dirs.
  - `terminal.py` — the shell runner: workspace cwd, scrubbed env (no
    `*key*/*token*/*secret*/*password*` vars reach a child — PRD §57 rule 6),
    output clip, timeout that kills the **process tree** (`taskkill /T` on
    Windows), stdin DEVNULL (no accidental hangs), and a **catastrophic-command
    backstop** (`rm -rf /`, `mkfs`, `diskpart`, `reg delete`, fork bomb, …)
    refused outright — a backstop *under* the risk engine, not instead of it.
  - `gitops.py` — git status/diff/log/commit/clone via the git CLI (so the
    user's own identity/credential helper/GPG signing just works), `gh pr
    list` via the GitHub CLI with a clear "install gh" error when absent.
    Commits never push; clone refuses existing destinations and non-URLs.
- **11 tools** in `tools/builtin/code.py` (registry now **47**):
  `analyze_project`/`grep_code`/`git_status`/`git_diff`/`github_prs` =
  **low+read-only**; `edit_file` = **medium** (exact old→new, refuses 0 or >1
  matches unless `replace_all`, so a stale edit never silently no-ops);
  `run_command`/`run_tests`/`install_dependencies`/`git_commit`/`git_clone` =
  **high**. The 8 process-spawning tools declare `requires="terminal"`.
- **`terminal` capability** (`security/capabilities.py`, 9th entry, kind `app`,
  **default OFF**) — grant in Settings → Permissions; hard-blocks the whole
  execution family regardless of autonomy (§39).
- **`CodeConfig`** (enabled, command_timeout_s ≤900, max_output_chars) +
  `code.json` overlay (`config/code_override.py`) + `/api/code` routes
  (GET/PUT/DELETE; status reports git/gh availability, workspace, terminal
  capability — no `supported` flag, the tools are cross-platform by design).

**Delivered — frontend**

- `lib/code.ts` + `CodeCard.tsx` (enable toggle, timeout, output limit, git/gh
  chips, project-root line, terminal-consent readout pointing at the
  Permissions card, Save/Discard/Reset-to-.env) after `<DesktopCard />`;
  reused the existing `TerminalIcon` (Phase 3).

**Tests**: 49 new (`test_code_tools.py` 41 + `test_code_api.py` 8) — hermetic
(tmp_path fixtures, scratch git repos, PATH-pinned venv for `python -m
pytest`); registry/capability/tool-api sets updated (47 tools, 9
capabilities). **559 passed, 1 skipped.**

**Milestone proven live** (`%TEMP%` scratch project, tools driven exactly as
the agent loop would): analyze → grep (`def add` at app/math.py:1) → red
`run_tests` (`assert -1 == 5`) → `edit_file` fix (`a - b` → `a + b`) → green
`run_tests` (`1 passed`) → `git_status` → `git_commit`. Also live: `/api/code`
GET/PUT/merge/drop-invalid/422/DELETE via TestClient; child-env scrubbing
proven by canary (`LUXION_TEST_FAKE_API_KEY` never reaches `os.environ` of the
child; `LUXION_TEST_HARMLESS` does).

**Gotchas**

1. **`_SECRET_PATTERN` must not contain bare `auth`** — it scrubbed
   `GIT_AUTHOR_*`/`GIT_COMMITTER_*` and broke every commit whose identity
   comes from env. Now anchored: `(^|_)auth$|authorization|api_?key|…`.
2. `python -m pytest` uses whatever `python` is on PATH — outside an
   activated venv that is the system interpreter (often no pytest). The
   *detected* command stays honest; tests pin the venv onto PATH.
3. Duplicate `TerminalIcon` in `icons.tsx` — one already existed from Phase 3
   (tool execution chips); reuse it, don't re-add.

**Gates:** backend `pytest` **559 passed, 1 skipped**, `ruff check .` clean,
`ruff format --check .` clean (159 files); frontend `tsc -b` exit 0,
`oxlint` clean, `npm run build` OK (pre-existing chunk-size warning only).

---

## Phase 9 — Web Intelligence ✅ (2026-10-20, committed `ca27319`)

PRD §37 (Search/Weather/News/Movies/Finance/Time/Internet speed) + §38
(financial *analysis*, not predictions). **Zero new Python dependencies**
(FOSS-first): stdlib (`xml.etree`, `zoneinfo`, `csv`, `json`, `email.utils`)
+ the already-present `httpx`, every source **keyless**.

**Decisions taken with the user (2026-10-19):**

1. Search → **DuckDuckGo HTML endpoint via httpx** (not the `ddgs` package,
   not Playwright) — one GET, no key, works with browser automation off.
2. Movies → **TVMaze** (keyless, unrate-limited) — no registration needed.
3. Finance → chosen as "Stooq + Yahoo keyless"; **Shipped Yahoo-only.**
   ⚠️ **Stooq's `q/l` CSV answers HTTP 404 from this machine for *every*
   parameter variant** (Stooq-branded error page → geo/UA block, verified
   2026-10-19). Yahoo's v8 chart turned out to carry strictly more —
   OHLCV bars + `fiftyTwoWeekHigh/Low` + `regularMarketVolume/Price` +
   `fulldayChangePercent` — in **one** request instead of two, so dropping
   Stooq loses nothing. Deviation from the picked combo, flagged to user.

**Delivered — backend**

- **`luxion/web/` package** (all network I/O funnels through `http.py`, so
  tests patch exactly one seam):
  - `errors.py` — `WebError`, deliberately *not* `ToolError`: `luxion.web`
    sits below the tool layer and must import standalone; tools map it up.
  - `http.py` — `get_text/get_json/get_bytes/post_bytes`: shared User-Agent
    (or `WebConfig.user_agent`) + `WebConfig.timeout_s`, redirects on,
    failures normalised to `WebError("host answered HTTP nnn")`, plus a
    per-request **`headers=`** merge (added for Cloudflare, see Open Items).
  - `_html.py` — `strip_tags` replaces tags with **nothing** (inline `<b>`
    must not inject a space: `API</b>.` → `API.`, not `API .`), unescapes,
    collapses whitespace, and removes invisible code points (`_INVISIBLE` =
    U+200B–200F, U+2060–2064, U+FEFF, U+FE0E/FE0F — DDG titles carry a
    leading `\ufe0f` that breaks Windows consoles).
  - `provenance.py` — **PRD §37**: `stamp()` → `[source: …, retrieved:
    2026-10-19T…Z]` appended to every web tool output, `provenance_dict()`
    merged into `data`, and `GUIDANCE` (sourcing rules: live vs training
    knowledge vs memories, stamps can go stale).
  - `search.py` — `html.duckduckgo.com/html/` + `kl` region;
    `unwrap()` decodes `/l/?uddg=` redirects to the real URL.
  - `weather.py` — Open-Meteo geocoding (names the town it *found*) +
    forecast, full **WMO code table** (0–99), 16-point wind compass,
    `format_report` renders Now + 3 days in configured units.
  - `news.py` — RSS **and** Atom via stdlib `ElementTree` (per-topic curated
    feeds: BBC + Guardian world/business, BBC + Verge + Ars tech, BBC +
    Guardian science, HN Algolia for `hackernews`), feeds gathered
    concurrently with `return_exceptions=True` (one dead outlet never kills
    headlines), **`_dedupe()` tracks URL *and* title** — same-link repeats
    (BBC's own feed double-lists headlines) *and* same-headline
    different-link wire copies both drop.
  - `movies.py` — TVMaze search / singlesearch / `id:<n>` lookup with
    `embed=episodes` (latest episode, count, community rating labelled as
    crowd-sourced, not a critic score).
  - `finance.py` — **Yahoo v8 only**: `parse_chart()` (pure, rejects bad
    JSON + empty result = honest "unknown ticker"), `build_snapshot()` (meta
    beats the last bar), `compute_indicators()` (SMA20/50/200, 1d/5d/1mo/
    3mo/1y returns, 52w range position, annualised vol = stdev of log
    returns × √252), `_range_position()` prefers meta's 52w high/low over a
    short `period`, `_price()` display rounding (342.4599914 → `342.46`,
    sub-dollar keeps 4 dp), `format_quote()` states *"descriptive
    statistics… not a prediction"* + lists unavailable fields (market cap,
    statements) instead of guessing (§38).
  - `speed.py` — Cloudflare `/meta` (latency = RTT of that call) +
    `/__down?bytes=N` + optional `/__up` POST; `mbps()` = bytes×8/s; payload
    sizes from `WebConfig.speed_*`.
  - `clock.py` — `zoneinfo` (+ installed `tzdata`, Windows has no IANA db),
    `CITY_ALIASES` ("Tokyo" → `Asia/Tokyo`), day/night from local hour.
- **7 tools** in `tools/builtin/webintel.py` → registry now **54**: all
  `risk: low` + `read_only=True`, **`requires=None`** (public web data needs
  no capability — this family is policy-gated, not consent-gated), category
  `web_intel`. Master gate `settings.web.enabled` with a card-pointing error;
  `internet_speed` additionally honours `speed_enabled`. `_guard()` **must be
  async** — a sync wrapper returns the coroutine, so `WebError` would escape
  the `try` and never become `ToolError`.
- **`WebConfig`** (11 knobs: enabled, timeout_s, max_results, news_items,
  search_region, temperature_unit, wind_unit, speed_enabled,
  speed_download_bytes, speed_upload_bytes, user_agent) + `web.json` overlay
  (`config/web_override.py`) + `apply/save_web_overrides` chained in
  `get_settings` + `.env.example` `LUXION_WEB__*` block.
- **`/api/web`** — GET bundle (config/defaults/status/catalog),
  PUT (partial merge, unknown key → 422, out-of-range silently dropped like
  every other overlay), DELETE → `.env`; **`POST /web/probe`** hits 5 sources
  once for the card's *Test sources* button (finance deliberately excluded —
  2 heavy calls; probe is opt-in, never automatic).
- **system_prompt**: appends `provenance.GUIDANCE` **iff** any exposed spec
  has `category == "web_intel"` — PRD §37's current/historical/model/user
  distinction rides along exactly when live tools exist (tested both ways).

**Delivered — frontend**: `lib/web.ts` (bundle/config/probe fetchers) +
`WebCard.tsx` (on + keyless chips, three columns Access / Retrieval /
Units & speed, numeric + select controls, *Test sources* results list,
Save/Discard/Reset-to-.env, unsaved-changes line) rendered after
`<CodeCard />`; reuses the existing `GlobeIcon`.

**Tests**: +59 → **618 passed, 2 skipped** (`test_web_sources.py` pure
parsing/maths/`_dedupe`/provenance offline at the `web.http` seam,
`test_web_tools.py` all 7 tools incl. every disabled-gate refusal +
WebError→ToolError, `test_web_api.py` bundle/patch-merges/422/reset/atomic
write; `test_tools.py` + `test_tools_api.py` sets now carry the 7 names).

**Live-verified over real HTTP** — all 7 tools driven exactly as the agent
loop would (`Temp\opencode\verify_tools_live.py`): `web_search` (DDG,
invisible char gone), `get_weather` (Tokyo, forecast), `get_news` (tech
headlines, deduped), `movie_lookup` (The Wire, 8.9/10), `stock_quote` (MSFT
live + formatted), `world_clock` (3 zones), and — since the 2026-10-20 fix —
`internet_speed` (5.81 Mbps download, colo `DEL`, latency 592 ms, ISP
"JKS BROADBAND"); provenance stamp + `data.provenance` asserted on every one;
the disabled gate refused all 7.

**The `internet_speed` 403 (fixed 2026-10-20)**: Cloudflare `/meta` answers
403 `{}` unless the request carries an `Origin` *or* `Referer` belonging to
`speed.cloudflare.com` — a browser-like User-Agent alone is not enough, and
`/__down` doesn't care. Fix: `http.py`'s per-request `headers=` param (merged
over the shared UA) + `SPEED_HEADERS = {"Origin": "https://speed.cloudflare.com",
"Referer": "https://speed.cloudflare.com/"}` sent on all three legs
(`/meta`, `/__down`, `/__up`) in `speed.py`; plus `_colo_name()` because
`colo` is now a **dict** (`{"iata": "DEL", "lat": …, "city": …}`) — the old
`data.get("colo") or ""` would have printed the raw dict. +2 tests
(`_colo_name` shapes; `connection_info` sends `SPEED_HEADERS`).

**Gotchas**

1. **Stooq is unreachable from here** — every `q/l` variant 404s; don't
   re-add it without re-testing live first.
2. **Cloudflare `/meta` 403s without `Origin`/`Referer` of
   speed.cloudflare.com**; `/__down` doesn't care. Its `colo` field is a
   **dict** (`iata`/`lat`/`city`), not a string.
3. **Atom namespaced children** — `node.find("title")` misses
   `{ns}title`; match children by `tag.split("}")[-1]`.
4. **Test helper `_async(value)` must return the async *function***, not
   `_inner()` — patching a module attribute with a coroutine makes every
   call raise `TypeError: 'coroutine' object is not callable`.
5. DDG result titles contain `\ufe0f` — strip invisible code points, not
   just whitespace, or Windows cp1252 consoles crash on print.
6. **Live-verify scripts need `PYTHONIOENCODING=utf-8`** on Windows — the
   tool output contains `→`/`—`/`°` that cp1252 cannot encode, and the
   *print* crashes even when the tool itself succeeded.

**Gates (2026-10-20):** backend `pytest` **620 passed, 2 skipped**,
`ruff check .` clean, `ruff format --check .` clean (**177 files**);
frontend `oxlint` clean, `tsc -b` exit 0, `vite build` exit 0 (pre-existing
chunk-size warning only); **7/7 tools live-verified**. **Committed as
`ca27319`; Web card not yet eyeballed in a running UI.**

---

## Session side-task — model switch + the qwen "not replying" bug (2026-10-08)

**Switch.** `PUT /api/llm/provider` with `{"provider":"ollama","model":"qwen3.5:2b"}`
persisted `database/llm_provider.json` →
`{"active":"ollama","models":{"openrouter":"deepseek/deepseek-chat","ollama":"qwen3.5:2b"}}`.
`.env` stays at `LUXION_LLM__MODEL=` (auto-detect). Ollama now only has
`qwen3.5:2b`, `qwen3.5:0.8b`, `qwen3.5:4b` — `nemomix-local:latest` was
**deleted from Ollama** (the running backend's `_models_cache` still listed it
until the switch cleared it). Live turn verified `"model":"qwen3.5:2b"`.

**Bug: the chat stopped replying.** qwen3.5 emits `message.thinking` and
produces **no `content` until it is finished**; `OllamaProvider._read_ndjson`
only yields deltas for non-empty `content` → **zero deltas** → UI stuck on
"streaming" forever. Measured: default config = 60 s+ with no content at all;
`think: false` = first content at **2 s**, 18.9 s total, 333 chars.

**Fix (code written, gates green — backend NOT restarted yet):**

- `config/settings.py` — new `LLMConfig.think: bool = False` (Ollama-only knob;
  comment explains reasoning models stream nothing while thinking).
- `llm/providers/ollama.py` — payload now sends `"think": bool(self.config.think)`.
- `.env.example` — `LUXION_LLM__THINK=false` + comment.
- `tests/test_llm_providers.py` — `_ollama_ok` asserts `payload["think"] is False`,
  new `_ollama_done_line()` helper, new `test_ollama_forwards_the_think_switch`.

> ⚠️ **Backend started by `scripts\dev.ps1` has no `--reload`** — kill the
> `python -m luxion` process and start it again (or re-run `.\scripts\dev.ps1`)
> before the `think` fix takes effect in the app. Chat endpoint is
> `POST /api/conversations/{id}/messages` (SSE), not `/api/chat/stream`.

**Gates:** `pytest` **406 passed, 1 skipped**, `ruff check .` clean,
`ruff format --check .` clean (124 files).

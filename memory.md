# Luxion — Project Memory

> Living document. **Update after every phase.** Read this first when resuming work.
> Companion to `prd.md` (source of truth for requirements) and
> `design-system/luxion/MASTER.md` (source of truth for UI design).

---

## Current Status

| Field | Value |
|-------|-------|
| **Current phase** | Phase 4 — Voice ✅ code + tests + **live API smoke** done (2026-10-05); only the browser eyeball remains |
| **Next phase** | Phase 5 — Memory + RAG (after the Phase 4 eyeball) |
| **Last updated** | 2026-10-05 |
| **Backend tests** | 239 passing, `ruff check` + `ruff format --check` clean |
| **Frontend build** | `tsc -b && vite build` OK, `oxlint` clean |
| **Tauri shell** | `cargo check` OK (icons still the old Vite logo) |
| **Git** | 5 commits; Phase 4 committed (`b3a798d` voice backend, `2a900c0` OmniVoice + voice UI); only `.gitmodules` untracked |
| **Default adapter** | **Ollama** (was OpenRouter via `.env`) — switchable by tapping a card in Settings |
| **Permission layers** | 4: OS privacy gates (read-only probe) → app consents → account sources → tool risk engine (Phase 3). Capability check runs **before** the risk engine. Voice re-uses the same gate (`microphone`, `speaker`). |

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
- [ ] Git: repo now has **5 commits** (… `b3a798d` Phase 4 voice backend,
  `2a900c0` OmniVoice + voice UI + tests); only `.gitmodules` is untracked.
  Nothing modified in the working tree — ask before committing the submodule.
- [ ] **No browser verification yet** — the backend is now proven **live over
  HTTP** (Phase 4 smoke on :8763, see *Phase 4 live smoke*), but no browser has
  rendered the app: ask the user to eyeball HUD labels clear of content, galaxy
  in the blank areas, logo readable, **(Phase 3)** chat tool chips + Allow/Deny
  card + Settings → Tools, **(Phase 3.5)** Permissions & capabilities card,
  **(Settings)** adapter cards, **(Phase 4)** Composer mic/PTT + Settings →
  Voice. `vite preview`/headless smoke still aborts (SIGABRT) in this
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
| 5 | Memory + RAG | ⬜ |
| 6 | Browser Agent | ⬜ |
| 7 | Computer Automation | ⬜ |
| 8 | Coding Agent | ⬜ |
| 9 | Web Intelligence | ⬜ |
| 10 | Communication | ⬜ |
| 11 | Vision + Hardware | ⬜ |
| 12 | 3D Orb | ⬜ (core already in place — Phase 12 = interaction/behaviour) |
| 13 | Advanced Agent | ⬜ |


## Latest Update

### Phase 4 — Voice (backend done 2026-10-02)

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

## Phase 5b — memory extraction + remember/recall/forget tools (2026-10-05, code done, tests pending)

Milestone **5b** is implemented end to end; the suite is green but the
memory-specific test files are **not written yet** (that is the first thing to
do next session).

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

**Gates:** backend `pytest` **269 passed**, `ruff check .` clean,
`ruff format --check .` clean (110 files).

**Still open:** `tests/test_memory_store.py` / `test_memory_recall.py` /
`test_memory_tools.py` / `test_memory_extraction.py`; then 5c — repository
indexing/retriever; then 5d — Settings → Memory UI + context injection.

**Housekeeping:** `.gitmodules` (OmniVoice submodule, gitlink already tracked)
committed in this batch → resolves OPEN ITEM 4.

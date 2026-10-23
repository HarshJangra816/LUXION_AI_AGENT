# Contributing to Luxion

Thanks for taking the time to contribute. Luxion is a **local-first personal AI
agent for Windows** — you describe what you want, it figures out how to do it.

This guide covers how to set the project up, the conventions the codebase
follows, how to add a tool (the most common contribution), and what we expect
from a pull request.

**Current state:** Phases 0–11 shipped — **70 built-in tools**, **836 tests**,
memory + RAG, browser/desktop/coding/web agents, email + WhatsApp + toast
notifications, and vision (image analysis, camera, OCR, voice + face auth).

- Product requirements (source of truth): [`prd.md`](prd.md)
- Install & usage guide: [`SETUP.md`](SETUP.md)
- Project log: [`memory.md`](memory.md)
- UI rules: [`design-system/luxion/MASTER.md`](design-system/luxion/MASTER.md)

---

## Table of contents

- [Ways to contribute](#ways-to-contribute)
- [Prerequisites](#prerequisites)
- [Development setup](#development-setup)
- [Repository layout](#repository-layout)
- [Code conventions](#code-conventions)
- [Adding a new tool](#adding-a-new-tool)
- [The permission model](#the-permission-model)
- [Tests and quality gates](#tests-and-quality-gates)
- [Commits, branches and pull requests](#commits-branches-and-pull-requests)
- [Documentation rules](#documentation-rules)
- [Security and secrets](#security-and-secrets)
- [Code of conduct](#code-of-conduct)
- [License](#license)

---

## Ways to contribute

Not every contribution needs to be code.

| Contribution | Where it goes | Good first task? |
|---|---|---|
| Fix a bug | the file named in the issue | ✅ |
| Add a tool | `backend/luxion/tools/builtin/<name>.py` | ✅ |
| Add a web/data source | `backend/luxion/web/` | ✅ |
| Add tests | `backend/tests/` | ✅ |
| Improve the setup guide | [`SETUP.md`](SETUP.md) | ✅ |
| Report a bug | GitHub Issues | ✅ |
| Propose a feature | GitHub Issues (describe the problem first) | |
| UI / design work | `frontend/src/` + `design-system/luxion/MASTER.md` | |
| Review a PR | any open PR | |

**Before you write code:** open an issue describing the *problem*, not just the
solution. Several shipped features started as "here is what broke" rather than
"here is a patch". Use the templates in
[`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE) — bug report and feature
request.

---

## Prerequisites

| Tool | Version | Needed for |
|---|---|---|
| Python | ≥ 3.11 | backend |
| Node.js | ≥ 20 | frontend |
| Rust | stable | Tauri desktop shell (only for `npx tauri dev`) |
| Ollama | any recent | running a local model (the default provider) |
| Git | any | everything |

Optional, feature-gated:

- **Playwright Chromium** — browser agent tools (`browser_*`, `youtube_*`):
  `python -m playwright install chromium`
- **Ollama models** — `ollama pull qwen3.5:2b` (chat) and `ollama pull
  qwen2.5vl:3b` (vision, Phase 11a)
- **A cloud provider key** — only if you want to use OpenRouter or another
  OpenAI-compatible endpoint instead of Ollama.

Luxion targets **Windows** primarily. Desktop automation (UI Automation, toasts,
volume/brightness) uses Windows-only APIs and will not work on Linux/macOS.
The backend, frontend and most tools are cross-platform.

---

## Development setup

### 1. Fork and clone

```bash
git clone https://github.com/<your-username>/LUXION_AI_AGENT.git
cd LUXION_AI_AGENT
git remote add upstream https://github.com/HarshJangra816/LUXION_AI_AGENT.git
```

### 2. Configure

```powershell
copy .env.example .env
```

`.env.example` documents every `LUXION_*` variable. The defaults work
out of the box with Ollama on `http://127.0.0.1:11434`.

### 3. Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\pip.exe install -e ".[dev]"
.\.venv\Scripts\python.exe -m luxion
```

The API comes up on <http://127.0.0.1:8756> (interactive docs at
<http://127.0.0.1:8756/docs>).

### 4. Frontend

```powershell
cd frontend
npm install
npm run dev
```

Vite serves <http://localhost:5173> and proxies `/api` to the backend.

### 5. Both at once

```powershell
.\scripts\dev.ps1
```

### 6. Desktop shell

```powershell
cd frontend
npx tauri dev
```

### 7. Playwright (needed for the browser agent)

```powershell
cd backend
.\.venv\Scripts\python.exe -m playwright install chromium
```

Without it the browser tools raise a clear error explaining what is missing —
that is expected, not a bug.

> **Note on `OmniVoice/`** — this directory is a git submodule pointing at
> [`k2-fsa/OmniVoice`](https://github.com/k2-fsa/OmniVoice). It is a separate
> upstream project with its own licence and contributing rules. **Do not open
> PRs against it here** — send those upstream.

---

## Repository layout

```
Luxion/
├── backend/
│   ├── luxion/
│   │   ├── api/            # FastAPI app factory, routes/, schemas, SSE
│   │   ├── config/         # settings + persisted overlay files (json)
│   │   ├── database/       # SQLAlchemy models, session
│   │   ├── llm/            # provider adapters (ollama, openrouter, openai_compat)
│   │   ├── context/        # token budget, trimming, summarisation
│   │   ├── memory/         # durable facts, extraction, recall
│   │   ├── rag/            # chunking, embeddings, sqlite-vec store
│   │   ├── repository/     # workspace scan, index, code retrieval
│   │   ├── security/       # capabilities, consents, permission engine
│   │   ├── tools/          # tool framework + 64 builtins
│   │   ├── browser/        # Playwright session manager
│   │   ├── desktop/        # Windows UI Automation, input control
│   │   ├── coding/         # analyzer, grep, terminal, git/gh
│   │   ├── email/          # SMTP send, IMAP read, MIME, drafts
│   │   ├── whatsapp/       # WhatsApp Web session + DOM ops
│   │   ├── notify/         # Windows toast notifications
│   │   ├── vision/         # image pipeline + vision model calls
│   │   ├── voice/          # mic, faster-whisper STT, TTS, wake word
│   │   ├── web/            # search, weather, news, movies, finance, speed
│   │   ├── calendar/       # .ics sources and events
│   │   └── services/       # chat orchestration, conversations, usage
│   └── tests/              # pytest suite (836 tests)
├── frontend/
│   ├── src/
│   │   ├── components/     # shared UI + three/ (the 3D core)
│   │   ├── features/       # chat, dashboard, memory, tools, integrations, settings
│   │   ├── lib/            # api client, types, state providers
│   │   └── index.css       # Tailwind v4 @theme tokens
│   └── src-tauri/          # Tauri 2 shell (Rust)
├── design-system/luxion/   # persisted design system
├── docs/assets/            # screenshots, demo clip
└── scripts/dev.ps1
```

### Backend packages

Every functional area is its own package under `backend/luxion/`, with a small
public surface and no cross-package reaching. Imports flow one way:

```
api / services  →  tools, context, memory, rag, llm, security
```

`luxion/services` may import from `luxion/tools`; the reverse never happens.
Keep it that way — the executor deliberately never imports a concrete tool, so
plugins and builtins stay interchangeable.

---

## Code conventions

### Python (backend)

- **Python ≥ 3.11.** `from __future__ import annotations` at the top of every
  module.
- **Ruff** does linting and formatting. Config lives in `backend/pyproject.toml`:
  - line length **100**
  - rules: `E, F, I, UP, B, SIM, C4` (pycodestyle, pyflakes, isort, pyupgrade,
    bugbear, simplify, comprehensions)
  - `ruff format` is the formatter; do not hand-format around it
- **Type hints on public functions.** Use `from typing import Any` sparingly;
  prefer concrete types.
- **Docstrings** on modules, classes and non-obvious functions. Explain *why*,
  not *what* — the code already says what.
- **Sync SQLAlchemy** is deliberate (see `backend/luxion/database/session.py`
  for the rationale). Do not introduce `async` database calls.
- **Config is never hardcoded.** Every knob is a `LUXION_<SECTION>__<KEY>` env
  var. Sections are nested with a double underscore — `LUXION_TOOLS__ENABLED`,
  `LUXION_LLM__MODEL`. Add the variable to `.env.example` with a comment.
- **FOSS-first (important).** The project deliberately prefers the standard
  library and free/open-source CLIs over new dependencies — Phases 8, 9 and 10
  each shipped **zero** new Python packages. If your change needs a new
  dependency, justify it in the PR description: what the stdlib cannot do, and
  why the licence is acceptable.

### TypeScript / React (frontend)

- **TypeScript strict.** `noUnusedLocals`, `noUnusedParameters` and
  `erasableSyntaxOnly` are on — unused imports are a build error.
- **Never `any`.** Define the response type in `src/lib/<area>.ts` next to the
  fetch function.
- **Tailwind v4 tokens must live in `@theme` in `src/index.css`** — never in a
  plain `:root` block. Tailwind 4 only generates utilities from `@theme`
  declarations; a token in `:root` silently produces no class and renders
  nothing. New tokens go in `src/index.css` (mirroring
  `design-system/luxion/MASTER.md`), never as inline hex.
- **`--color-accent` / `--color-tint` are re-pointed at runtime** by
  `src/lib/appearance.tsx`. Don't hardcode them.
- **oxlint** is the linter (`npm run lint`).
- **Accessibility is not optional:** `cursor-pointer` on clickables, 150–300 ms
  transitions, visible focus rings, `prefers-reduced-motion` respected,
  **no emoji as icons** (use the SVG components in `src/components/icons.tsx`),
  and text contrast ≥ 4.5:1.
- **The 3D core is frozen.** Do not modify `CoreCore`, `CoreShell`,
  `CoreWireframe`, `CoreRings`, `CoreParticles` or `CoreField` without asking
  first — the visuals are approved as-is. Per-frame values belong in the
  mutable `coreDrive` state, not in React state.
- three.js stays **code-split** behind
  `lazy(() => import('./components/three/AI3DCore'))`.

### Formatting (all files)

`.editorconfig` is the source of truth: UTF-8, **LF** line endings, final
newline, trim trailing whitespace, 4-space indent for Python, 2-space for
JS/TS/JSON/CSS/YAML.

---

## Adding a new tool

This is the single most useful contribution. The pattern is identical for all
64 built-ins.

**1. Create `backend/luxion/tools/builtin/<name>.py`.**

```python
"""One-line summary of what this tool does and its risk level."""

from __future__ import annotations

from luxion.tools.base import Tool, ToolContext, ToolError, ToolResult, ToolSpec


class GetThing(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="get_thing",
            description="What it does. Written for the model — be explicit.",
            risk="low",              # low | medium | high | critical
            category="general",
            tags=["thing", "fetch"],  # keywords for the tool router
            read_only=True,           # side-effect free
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to look up."},
                },
                "required": ["query"],
            },
            requires=None,           # capability id, e.g. "screen_capture"
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        query = args.get("query")
        if not query:
            raise ToolError("query is required")
        return ToolResult(
            output="Human-readable result the model will read.",
            data={"query": query},   # structured payload for the UI
        )


BUILTIN_TOOLS: list[Tool] = [GetThing()]
```

**2. Register it** in `backend/luxion/tools/builtin/__init__.py` — import the
module and spread its `BUILTIN_TOOLS` into the list. The registry rebuilds on
the next server start.

**3. Pick the right `risk`.**

| Risk | Meaning | Example |
|---|---|---|
| `low` | read-only, no side effects | `get_time`, `web_search` |
| `medium` | writes, or reads something sensitive | `write_file`, `email_send` |
| `high` | launches/kills processes, moves the mouse, sends messages | `open_application`, `whatsapp_send` |
| `critical` | irreversible or destructive | `close_application`, `kill` |

The risk feeds the autonomy matrix: level 2 may only run `read_only` tools
unattended. Set `read_only=True` only if the tool truly has no side effects.

**4. Declare a capability if it touches the machine.** Anything that uses the
screen, microphone, keyboard, terminal or notifications sets
`requires="<capability_id>"`. Existing capability ids: `microphone`, `camera`,
`location`, `speaker`, `screen_capture`, `notifications`, `input_control`,
`terminal`, `calendar`. A denied capability is a **hard block** — no autonomy
level overrides it.

**5. Add tests** in `backend/tests/test_<name>_tools.py`. Cover the happy path,
the argument-validation path, and the permission/capability behaviour. The
existing `test_tools.py`, `test_capabilities.py` and `test_tool_agent.py` are
good templates.

**6. Expose it in the UI** (if it has a settings surface): add a route in
`backend/luxion/api/routes/<area>.py`, register it in
`backend/luxion/api/app.py`, and add a card under
`frontend/src/features/settings/` or `frontend/src/features/integrations/`.

**7. Update the counters** — the tool count in `README.md` and `memory.md`.

### Tool plugins (no fork needed)

You can also ship tools **outside** the repo. Put a `*.py` file in a directory
listed in `LUXION_TOOLS__PLUGIN_DIRS`; it may expose either `TOOLS = [...]` or
a `register(registry)` function. A broken plugin is logged and skipped — it
never takes Luxion down. This is a good way to propose a tool before it earns
a place in the core.

---

## The permission model

Luxion has **four layers**, in this order. Respect the order when you add
anything:

1. **OS privacy gates** — probed read-only from the Windows registry
   (`microphone`, `camera`, `location`). Luxion never writes OS state; it can
   only open the relevant `ms-settings:` page.
2. **App consents** — persisted in `<data_dir>/capabilities.json`
   (`speaker`, `screen_capture`, `notifications`, `input_control`, `terminal`).
   `terminal` ships **off**; the user must grant it explicitly.
3. **Account sources** — derived from connected accounts (e.g. `calendar`),
   never stored separately.
4. **Tool risk engine** — the autonomy matrix plus the confirmation guardrails.

**Rules that are not negotiable:**

- The capability check runs **before** the risk engine.
- A denied capability is a hard block that **no** autonomy level can override.
- A tool must never bypass its own `ToolSpec.requires`.
- Every tool call — success, failure, denial, timeout, bad arguments — lands in
  the append-only audit log (`<data_dir>/tool_log.jsonl`) with secrets redacted.

---

## Tests and quality gates

Run these before every push. All five must be clean.

```powershell
# Backend — 836 tests, 1 skipped (symlink creation not permitted on some machines)
cd backend
.\.venv\Scripts\pytest.exe
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .

# Frontend
cd ..\frontend
npm run lint            # oxlint
npm run build           # tsc -b && vite build

# Desktop shell
cd src-tauri
cargo check
```

Rules:

- **New behaviour needs a test.** A PR that changes code without touching
  `backend/tests/` will be asked for one.
- Tests must not depend on network access, a real mailbox, a real camera or a
  real WhatsApp account. Mock at the boundary.
- Use the fixtures in `backend/tests/conftest.py` (it pins config so a stray
  local `.env` cannot change results).
- `ruff format` and `ruff check` must pass with **zero** findings.
- The frontend build must exit 0 (`tsc -b` is the type gate).

---

## Commits, branches and pull requests

**Branch names**

```
feature/add-weather-tool
fix/whatsapp-draft-encoding
docs/setup-troubleshooting
```

**Commit messages** — imperative, prefixed with the scope, one logical change
per commit:

```
Add Phase 9 web intelligence: DDG search, Open-Meteo weather, RSS/HN news
Add SETUP.md - detailed setup and user guide
Record Phase 10 commit hash in memory.md
Fix web speed test 403 by sending Origin header
```

**Before you open a PR**

1. `git fetch upstream && git rebase upstream/main`
2. Run the full quality-gate suite above.
3. Update `memory.md` — it is the living project log and must reflect your
   change.
4. Make sure `git status` shows no stray `.env`, `database/*.json`, API keys or
   local artefacts.

**PR description should answer**

- What problem does this solve?
- What did you change?
- How did you test it?
- Any new dependency? (justify it — see [FOSS-first](#python-backend))
- Screenshots or a short clip for UI changes.

The pull request template at
[`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md) has a
checklist covering all of this — tick the boxes rather than re-typing them.

**Good first issues** are labelled `good first issue` — they are scoped so a
new contributor can finish them in an evening. Ask for one if you want a
starting point.

---

## Documentation rules

Four documents, each with a distinct owner:

| File | Role | Update it when |
|---|---|---|
| `prd.md` | **source of truth** for requirements | a requirement changes |
| `memory.md` | living status log | **after every phase or change** |
| `SETUP.md` | install + usage guide for users | setup steps or UI change |
| `design-system/luxion/MASTER.md` | UI rules and tokens | a token or rule changes |

If your change alters behaviour, update `memory.md` in the **same PR**. A
behaviour change without a log entry is incomplete.

---

## Security and secrets

- **Never commit secrets.** `.env`, `database/*.json`, `database/*.ics` and
  `api_key` are gitignored. Keep it that way.
- If a key is ever pushed by accident, **rotate it immediately** — removing it
  from git history is not enough.
- Secrets are read from **environment variables only**, never from a literal in
  source. SMTP/IMAP passwords live in `LUXION_EMAIL__SMTP_PASSWORD` and
  nowhere else.
- Structured logs **redact** anything matching
  `key|token|password|secret|credential|auth`. If you add a new field that can
  hold a secret, extend that pattern in `backend/luxion/logging_setup.py`.
- **Local-first is a promise.** Nothing leaves the machine unless the user
  explicitly selects a cloud provider in Settings. Do not add telemetry, and
  do not add a network call that isn't in the documented capability set.
- The email, WhatsApp and notification tools send **real messages**. Their
  tests must never hit a live server.

---

## Code of conduct

Be respectful and constructive. Assume good faith, critique the code and not
the person, and accept that maintainers may ask for changes before merging.

Report unacceptable behaviour by opening an issue or contacting the maintainer
directly. This project follows the
[Contributor Covenant v2.1](https://www.contributor-covenant.org/version/2/1/code_of_conduct/).

---

## License

Luxion is released under the **MIT License** — see [`LICENSE`](LICENSE).

By contributing you agree that your contributions are licensed under the same
terms.

---

**Questions?** Open a GitHub Issue, or start a discussion. For anything about
setup, [`SETUP.md`](SETUP.md) has a troubleshooting section that covers the
common cases.

Thanks for contributing. 🤖

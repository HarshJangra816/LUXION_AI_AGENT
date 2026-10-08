"""Configuration system for Luxion.

All runtime configuration is resolved through :class:`Settings`.
Values come from (in increasing priority):

1. Built-in defaults
2. A ``.env`` file at the project root (optional)
3. Environment variables prefixed with ``LUXION_``
   (nested fields use ``__`` as delimiter, e.g. ``LUXION_SERVER__PORT``)
4. The provider selection saved from the Settings page
   (``<data_dir>/llm_provider.json`` — adapter + model only, see
   :func:`apply_provider_selection`)
5. The voice edits saved from the Settings page
   (``<data_dir>/voice.json`` — partial overlay, see
   :func:`apply_voice_overrides`)
6. The RAG edits saved from the Settings → Memory page
   (``<data_dir>/rag.json`` — partial overlay, see
   :func:`apply_rag_overrides`)

No secrets are ever hardcoded here. API keys are referenced either
directly through a secret-typed setting or via an environment variable
name held in ``LLMConfig.api_key_env``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from luxion.config import rag_override
from luxion.config.provider_override import load_selection
from luxion.config.voice_override import load_overrides, save_overrides

# Luxion/backend/luxion/config/settings.py -> parents: [config, luxion, backend, Luxion]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = Path(__file__).resolve().parents[2]


class AppConfig(BaseModel):
    environment: Literal["development", "test", "production"] = "development"
    data_dir: Path = PROJECT_ROOT / "database"
    logs_dir: Path = PROJECT_ROOT / "logs"


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(default=8756, ge=1, le=65535)
    reload: bool = False
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            # Vite dev server
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            # Tauri webview origins (Windows/Linux use http://tauri.localhost)
            "http://tauri.localhost",
            "tauri://localhost",
        ]
    )


class DatabaseConfig(BaseModel):
    """Database settings. Empty ``url`` derives a SQLite path from ``app.data_dir``."""

    url: str = ""
    echo: bool = False


#: Local Ollama endpoint. Doubles as the "unset" sentinel for providers that
#: bring their own default base URL (OpenRouter), so switching ``llm.provider``
#: does not silently keep pointing at a local server.
OLLAMA_BASE_URL = "http://127.0.0.1:11434"

#: Adapter ids the Settings page may select at runtime. Kept in sync with
#: ``luxion.llm.registry.PROVIDER_TYPES`` (asserted by the test suite) — it is
#: repeated here so this module never has to import the providers.
SELECTABLE_PROVIDERS: frozenset[str] = frozenset(
    {"ollama", "openai", "openai_compatible", "openrouter", "mock"}
)

#: Endpoint each adapter is pointed at once selected.
#: ``None`` = keep the ``.env`` value (it already is that adapter's URL —
#: ``LUXION_LLM__BASE_URL`` defaults to Ollama and is where custom
#: OpenAI-compatible endpoints are configured), ``""`` = let the provider fall
#: back to its own default (OpenRouter, mock).
SELECTED_BASE_URLS: dict[str, str | None] = {
    "ollama": None,
    "openai_compatible": None,
    "openai": "https://api.openai.com/v1",
    "openrouter": "",
    "mock": "",
}


class LLMConfig(BaseModel):
    """Provider settings. Consumed by the LLM manager from Phase 1 onwards."""

    provider: str = "ollama"
    model: str = ""
    base_url: str = OLLAMA_BASE_URL
    api_key: str | None = Field(default=None, repr=False)
    api_key_env: str = ""
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, ge=1)
    request_timeout_s: float = Field(default=120.0, gt=0)
    #: Ollama only: let a reasoning model (qwen3.5 and friends) think first.
    #: On they emit ``message.thinking`` and no content until they are done,
    #: which reads as "not replying" for tens of seconds; off is the default
    #: until the composer can render a thinking stream.
    think: bool = False
    #: Overrides the built-in system prompt when non-empty.
    system_prompt: str = ""
    #: Artificial per-chunk delay for ``provider = "mock"`` (0 = instant).
    mock_delay_s: float = Field(default=0.0, ge=0.0)

    @field_validator("api_key", mode="before")
    @classmethod
    def _empty_str_to_none(cls, value: object) -> object:
        return None if value == "" else value


class ContextConfig(BaseModel):
    """Context window policy (consumed by :mod:`luxion.context`)."""

    total_budget_tokens: int = Field(default=32_000, ge=1_000)
    reserve_tokens: int = Field(default=4_000, ge=0)
    max_tool_result_chars: int = Field(default=6_000, ge=200)
    max_history_messages: int = Field(default=50, ge=2)
    #: Newest messages always sent, even when the budget is already full.
    keep_recent_messages: int = Field(default=6, ge=1)
    #: Rolling summary of older messages (off = oldest turns are just dropped).
    summary_enabled: bool = True
    summary_max_tokens: int = Field(default=1_200, ge=200)
    #: Triggers summarization once this many uncovered messages pile up.
    summary_min_messages: int = Field(default=4, ge=1)


class SecurityConfig(BaseModel):
    autonomy_level: int = Field(default=3, ge=0, le=5)
    #: Directories file tools may touch. Defaults to the project root so the
    #: tools work out of the box without granting the whole drive (PRD §42).
    allowed_workspaces: list[Path] = Field(default_factory=lambda: [PROJECT_ROOT])
    terminal_timeout_s: float = Field(default=60.0, gt=0)
    require_confirmation_high: bool = True
    require_confirmation_critical: bool = True

    @field_validator("allowed_workspaces", mode="before")
    @classmethod
    def _split_workspaces(cls, value: object) -> object:
        if isinstance(value, str):
            paths = [p.strip() for p in value.split(";") if p.strip()]
            # An unset/empty env var means "the default", not "no workspace":
            # silently locking every file tool out is a nasty surprise.
            return paths or [PROJECT_ROOT]
        return value


class ToolsConfig(BaseModel):
    """Tool framework policy (PRD §18-21, Phase 3)."""

    #: Master switch — off means the model is never offered any tools.
    enabled: bool = True
    #: Hard cap on agent rounds per user turn (PRD §57 rule 9: no infinite loops).
    max_iterations: int = Field(default=6, ge=1, le=20)
    #: Per-tool wall clock limit.
    timeout_s: float = Field(default=30.0, gt=0)
    #: How many tools may be exposed to the model in one request (PRD §19).
    max_exposed: int = Field(default=16, ge=1, le=256)
    #: Retained audit-log entries (PRD §43).
    log_limit: int = Field(default=500, ge=10, le=10_000)
    #: How long the user has to answer a confirmation prompt.
    confirm_timeout_s: float = Field(default=180.0, gt=0)
    #: Extra directories scanned for dynamically loaded tool modules.
    plugin_dirs: list[Path] = Field(default_factory=list)

    @field_validator("plugin_dirs", mode="before")
    @classmethod
    def _split_dirs(cls, value: object) -> object:
        if isinstance(value, str):
            return [p.strip() for p in value.split(";") if p.strip()]
        return value


class LoggingConfig(BaseModel):
    level: str = "INFO"
    json_logs: bool = True
    console: bool = True
    file_name: str = "luxion.log"
    max_bytes: int = Field(default=5 * 1024 * 1024, ge=1024)
    backup_count: int = Field(default=3, ge=0)


class VoiceConfig(BaseModel):
    """Voice pipeline policy (PRD §26, §5.5, §5.6, Phase 4).

    Defaults are chosen so the feature is *safe* out of the box: the mic is
    only opened after the user asks for it, replies are only spoken while the
    voice session is live, and every hardware gate is still enforced by
    :mod:`luxion.security.capabilities` before anything touches a device.
    """

    master: bool = True
    # -- speech to text (PRD §5.5) ----------------------------------------
    stt_provider: str = "whisper"
    stt_model: str = "base.en"
    stt_device: str = "auto"
    stt_compute_type: str = "int8"
    #: "" = auto-detect; ``.en`` models are English-only regardless.
    stt_language: str = ""
    # -- text to speech (PRD §5.6) ----------------------------------------
    #: ``windows`` = offline SAPI5, ``omnivoice`` = local neural voice design.
    tts_provider: str = "windows"
    tts_enabled: bool = True
    #: SAPI5 rate offset in words/minute around the voice's natural rate.
    tts_rate: int = Field(default=0, ge=-50, le=100)
    tts_volume: int = Field(default=100, ge=0, le=100)
    #: OmniVoice model id or local path (only used by the omnivoice provider).
    tts_model: str = "k2-fsa/OmniVoice"
    #: Voice design prompt, e.g. "female, british accent, moderate pitch".
    #: Blank lets the model pick a voice on its own.
    tts_instruct: str = "female, young adult, moderate pitch"
    #: Diffusion steps - fewer steps synthesize faster on the CPU
    #: (~11 s at 4, ~23 s at 8, ~47 s at 16 for a short sentence).
    tts_steps: int = Field(default=8, ge=4, le=64)
    #: OmniVoice language hint ("English", "en", ...); "" = language agnostic.
    tts_language: str = ""
    # -- wake word (PRD §26) ----------------------------------------------
    wake_enabled: bool = True
    wake_phrase: str = "hey luxion"
    #: Seconds a bare "Hey Luxion" stays armed awaiting the command.
    wake_arm_s: float = Field(default=20.0, ge=1.0, le=120.0)
    # -- capture / VAD ------------------------------------------------------
    #: PortAudio device index or name fragment; "" = system default.
    mic_device: str = ""
    #: Energy gate for speech (RMS). Below the learned noise floor × 2.5.
    vad_threshold: float = Field(default=0.01, gt=0.0, le=0.5)
    min_speech_s: float = Field(default=0.2, ge=0.0, le=2.0)
    silence_s: float = Field(default=0.9, ge=0.2, le=5.0)
    max_utterance_s: float = Field(default=30.0, ge=3.0, le=240.0)
    #: Stop TTS playback when the user talks over it (PRD §26 interruption).
    barge_in: bool = True
    #: Push-to-talk budget in the composer.
    ptt_timeout_s: float = Field(default=15.0, ge=3.0, le=120.0)


class EmbeddingModelSpec(BaseModel):
    """One model offered by Settings → Memory (PRD §16 embedding step)."""

    id: str
    label: str
    #: Vector width. ``chunks_vec`` is built with it, so changing model means
    #: re-embedding (the store keeps the raw vectors, not just the index).
    dim: int
    size_gb: float
    languages: str


#: Curated fastembed models — every entry is in
#: ``fastembed.TextEmbedding.list_supported_models()`` (asserted by tests), so
#: the dropdown never offers something that needs a custom registration.
EMBEDDING_MODELS: tuple[EmbeddingModelSpec, ...] = (
    EmbeddingModelSpec(
        id="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        label="Multilingual MiniLM (recommended)",
        dim=384,
        size_gb=0.22,
        languages="~50 languages (incl. Hindi, English)",
    ),
    EmbeddingModelSpec(
        id="jinaai/jina-embeddings-v2-base-code",
        label="Jina v2 Base — code & multilingual",
        dim=768,
        size_gb=0.64,
        languages="30+ languages, code-aware",
    ),
    EmbeddingModelSpec(
        id="BAAI/bge-small-en-v1.5",
        label="BGE Small — English, lightest",
        dim=384,
        size_gb=0.067,
        languages="English",
    ),
    EmbeddingModelSpec(
        id="sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
        label="Multilingual MPNet — largest",
        dim=768,
        size_gb=1.0,
        languages="~50 languages (incl. Hindi)",
    ),
)

DEFAULT_EMBEDDING_MODEL = EMBEDDING_MODELS[0].id

#: Documents + source code extensions the indexer walks.
DEFAULT_INDEX_EXTENSIONS: list[str] = [
    ".md",
    ".txt",
    ".rst",
    ".sql",
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".rs",
    ".go",
    ".java",
    ".kt",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".cs",
    ".rb",
    ".php",
    ".sh",
    ".ps1",
    ".bat",
    ".yml",
    ".yaml",
    ".toml",
    ".json",
    ".css",
    ".html",
]

#: Directory / file names skipped entirely (matched against any path part).
DEFAULT_EXCLUDE: list[str] = [
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    "target",
    ".next",
    ".cache",
    "*.min.js",
    "*.map",
    "*.lock",
    "*.svg",
    "*.png",
    "*.jpg",
]


def embedding_dim_of(model_id: str) -> int | None:
    """Vector width for a curated model id (``None`` = unknown/custom)."""
    for spec in EMBEDDING_MODELS:
        if spec.id == model_id:
            return spec.dim
    return None


class RAGConfig(BaseModel):
    """Indexing + retrieval policy (PRD §16-17, Phase 5).

    The token budget for what retrieval is allowed to inject lives in
    :class:`ContextConfig` (that is where the budget maths runs); this model
    only decides *what gets indexed* and *how it is ranked*.
    """

    #: Master switch — off means nothing is indexed and retrieval returns [].
    enabled: bool = True
    #: Embedding backend. ``fastembed`` is the only one shipped so far.
    provider: str = "fastembed"
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    #: Prose chunk window (chars) and the tail carried into the next chunk.
    chunk_chars: int = Field(default=800, ge=200, le=4000)
    chunk_overlap: int = Field(default=120, ge=0, le=1000)
    #: How many hits a query returns before ranking/filtering.
    top_k: int = Field(default=6, ge=1, le=50)
    #: Cosine floor in 0..1 (identical text = 1.0). Below it a hit is dropped.
    min_score: float = Field(default=0.2, ge=0.0, le=1.0)
    #: Documents + source code extensions the indexer walks.
    index_extensions: list[str] = Field(default_factory=lambda: [*DEFAULT_INDEX_EXTENSIONS])
    #: Directory / file names skipped entirely (matched against any path part).
    exclude: list[str] = Field(default_factory=lambda: [*DEFAULT_EXCLUDE])
    #: Largest single file the indexer opens; bigger files stay unindexed.
    max_file_bytes: int = Field(default=512_000, ge=1024, le=20_000_000)
    #: Files walked in one sync — bounds a first pass over a large workspace.
    max_files: int = Field(default=5_000, ge=1, le=200_000)
    #: Sync the repository as soon as the backend boots. Off by default:
    #: embedding a whole workspace on CPU is not something to do unasked.
    index_on_start: bool = False
    #: Embedding batch size for the re-embed job (CPU friendly).
    reembed_batch: int = Field(default=32, ge=1, le=512)
    #: Keep extracting durable facts from finished turns (PRD §15).
    memory_extraction: bool = True
    #: Ceiling on stored memories — the conversation itself is never stored
    #: (PRD §58 rule 5), and this bounds what a long-lived install accumulates.
    memory_max: int = Field(default=500, ge=10, le=100_000)

    @field_validator("index_extensions", mode="before")
    @classmethod
    def _split_extensions(cls, value: object) -> object:
        if isinstance(value, str):
            # An empty env var must mean "the default", not "index nothing"
            # (same call as ``SecurityConfig.allowed_workspaces``).
            return [item.strip() for item in value.split(";") if item.strip()] or [
                *DEFAULT_INDEX_EXTENSIONS
            ]
        return value

    @field_validator("exclude", mode="before")
    @classmethod
    def _split_exclude(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(";") if item.strip()] or [*DEFAULT_EXCLUDE]
        return value


def _valid_rag_values(values: dict[str, object]) -> dict[str, object]:
    """Drop anything that is not a real :class:`RAGConfig` field with a sane type.

    A hand-edited ``rag.json`` must never take the app down; unknown keys and
    values pydantic rejects are simply ignored so ``.env`` keeps winning.
    """
    accepted: dict[str, object] = {}
    for key, value in values.items():
        if key not in RAGConfig.model_fields:
            continue
        try:
            RAGConfig(**{key: value})
        except Exception:  # noqa: BLE001 - a bad value only skips that key
            continue
        accepted[key] = value
    return accepted


def _valid_voice_values(values: dict[str, object]) -> dict[str, object]:
    """Drop anything that is not a real :class:`VoiceConfig` field with a sane type.

    A hand-edited ``voice.json`` must never take the app down; unknown keys and
    values pydantic rejects are simply ignored so ``.env`` keeps winning.
    """
    accepted: dict[str, object] = {}
    for key, value in values.items():
        if key not in VoiceConfig.model_fields:
            continue
        try:
            VoiceConfig(**{key: value})
        except Exception:  # noqa: BLE001 - a bad value only skips that key
            continue
        accepted[key] = value
    return accepted


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LUXION_",
        env_nested_delimiter="__",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app: AppConfig = AppConfig()
    server: ServerConfig = ServerConfig()
    db: DatabaseConfig = DatabaseConfig()
    llm: LLMConfig = LLMConfig()
    context: ContextConfig = ContextConfig()
    security: SecurityConfig = SecurityConfig()
    tools: ToolsConfig = ToolsConfig()
    voice: VoiceConfig = VoiceConfig()
    rag: RAGConfig = RAGConfig()
    logging: LoggingConfig = LoggingConfig()

    @property
    def embedding_dim(self) -> int:
        """Vector width of the configured model (curated models are known;
        a custom id falls back to the default model's width until the store
        records the real one in ``rag_meta``)."""
        return embedding_dim_of(self.rag.embedding_model) or embedding_dim_of(
            DEFAULT_EMBEDDING_MODEL
        )

    @model_validator(mode="after")
    def _resolve_defaults(self) -> Settings:
        if not self.db.url:
            self.db.url = f"sqlite:///{(self.app.data_dir / 'luxion.db').as_posix()}"
        return self

    @property
    def is_dev(self) -> bool:
        return self.app.environment != "production"

    def ensure_directories(self) -> None:
        self.app.data_dir.mkdir(parents=True, exist_ok=True)
        self.app.logs_dir.mkdir(parents=True, exist_ok=True)


def apply_provider_selection(settings: Settings) -> None:
    """Overlay the persisted Settings-page choice onto ``settings.llm``.

    Called by :func:`get_settings` right after ``Settings`` is built, so every
    consumer (chat, status, health) sees the adapter the user last tapped.
    Without a selection file nothing changes: ``.env`` stays authoritative.
    """
    selection = load_selection(settings.app.data_dir)
    if selection is None or selection.active not in SELECTABLE_PROVIDERS:
        return

    llm = settings.llm
    provider = selection.active
    model = selection.models.get(provider)
    if model is None:
        # Never edited in the UI: the adapter `.env` already points at keeps
        # its configured model; every other adapter auto-detects the first
        # model it reports (model ids do not transfer between providers).
        model = llm.model if provider == llm.provider else ""
    base_url = SELECTED_BASE_URLS[provider]

    llm.provider = provider
    llm.model = model
    if base_url is not None:
        llm.base_url = base_url


def apply_voice_overrides(settings: Settings) -> None:
    """Overlay the persisted Settings → Voice edits onto ``settings.voice``.

    Called by :func:`get_settings` after the provider selection. Only fields
    the user actually changed are stored, so ``.env`` keeps every default it
    was not told to change.
    """
    values = _valid_voice_values(load_overrides(settings.app.data_dir))
    if not values:
        return
    settings.voice = VoiceConfig(**{**settings.voice.model_dump(), **values})


def save_voice_overrides(settings: Settings, values: dict[str, object]) -> None:
    """Persist a partial voice overlay and refresh the cached settings.

    The overlay only ever holds the fields the user actually touched, so a
    patch must **merge** into what is already stored — writing it verbatim
    would silently revert every knob the user had changed earlier back to
    ``.env``. Nothing to store (every key was invalid) leaves the file alone.
    """
    valid = _valid_voice_values(values)
    if valid:
        save_overrides(settings.app.data_dir, {**load_overrides(settings.app.data_dir), **valid})
    reset_settings_cache()


def apply_rag_overrides(settings: Settings) -> None:
    """Overlay the persisted Settings → Memory edits onto ``settings.rag``.

    Called by :func:`get_settings` last, so ``<data_dir>/rag.json`` wins over
    ``LUXION_RAG__*`` exactly like the voice and provider overlays.
    """
    values = _valid_rag_values(rag_override.load_overrides(settings.app.data_dir))
    if not values:
        return
    settings.rag = RAGConfig(**{**settings.rag.model_dump(), **values})


def save_rag_overrides(settings: Settings, values: dict[str, object]) -> None:
    """Persist a partial RAG overlay and refresh the cached settings.

    Merges into what is already stored (same reason as
    :func:`save_voice_overrides`): a patch only carries the fields the user
    changed, and writing it verbatim would silently revert the rest.
    """
    valid = _valid_rag_values(values)
    if valid:
        rag_override.save_overrides(
            settings.app.data_dir,
            {**rag_override.load_overrides(settings.app.data_dir), **valid},
        )
    reset_settings_cache()


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    apply_provider_selection(settings)
    apply_voice_overrides(settings)
    apply_rag_overrides(settings)
    return settings


def reset_settings_cache() -> None:
    """Drop the cached settings so the next :func:`get_settings` re-reads
    ``.env`` and the persisted provider selection (tests + Settings switches)."""
    get_settings.cache_clear()

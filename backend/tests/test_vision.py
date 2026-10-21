"""Vision core: image plumbing, imaging, analyzer and the two tools.

Phase 11a (PRD §5.9, §33.15). Hermetic: the provider is faked, so no model
server is needed and no image ever leaves the box.
"""

from __future__ import annotations

import asyncio
import base64
import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from luxion.config.settings import Settings
from luxion.llm.types import (
    ChatMessage,
    ImagePayload,
    ollama_message_payload,
    openai_message_payload,
)
from luxion.tools.base import ToolContext, ToolError
from luxion.tools.builtin.vision import AnalyzeImage, AnalyzeScreenshot
from luxion.tools.registry import build_registry
from luxion.vision.analyzer import analyze_images, resolve_vision_llm
from luxion.vision.imaging import VisionError, prepare_image

VISION_TOOL_NAMES = {"analyze_image", "analyze_screenshot"}


def run(coro):  # noqa: ANN001, ANN201
    return asyncio.run(coro)


def _ctx(vision: dict | None = None) -> ToolContext:
    return ToolContext(Settings(vision=vision or {}))


def _png(width: int = 40, height: int = 30) -> bytes:
    """A tiny PNG built with Pillow (no binary fixture in the repo)."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (12, 34, 56)).save(buffer, format="PNG")
    return buffer.getvalue()


class _FakeProvider:
    """Records the messages it was handed and answers with fixed text."""

    def __init__(self, text: str = "A blue rectangle.") -> None:
        self.text = text
        self.messages: list[ChatMessage] = []
        self.model: str | None = None

    async def resolve_model(self) -> str:
        return "fake-vision"

    async def complete(self, messages, *, model=None, **_kwargs):  # noqa: ANN001, ANN003
        self.messages = list(messages)
        self.model = model
        return SimpleNamespace(text=self.text)


def _patch_provider(monkeypatch: pytest.MonkeyPatch, provider: _FakeProvider) -> None:
    import luxion.vision.analyzer as analyzer

    monkeypatch.setattr(analyzer, "get_provider", lambda _config: provider)


# ------------------------------------------------------------------ provider payloads
def test_chat_message_carries_images() -> None:
    message = ChatMessage(
        role="user",
        content="what is this?",
        images=[ImagePayload(data="QUJD", mime="image/png")],
    )
    assert message.images[0].data == "QUJD"
    assert message.images[0].data_url == "data:image/png;base64,QUJD"


def test_ollama_payload_puts_images_beside_the_content() -> None:
    payload = ollama_message_payload(
        ChatMessage(
            role="user",
            content="hello",
            images=[ImagePayload(data="QUJD"), ImagePayload(data="REVG")],
        )
    )
    assert payload["role"] == "user"
    assert payload["content"] == "hello"
    assert payload["images"] == ["QUJD", "REVG"]


def test_openai_payload_uses_the_content_array() -> None:
    payload = openai_message_payload(
        ChatMessage(
            role="user",
            content="hello",
            images=[ImagePayload(data="QUJD", mime="image/jpeg")],
        )
    )
    assert payload["content"] == [
        {"type": "text", "text": "hello"},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,QUJD"}},
    ]


def test_text_only_messages_are_unchanged() -> None:
    message = ChatMessage(role="user", content="hi")
    assert ollama_message_payload(message) == {"role": "user", "content": "hi"}
    assert openai_message_payload(message) == {"role": "user", "content": "hi"}


# ------------------------------------------------------------------------ imaging
def test_prepare_image_encodes_and_downscales(tmp_path: Path) -> None:
    target = tmp_path / "big.png"
    target.write_bytes(_png(4000, 2000))

    prepared = prepare_image(target, max_dimension=1568)

    assert prepared.mime == "image/png"
    assert prepared.width == 1568
    assert prepared.height == 784
    assert prepared.source == "big.png"
    # The payload really is base64-encoded PNG bytes.
    assert base64.b64decode(prepared.data)[:4] == b"\x89PNG"


def test_prepare_image_accepts_raw_bytes(tmp_path: Path) -> None:
    prepared = prepare_image(_png(10, 10))
    assert prepared.width == 10
    assert prepared.height == 10


def test_prepare_image_reports_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(VisionError) as excinfo:
        prepare_image(tmp_path / "nope.png")
    assert excinfo.value.code == "vision_not_found"


def test_prepare_image_rejects_an_unsupported_type(tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("hello", encoding="utf-8")
    with pytest.raises(VisionError) as excinfo:
        prepare_image(target)
    assert excinfo.value.code == "vision_unsupported_type"


def test_prepare_image_refuses_a_file_over_the_byte_budget(tmp_path: Path) -> None:
    target = tmp_path / "big.png"
    target.write_bytes(_png(3000, 3000))
    with pytest.raises(VisionError) as excinfo:
        prepare_image(target, max_bytes=1_000)
    assert excinfo.value.code == "vision_too_large"


# ----------------------------------------------------------------------- resolver
def test_resolve_vision_llm_uses_the_chat_model_by_default() -> None:
    settings = Settings(llm={"provider": "ollama", "model": "chat-model"})
    config, model = resolve_vision_llm(settings)
    assert model == "chat-model"
    assert config.provider == "ollama"


def test_resolve_vision_llm_prefers_the_vision_model() -> None:
    settings = Settings(
        llm={"provider": "ollama", "model": "chat-model"},
        vision={"model": "qwen2.5vl:3b"},
    )
    _config, model = resolve_vision_llm(settings)
    assert model == "qwen2.5vl:3b"


def test_resolve_vision_llm_can_override_the_endpoint() -> None:
    settings = Settings(
        llm={"provider": "ollama", "model": "chat-model"},
        vision={
            "provider": "openai",
            "base_url": "https://vision.example/v1",
            "api_key_env": "VISION_KEY",
            "timeout_s": 30,
        },
    )
    config, _model = resolve_vision_llm(settings)
    assert config.provider == "openai"
    assert config.base_url == "https://vision.example/v1"
    assert config.api_key_env == "VISION_KEY"
    assert config.request_timeout_s == 30


# ----------------------------------------------------------------------- analyzer
def test_analyze_images_attaches_the_picture(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _FakeProvider("It is a blue rectangle.")
    _patch_provider(monkeypatch, provider)

    image = prepare_image(_png(12, 12))
    answer = run(analyze_images(Settings(), [image], question="what is this?"))

    assert answer == "It is a blue rectangle."
    assert provider.messages, "the provider must have been called"
    sent = provider.messages[0]
    assert sent.role == "user"
    assert "what is this?" in sent.content
    assert sent.images and sent.images[0].mime == "image/png"


def test_analyze_images_refuses_when_vision_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _FakeProvider()
    _patch_provider(monkeypatch, provider)

    image = prepare_image(_png(12, 12))
    with pytest.raises(VisionError) as excinfo:
        run(analyze_images(Settings(vision={"enabled": False}), [image]))
    assert excinfo.value.code == "vision_disabled"
    assert not provider.messages, "the provider must not be called"


def test_analyze_images_refuses_without_an_image(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_provider(monkeypatch, _FakeProvider())
    with pytest.raises(VisionError) as excinfo:
        run(analyze_images(Settings(), []))
    assert excinfo.value.code == "vision_no_image"


# ------------------------------------------------------------------------- tools
def test_both_vision_tools_are_registered() -> None:
    registry = build_registry(Settings())
    assert set(registry.names()) >= VISION_TOOL_NAMES
    assert registry.spec("analyze_image").risk == "low"
    assert registry.spec("analyze_image").read_only is True
    assert registry.spec("analyze_image").requires is None
    # Capturing the screen is hardware access (PRD §39).
    assert registry.spec("analyze_screenshot").requires == "screen_capture"


def test_analyze_image_answers_about_a_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _FakeProvider("A small blue square.")
    _patch_provider(monkeypatch, provider)

    target = tmp_path / "shot.png"
    target.write_bytes(_png(20, 20))

    settings = Settings(security={"allowed_workspaces": [tmp_path]})
    ctx = ToolContext(settings)
    result = run(AnalyzeImage().run({"path": str(target)}, ctx))

    assert result.ok is True
    assert result.output == "A small blue square."
    assert result.data["path"] == str(target)
    assert result.data["image"]["mime"] == "image/png"


def test_analyze_image_refuses_a_file_outside_the_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_provider(monkeypatch, _FakeProvider())

    target = tmp_path / "shot.png"
    target.write_bytes(_png(20, 20))
    elsewhere = tmp_path.parent / "elsewhere"
    elsewhere.mkdir(exist_ok=True)

    settings = Settings(security={"allowed_workspaces": [elsewhere]})
    ctx = ToolContext(settings)
    with pytest.raises(ToolError) as excinfo:
        run(AnalyzeImage().run({"path": str(target)}, ctx))
    assert excinfo.value.code == "workspace_violation"


def test_analyze_image_needs_a_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_provider(monkeypatch, _FakeProvider())
    with pytest.raises(ToolError) as excinfo:
        run(AnalyzeImage().run({}, _ctx()))
    assert excinfo.value.code == "invalid_arguments"


def test_analyze_image_surfaces_the_disabled_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_provider(monkeypatch, _FakeProvider())
    target = tmp_path / "shot.png"
    target.write_bytes(_png(20, 20))

    settings = Settings(
        security={"allowed_workspaces": [tmp_path]},
        vision={"enabled": False},
    )
    with pytest.raises(ToolError) as excinfo:
        run(AnalyzeImage().run({"path": str(target)}, ToolContext(settings)))
    assert excinfo.value.code == "vision_disabled"


def test_analyze_screenshot_captures_and_answers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _FakeProvider("A spreadsheet.")
    _patch_provider(monkeypatch, provider)

    class _Image:
        def save(self, path, format=None):  # noqa: ANN001, ARG002
            Path(path).write_bytes(_png(30, 20))

    def _grab():
        return _Image(), (30, 20)

    import luxion.tools.builtin.vision as vision_tools

    monkeypatch.setattr(vision_tools, "grab_screen", _grab)

    settings = Settings(security={"allowed_workspaces": [tmp_path]})
    result = run(AnalyzeScreenshot().run({}, ToolContext(settings)))

    assert result.output == "A spreadsheet."
    assert result.data["width"] == 30
    assert Path(result.data["path"]).exists()
    assert provider.messages[0].images, "the captured screen must reach the model"

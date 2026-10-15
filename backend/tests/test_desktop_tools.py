"""Desktop automation tools: the read-only surface + the safety gates (PRD §5.8, Phase 7).

These deliberately exercise only the parts that cannot disturb a person at the
keyboard: listing windows and processes, the settings gates, and input parsing.
Everything that types, clicks or moves the cursor is left to a live host.
"""

from __future__ import annotations

import pytest

from luxion.config.settings import Settings
from luxion.desktop import input as keys
from luxion.desktop.errors import DesktopError
from luxion.tools.base import ToolContext, ToolError
from luxion.tools.builtin.desktop import BUILTIN_TOOLS
from luxion.tools.registry import build_registry

TOOLS = {tool.spec.name: tool for tool in BUILTIN_TOOLS}


def asyncio_run(coro):  # noqa: ANN001, ANN201
    import asyncio

    return asyncio.run(coro)


def _ctx(settings: Settings) -> ToolContext:
    return ToolContext(settings)


def test_every_desktop_tool_is_registered() -> None:
    assert set(TOOLS) == {
        "list_applications",
        "focus_application",
        "list_processes",
        "inspect_window",
        "click_element",
        "press_keys",
        "type_text",
        "click_at",
        "control_volume",
        "control_brightness",
    }
    names = set(build_registry(Settings()).names())
    assert set(TOOLS) <= names


def test_the_four_input_tools_declare_the_capability() -> None:
    """PRD §39: anything typed or clicked as the user is gated, not just risky."""
    gated = {name for name, tool in TOOLS.items() if tool.spec.requires == "input_control"}
    assert gated == {"click_element", "press_keys", "type_text", "click_at"}

    # The rest read or change system state, so autonomy alone governs them.
    for name in ("list_applications", "list_processes", "inspect_window"):
        assert TOOLS[name].spec.requires is None


def test_risk_levels_follow_prd_section_20() -> None:
    risks = {name: tool.spec.risk for name, tool in TOOLS.items()}
    assert risks["list_applications"] == "low"
    assert risks["list_processes"] == "low"
    assert risks["inspect_window"] == "low"
    assert risks["control_volume"] == "medium"
    assert risks["control_brightness"] == "medium"
    # click_element acts on one named control through the accessibility tree,
    # which is why it sits below raw coordinate clicking.
    assert risks["click_element"] == "medium"
    # Raw keystrokes, typing and screen coordinates act as the user: high risk,
    # a confirmation at the default autonomy level.
    assert risks["press_keys"] == "high"
    assert risks["type_text"] == "high"
    assert risks["click_at"] == "high"


def test_list_applications_reports_visible_windows() -> None:
    result = asyncio_run(TOOLS["list_applications"].run({}, _ctx(Settings())))

    assert result.ok is True
    assert result.output.strip()
    # This suite runs headless, but Windows always has *some* titled window (the
    # shell at minimum), so the count is non-zero on a live desktop.
    assert result.data["total"] >= 1
    assert isinstance(result.data["windows"], list)


def test_list_applications_query_narrows_the_result() -> None:
    everything = asyncio_run(TOOLS["list_applications"].run({}, _ctx(Settings())))
    if everything.data["total"] == 0:
        return  # nothing on the desktop to narrow — nothing to assert

    first = everything.data["windows"][0]
    needle = first["title"].split(" - ")[0][:6] or first["process"]
    if not needle.strip():
        return

    narrowed = asyncio_run(TOOLS["list_applications"].run({"query": needle}, _ctx(Settings())))
    assert narrowed.ok is True
    titles = [row["title"] for row in narrowed.data["windows"]]
    assert any(needle.lower() in title.lower() for title in titles)


def test_list_processes_returns_a_ranked_list() -> None:
    result = asyncio_run(TOOLS["list_processes"].run({}, _ctx(Settings())))

    assert result.ok is True
    assert 1 <= len(result.data["processes"]) <= Settings().desktop.max_processes
    assert result.data["running"] >= 1
    names = [row["name"] for row in result.data["processes"]]
    assert all(isinstance(name, str) and name for name in names)


def test_list_processes_respects_the_configured_limit() -> None:
    settings = Settings(desktop={"max_processes": 5})
    result = asyncio_run(TOOLS["list_processes"].run({}, _ctx(settings)))

    assert len(result.data["processes"]) <= 5


def test_list_processes_query_filters_by_name() -> None:
    ctx = _ctx(Settings())
    result = asyncio_run(
        TOOLS["list_processes"].run({"query": "definitely-not-a-real-process"}, ctx)
    )
    assert result.ok is True
    assert result.data["processes"] == []
    assert result.data["matched"] == 0
    assert "no process" in result.output.lower()


# ------------------------------------------------------------------- gates
def test_disabled_master_switch_blocks_every_tool() -> None:
    settings = Settings(desktop={"enabled": False})
    ctx = _ctx(settings)

    for name in ("list_applications", "list_processes", "control_volume"):
        with pytest.raises(ToolError) as excinfo:
            asyncio_run(TOOLS[name].run({}, ctx))
        assert "disabled" in str(excinfo.value).lower()


def test_ui_automation_switch_blocks_the_tree_tools_only() -> None:
    settings = Settings(desktop={"ui_automation": False})
    ctx = _ctx(settings)

    with pytest.raises(ToolError) as excinfo:
        asyncio_run(TOOLS["inspect_window"].run({}, ctx))
    assert "ui automation" in str(excinfo.value).lower()

    # Focus and volume do not need the accessibility tree, so they still answer.
    assert TOOLS["focus_application"].spec.requires is None


def test_coordinate_switch_blocks_click_at_only() -> None:
    settings = Settings(desktop={"coordinate_fallback": False})
    ctx = _ctx(settings)

    with pytest.raises(ToolError) as excinfo:
        asyncio_run(TOOLS["click_at"].run({"x": 10, "y": 10}, ctx))
    assert "coordinate" in str(excinfo.value).lower()


def test_click_at_rejects_negative_coordinates() -> None:
    settings = Settings(desktop={"coordinate_fallback": True})
    with pytest.raises(ToolError) as excinfo:
        asyncio_run(TOOLS["click_at"].run({"x": -5, "y": 10}, _ctx(settings)))
    assert "negative" in str(excinfo.value).lower()


def test_volume_out_of_range_is_refused_not_clamped_silently() -> None:
    ctx = _ctx(Settings())
    with pytest.raises(ToolError) as excinfo:
        asyncio_run(TOOLS["control_volume"].run({"action": "set", "percent": 250}, ctx))
    assert "0" in str(excinfo.value) and "100" in str(excinfo.value)


# ------------------------------------------------------------- input parsing
def test_parse_chord_splits_modifiers_from_the_key() -> None:
    parsed = keys.parse_chord("ctrl+shift+s")

    assert parsed["main"] == "s"
    assert parsed["modifiers"] == ["ctrl", "shift"]
    assert isinstance(parsed["vk"], int) and parsed["vk"] > 0


def test_parse_chord_accepts_named_keys() -> None:
    for chord, expected in (("enter", "enter"), ("ctrl+left", "left"), ("f5", "f5")):
        assert keys.parse_chord(chord)["main"] == expected


def test_parse_chord_rejects_an_unknown_modifier() -> None:
    try:
        keys.parse_chord("meta+s")
    except DesktopError as exc:
        assert "meta" in str(exc).lower()
    else:  # pragma: no cover - the parse must not succeed
        raise AssertionError("an unknown modifier must not parse")


def test_parse_chord_rejects_an_empty_sequence() -> None:
    for empty in ("", "   ", "+"):
        try:
            keys.parse_chord(empty)
        except DesktopError:
            continue
        raise AssertionError(f"{empty!r} must not parse")


def test_split_sequence_groups_chords_on_whitespace() -> None:
    assert keys.split_sequence("ctrl+a ctrl+c enter") == ["ctrl+a", "ctrl+c", "enter"]
    assert keys.split_sequence("esc") == ["esc"]


def test_split_sequence_rejects_an_empty_sequence() -> None:
    try:
        keys.split_sequence("   ")
    except DesktopError as exc:
        assert "empty" in str(exc).lower()
    else:  # pragma: no cover
        raise AssertionError("an empty key sequence must not parse")

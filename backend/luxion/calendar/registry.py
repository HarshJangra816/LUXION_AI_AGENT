"""Connected calendar sources, persisted in ``<data_dir>/calendar_sources.json``.

The file stores *where* calendars live (path or URL) — events stay in the
sources themselves. Capability state derives from this registry: no sources
→ ``calendar`` is ``not_connected``.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from luxion.calendar.sources import (
    CalendarError,
    CalendarEvent,
    CalendarSourceInfo,
    IcsSubscriptionSource,
    LocalIcsSource,
    SourceKind,
)
from luxion.config.settings import Settings

logger = logging.getLogger(__name__)

_KNOWN_KINDS: tuple[SourceKind, ...] = ("local_ics", "ics_subscription")


class CalendarRegistry:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self.settings.app.data_dir / "calendar_sources.json"

    # storage -------------------------------------------------------------
    def _load(self) -> list[dict]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(raw, dict) or not isinstance(raw.get("sources"), list):
            return []
        items = []
        for entry in raw["sources"]:
            if (
                isinstance(entry, dict)
                and isinstance(entry.get("id"), str)
                and isinstance(entry.get("target"), str)
                and entry.get("kind") in _KNOWN_KINDS
            ):
                items.append(entry)
        return items

    def _save(self, items: list[dict]) -> None:
        if not items:
            if self.path.exists():
                self.path.unlink()
            return
        payload = json.dumps({"sources": items}, indent=2, sort_keys=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(self.path)

    # reads ---------------------------------------------------------------
    def list(self) -> list[CalendarSourceInfo]:
        infos: list[CalendarSourceInfo] = []
        for item in self._load():
            infos.append(
                CalendarSourceInfo(
                    id=item["id"],
                    kind=item["kind"],
                    label=item.get("label") or item["target"],
                    target=item["target"],
                    writable=item["kind"] == "local_ics",
                )
            )
        return infos

    def has_sources(self) -> bool:
        return bool(self._load())

    def sources(self) -> list[LocalIcsSource | IcsSubscriptionSource]:
        sources: list[LocalIcsSource | IcsSubscriptionSource] = []
        for info in self.list():
            if info.kind == "local_ics":
                sources.append(LocalIcsSource(info))
            else:
                sources.append(IcsSubscriptionSource(info))
        return sources

    def writable_source(self) -> LocalIcsSource | None:
        for source in self.sources():
            if isinstance(source, LocalIcsSource):
                return source
        return None

    # writes --------------------------------------------------------------
    def add(
        self, kind: str, *, target: str | None = None, label: str | None = None
    ) -> CalendarSourceInfo:
        """Validate + connect a source. Raises :class:`CalendarError` with a
        user-facing message on anything wrong."""
        if kind not in _KNOWN_KINDS:
            raise CalendarError(f"unknown calendar source kind '{kind}'")
        with self._lock:
            items = self._load()
            if kind == "local_ics":
                info = self._prepare_local(target, label, items)
            else:
                info = self._prepare_subscription(target, label, items)
            items.append(
                {"id": info.id, "kind": info.kind, "label": info.label, "target": info.target}
            )
            self._save(items)
            return info

    def remove(self, source_id: str | None = None) -> int:
        """Disconnect one source (or, with ``None``, all of them)."""
        with self._lock:
            items = self._load()
            keep = [item for item in items if source_id and item["id"] != source_id]
            removed = len(items) - len(keep)
            if removed:
                self._save(keep)
            return removed

    def _prepare_local(
        self, target: str | None, label: str | None, items: list[dict]
    ) -> CalendarSourceInfo:
        if target and target.strip():
            path = Path(target.strip()).expanduser()
            if not path.is_absolute():
                path = self.settings.app.data_dir / path
        else:
            path = self.settings.app.data_dir / "calendar.ics"
        if any(item["kind"] == "local_ics" and item["target"] == str(path) for item in items):
            raise CalendarError(f"{path} is already connected")
        if path.exists():
            try:
                text = path.read_text(encoding="utf-8-sig")
            except OSError as exc:
                raise CalendarError(f"cannot read {path}: {exc}") from exc
            if "BEGIN:VCALENDAR" not in text.upper():
                raise CalendarError(f"{path} is not an iCalendar (.ics) file")
        else:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
                    "PRODID:-//Luxion//Calendar//EN\r\nEND:VCALENDAR\r\n",
                    encoding="utf-8",
                )
            except OSError as exc:
                raise CalendarError(f"cannot create {path}: {exc}") from exc
        return CalendarSourceInfo(
            id=uuid.uuid4().hex[:8],
            kind="local_ics",
            label=(label or "").strip() or f"Local file ({path.name})",
            target=str(path),
            writable=True,
        )

    def _prepare_subscription(
        self, target: str | None, label: str | None, items: list[dict]
    ) -> CalendarSourceInfo:
        url = (target or "").strip()
        if not url.startswith(("http://", "https://")):
            raise CalendarError("subscription URL must start with http:// or https://")
        if any(item["kind"] == "ics_subscription" and item["target"] == url for item in items):
            raise CalendarError("this calendar is already connected")
        probe = IcsSubscriptionSource(
            CalendarSourceInfo(
                id="probe", kind="ics_subscription", label="probe", target=url, writable=False
            )
        )
        text = probe.fetch()
        if "BEGIN:VCALENDAR" not in text.upper():
            raise CalendarError("that URL did not return an iCalendar feed")
        return CalendarSourceInfo(
            id=uuid.uuid4().hex[:8],
            kind="ics_subscription",
            label=(label or "").strip() or "Subscribed calendar",
            target=url,
            writable=False,
        )

    # events --------------------------------------------------------------
    def events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        """Merged view; a broken subscription is skipped, never fatal."""
        merged: list[CalendarEvent] = []
        for source in self.sources():
            try:
                merged.extend(source.list_events(start, end))
            except CalendarError as exc:
                logger.warning(
                    "calendar_source_failed", extra={"source": source.info.id, "error": str(exc)}
                )
        return sorted(merged, key=lambda event: (event.start, event.title))

    def create_event(
        self,
        title: str,
        start: datetime,
        end: datetime | None = None,
        *,
        all_day: bool = False,
        description: str = "",
        location: str = "",
    ) -> CalendarEvent:
        source = self.writable_source()
        if source is None:
            raise CalendarError("no writable calendar connected — add a local .ics file first")
        return source.create_event(
            title, start, end, all_day=all_day, description=description, location=location
        )

    def upcoming(self, days: int = 30) -> list[CalendarEvent]:
        now = datetime.now().astimezone()
        return self.events(now, now + timedelta(days=days))


_registry: CalendarRegistry | None = None
_registry_key: tuple | None = None


def get_calendar_registry(settings: Settings | None = None) -> CalendarRegistry:
    global _registry, _registry_key
    from luxion.config.settings import get_settings

    resolved = settings or get_settings()
    key = (str(resolved.app.data_dir),)
    if _registry is None or _registry_key != key:
        _registry = CalendarRegistry(resolved)
        _registry_key = key
    return _registry


def reset_calendar_registry() -> None:
    global _registry, _registry_key
    _registry = None
    _registry_key = None

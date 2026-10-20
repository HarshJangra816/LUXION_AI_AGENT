"""Email (Phase 10, PRD §33.4): MIME, drafts, SMTP/IMAP seams, tools, API. Hermetic.

SMTP and IMAP are exercised through fake ``smtplib`` / ``imaplib`` modules
swapped into the module globals, so no packet leaves the box and no real mail
can be sent from CI. The credential rules are asserted explicitly: the secret
never reaches the overlay, the bundle or the patch model.
"""

from __future__ import annotations

import asyncio
import imaplib as real_imaplib
import json
import smtplib as real_smtplib
from email.message import EmailMessage
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from luxion.config import email_override
from luxion.config.settings import (
    EMAIL_SECRET_FIELDS,
    EmailConfig,
    Settings,
    get_settings,
    reset_settings_cache,
)
from luxion.email.drafts import create_draft, delete_draft, drafts_dir, list_drafts, load_draft
from luxion.email.errors import MailError
from luxion.email.message import build_message, render_preview
from luxion.email.smtp_send import (
    is_imap_configured,
    is_smtp_configured,
    resolve_password,
    send_message,
)
from luxion.tools.base import ToolContext, ToolError
from luxion.tools.builtin.email_tools import (
    CATEGORY,
    EmailDraft,
    EmailRead,
    EmailSend,
    EmailSendDraft,
)
from luxion.tools.registry import build_registry

SMTP_CONFIG = {"enabled": True, "smtp_host": "smtp.test", "from_address": "me@test.com"}


def run(coro):  # noqa: ANN001, ANN201
    return asyncio.run(coro)


@pytest.fixture()
def clean_email(client: TestClient):  # noqa: ANN201
    """The shared data dir is suite-wide — keep email.json/drafts hermetic."""
    data_dir = get_settings().app.data_dir
    email_override.clear_overrides(data_dir)
    for path in drafts_dir(data_dir).glob("*.json"):
        path.unlink(missing_ok=True)
    reset_settings_cache()
    yield client
    email_override.clear_overrides(data_dir)
    for path in drafts_dir(data_dir).glob("*.json"):
        path.unlink(missing_ok=True)
    reset_settings_cache()


# ------------------------------------------------------------------- fake SMTP
class _FakeSMTP:
    """Stands in for smtplib.SMTP / SMTP_SSL; records the session shape."""

    last: _FakeSMTP | None = None
    ssl = False
    login_error: Exception | None = None
    recipients_refused = False

    def __init__(self, host, port, timeout=None):  # noqa: ANN001, ANN201
        self.host, self.port, self.timeout = host, port, timeout
        self.calls: list[tuple] = []
        self.sent: list[tuple] = []
        _FakeSMTP.last = self

    def ehlo(self):
        self.calls.append(("ehlo",))

    def starttls(self):
        self.calls.append(("starttls",))

    def has_extn(self, name):  # noqa: ANN001
        self.calls.append(("has_extn", name))
        return False

    def login(self, username, password):  # noqa: ANN001
        self.calls.append(("login", username, password))
        if _FakeSMTP.login_error:
            raise _FakeSMTP.login_error

    def send_message(self, message, from_addr=None, to_addrs=None):  # noqa: ANN001
        self.sent.append((message, from_addr, tuple(to_addrs or ())))
        if _FakeSMTP.recipients_refused:
            raise real_smtplib.SMTPRecipientsRefused({"nobody@x": (550, b"nope")})
        return {}

    def quit(self):
        self.calls.append(("quit",))


@pytest.fixture()
def fake_smtp(monkeypatch):  # noqa: ANN201
    _FakeSMTP.last = None
    _FakeSMTP.login_error = None
    _FakeSMTP.recipients_refused = False

    def make_ssl(host, port, timeout=None):  # noqa: ANN001, ANN201
        _FakeSMTP.ssl = True
        return _FakeSMTP(host, port, timeout=timeout)

    def make_plain(host, port, timeout=None):  # noqa: ANN001, ANN201
        _FakeSMTP.ssl = False
        return _FakeSMTP(host, port, timeout=timeout)

    monkeypatch.setattr(
        "luxion.email.smtp_send.smtplib",
        SimpleNamespace(
            SMTP=make_plain,
            SMTP_SSL=make_ssl,
            SMTPAuthenticationError=real_smtplib.SMTPAuthenticationError,
            SMTPRecipientsRefused=real_smtplib.SMTPRecipientsRefused,
            SMTPException=real_smtplib.SMTPException,
        ),
    )
    return _FakeSMTP


# ------------------------------------------------------------------- fake IMAP
_RAW_ONE = (
    b"From: Alice <alice@example.com>\r\n"
    b"To: me@test.com\r\n"
    b"Subject: =?utf-8?b?SGVsbG8gd29ybGQ=?=\r\n"
    b"Date: Mon, 19 Oct 2026 10:00:00 +0000\r\n"
    b"\r\n"
    b"Hi, the quarterly numbers are attached."
)
_RAW_TWO = b"From: Bob <bob@example.com>\r\nSubject: Lunch?\r\n\r\nWant to grab lunch tomorrow?"


class _FakeIMAP:
    login_error: Exception | None = None

    def __init__(self, host, port, timeout=None):  # noqa: ANN001, ANN201
        self.host, self.port = host, port
        self.selected = False
        self.logged_out = False

    def login(self, username, password):  # noqa: ANN001
        if _FakeIMAP.login_error:
            raise _FakeIMAP.login_error

    def select(self, box, readonly=False):  # noqa: ANN001
        self.selected = True
        return ("OK", [b"2"])

    def uid(self, command, *args):  # noqa: ANN001
        if command == "search":
            return ("OK", [b"100 101"])
        if command == "fetch":
            uid = args[0]  # called as uid("fetch", b"100", "(BODY.PEEK[])")
            raw = _RAW_ONE if uid == b"100" else _RAW_TWO
            return ("OK", [(b"1 (BODY[])", raw)])
        return ("NO", [b""])

    def logout(self):
        self.logged_out = True


@pytest.fixture()
def fake_imap(monkeypatch):  # noqa: ANN201
    _FakeIMAP.login_error = None
    monkeypatch.setattr(
        "luxion.email.imap_client.imaplib",
        SimpleNamespace(IMAP4_SSL=_FakeIMAP, IMAP4=real_imaplib.IMAP4),
    )
    return _FakeIMAP


def _ctx(email: dict | None = None, *, data_dir: str | None = None) -> ToolContext:
    app = {"data_dir": data_dir} if data_dir else {}
    return ToolContext(Settings(app=app, email=email or {}))


# ---------------------------------------------------------------- MIME building
def test_build_message_sets_headers_and_appends_signature() -> None:
    message = build_message(
        to=["alex@example.com"],
        cc="carl@example.com",
        subject="Quarterly numbers",
        body="See attached.",
        from_name="Luxion",
        from_address="me@test.com",
        signature="Sent by Luxion",
    )
    assert message["From"] == "Luxion <me@test.com>"
    assert message["To"] == "alex@example.com"
    assert message["Cc"] == "carl@example.com"
    assert message["Subject"] == "Quarterly numbers"
    text = message.get_body(preferencelist=("plain",)).get_content()
    assert "See attached." in text
    assert "--\nSent by Luxion" in text


def test_build_message_rejects_header_injection() -> None:
    with pytest.raises(MailError, match="line breaks"):
        build_message(
            to=["a@b.c"],
            subject="hi\nBcc: victim@x",
            body="x",
            from_address="me@test.com",
        )
    with pytest.raises(MailError, match="line breaks"):
        build_message(
            to=["a@b.c\r\nBcc: victim@x"],
            subject="s",
            body="x",
            from_address="me@test.com",
        )


def test_build_message_validates_recipients_and_sender() -> None:
    with pytest.raises(MailError, match="at least one recipient"):
        build_message(to=[], subject="s", body="x", from_address="me@test.com")
    with pytest.raises(MailError, match="does not look like"):
        build_message(to=["not-an-address"], subject="s", body="x", from_address="me@test.com")
    with pytest.raises(MailError, match="no sender address"):
        build_message(to=["a@b.c"], subject="s", body="x", from_address="")
    with pytest.raises(MailError, match="neither a text nor an HTML body"):
        build_message(to=["a@b.c"], subject="s", body="", from_address="me@test.com")


def test_build_message_adds_html_alternative_and_keeps_bcc_out_of_the_wire() -> None:
    message = build_message(
        to=["a@b.c"],
        subject="s",
        body="plain version",
        html="<p>rich version</p>",
        from_address="me@test.com",
        bcc=["secret@x"],
    )
    assert message.get_body(preferencelist=("html",)).get_content().strip() == "<p>rich version</p>"
    assert message["Bcc"] == "secret@x"  # needed for addressing…
    # …rendered previews never show it, and smtplib strips it from the wire.
    assert "secret" not in render_preview(message)


def test_attachments_are_typed_sized_and_found(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    report = tmp_path / "report.txt"
    report.write_text("numbers", encoding="utf-8")
    message = build_message(
        to=["a@b.c"],
        subject="s",
        body="x",
        from_address="me@test.com",
        attachments=[str(report)],
    )
    parts = list(message.iter_attachments())
    assert [p.get_filename() for p in parts] == ["report.txt"]
    assert parts[0].get_content_type() == "text/plain"

    with pytest.raises(MailError, match="attachment not found"):
        build_message(
            to=["a@b.c"],
            subject="s",
            body="x",
            from_address="me@test.com",
            attachments=[str(tmp_path / "missing.pdf")],
        )

    monkeypatch.setattr("luxion.email.message.MAX_ATTACHMENT_BYTES", 2)
    with pytest.raises(MailError, match="per-file limit"):
        build_message(
            to=["a@b.c"],
            subject="s",
            body="x",
            from_address="me@test.com",
            attachments=[str(report)],
        )


def test_render_preview_shows_headers_body_and_attachments(tmp_path) -> None:  # noqa: ANN001
    note = tmp_path / "note.txt"
    note.write_text("hi", encoding="utf-8")
    preview = render_preview(
        build_message(
            to=["a@b.c"],
            subject="Preview me",
            body="body line",
            from_address="me@test.com",
            attachments=[str(note)],
        )
    )
    assert "Subject: Preview me" in preview
    assert "body line" in preview
    assert "note.txt" in preview


# ------------------------------------------------------------------ draft store
def test_draft_round_trip(tmp_path) -> None:  # noqa: ANN001
    draft = create_draft(
        tmp_path,
        {
            "to": ["a@b.c"],
            "subject": "Drafting",
            "body": "First pass.",
            "attachments": [],
        },
    )
    assert len(draft.id) == 12
    loaded = load_draft(tmp_path, draft.id)
    assert loaded.subject == "Drafting"
    assert draft.preview().count("First pass.") == 1
    assert [d.id for d in list_drafts(tmp_path)] == [draft.id]

    assert delete_draft(tmp_path, draft.id) is True
    assert delete_draft(tmp_path, draft.id) is False
    assert list_drafts(tmp_path) == []


def test_draft_rejects_path_like_ids(tmp_path) -> None:  # noqa: ANN001
    create_draft(tmp_path, {"to": ["a@b.c"], "subject": "x", "body": "y"})
    with pytest.raises(MailError, match="invalid draft id"):
        load_draft(tmp_path, "../../etc/passwd")


def test_corrupt_draft_is_skipped_not_fatal(tmp_path) -> None:  # noqa: ANN001
    good = create_draft(tmp_path, {"to": ["a@b.c"], "subject": "ok", "body": "b"})
    (tmp_path / "email_drafts" / "broken.json").write_text("{not json", encoding="utf-8")
    assert [d.id for d in list_drafts(tmp_path)] == [good.id]


# --------------------------------------------------------------------- SMTP/IMAP
def test_password_prefers_the_named_env_var(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("LUXION_TEST_SMTP_PASS", "from-env")
    config = EmailConfig(smtp_password="inline", smtp_password_env="LUXION_TEST_SMTP_PASS")
    assert resolve_password(config) == "from-env"
    monkeypatch.delenv("LUXION_TEST_SMTP_PASS")
    assert resolve_password(config) == ""  # named env wins even when empty…
    assert resolve_password(EmailConfig(smtp_password="inline")) == "inline"


def test_configured_gates() -> None:
    off = EmailConfig()
    assert is_smtp_configured(off) is False
    assert is_imap_configured(off) is False
    on = EmailConfig(**SMTP_CONFIG, imap_host="imap.test")
    assert is_smtp_configured(on) is True
    assert is_imap_configured(on) is True


def test_send_message_ssl_flow_and_receipt(fake_smtp) -> None:
    config = EmailConfig(**SMTP_CONFIG, smtp_security="ssl", smtp_port=465, smtp_password="pw")
    message = build_message(
        to=["alex@example.com"], subject="Hi", body="body", from_address="me@test.com"
    )
    receipt = send_message(config, message)
    assert receipt["sent"] is True
    assert receipt["to"] == ["alex@example.com"]
    assert receipt["subject"] == "Hi"
    assert fake_smtp.last.port == 465
    assert fake_smtp.ssl is True  # SMTP_SSL — no STARTTLS upgrade
    assert fake_smtp.last.sent, "the message must reach send_message"
    assert fake_smtp.last.calls[-1] == ("quit",)


def test_send_message_starttls_upgrades_and_logs_in(fake_smtp) -> None:
    config = EmailConfig(**SMTP_CONFIG, smtp_security="starttls", smtp_password="pw")
    message = build_message(
        to=["alex@example.com"], subject="Hi", body="body", from_address="me@test.com"
    )
    send_message(config, message)
    calls = [c[0] for c in fake_smtp.last.calls]
    assert calls.index("starttls") < calls.index("login")
    assert ("login", "me@test.com", "pw") in fake_smtp.last.calls
    assert fake_smtp.ssl is False


def test_send_message_maps_auth_failure_to_app_password_hint(fake_smtp) -> None:
    fake_smtp.login_error = real_smtplib.SMTPAuthenticationError(535, b"bad")
    config = EmailConfig(**SMTP_CONFIG, smtp_password="pw")
    message = build_message(to=["a@b.c"], subject="s", body="b", from_address="me@test.com")
    with pytest.raises(MailError, match="app password"):
        send_message(config, message)


def test_send_message_maps_refused_recipients(fake_smtp) -> None:
    fake_smtp.recipients_refused = True
    config = EmailConfig(**SMTP_CONFIG, smtp_password="pw")
    message = build_message(to=["a@b.c"], subject="s", body="b", from_address="me@test.com")
    with pytest.raises(MailError, match="refused every recipient"):
        send_message(config, message)


def test_send_message_requires_a_password(fake_smtp) -> None:
    config = EmailConfig(**SMTP_CONFIG, smtp_username="me@test.com")
    message = build_message(to=["a@b.c"], subject="s", body="b", from_address="me@test.com")
    with pytest.raises(MailError, match="no SMTP password"):
        send_message(config, message)


def test_send_message_delivers_bcc_recipients(fake_smtp) -> None:
    config = EmailConfig(**SMTP_CONFIG, smtp_password="pw")
    message = build_message(
        to=["a@b.c"], subject="s", body="b", from_address="me@test.com", bcc=["blind@x"]
    )
    send_message(config, message)
    _, from_addr, to_addrs = fake_smtp.last.sent[0]
    assert from_addr == "me@test.com"
    assert set(to_addrs) == {"a@b.c", "blind@x"}


def test_imap_read_inbox_parses_and_filters(fake_imap) -> None:
    from luxion.email.imap_client import read_inbox

    config = EmailConfig(**SMTP_CONFIG, imap_host="imap.test", smtp_password="pw")
    rows = read_inbox(config, limit=5)
    assert len(rows) == 2
    # Newest first (uid 101 was fetched after 100, reversed() puts it first).
    assert rows[0]["subject"] == "Lunch?"
    assert rows[0]["from"] == "Bob <bob@example.com>"
    assert rows[1]["subject"] == "Hello world"  # RFC 2047 decoded
    assert "quarterly numbers" in rows[1]["preview"]

    filtered = read_inbox(config, limit=5, query="lunch")
    assert [r["subject"] for r in filtered] == ["Lunch?"]
    assert read_inbox(config, limit=5, query="zzz") == []


def test_imap_requires_host_and_maps_login_failure(fake_imap) -> None:
    from luxion.email.imap_client import probe_imap, read_inbox

    with pytest.raises(MailError, match="no IMAP server configured"):
        read_inbox(EmailConfig(**SMTP_CONFIG))

    fake_imap.login_error = real_imaplib.IMAP4.error
    with pytest.raises(MailError, match="app password"):
        probe_imap(EmailConfig(**SMTP_CONFIG, imap_host="imap.test", smtp_password="pw"))


def test_probes_report_success(fake_smtp, fake_imap) -> None:
    from luxion.email.imap_client import probe_imap
    from luxion.email.smtp_send import probe_smtp

    config = EmailConfig(**SMTP_CONFIG, imap_host="imap.test", smtp_password="pw")
    assert probe_smtp(config).startswith("ok")
    assert probe_imap(config) == "ok (2 messages)"


# ------------------------------------------------------------------------ tools
def test_all_four_tools_registered_with_expected_risk() -> None:
    registry = build_registry(Settings())
    expectations = {
        "email_draft": ("medium", False),
        "email_send": ("high", False),
        "email_send_draft": ("high", False),
        "email_read": ("medium", True),
    }
    for name, (risk, read_only) in expectations.items():
        spec = registry.spec(name)
        assert spec.risk == risk, name
        assert spec.read_only is read_only, name
        assert spec.category == CATEGORY, name
        assert spec.requires is None, name  # gated by config, not a capability


def test_every_email_tool_refuses_when_disabled() -> None:
    ctx = _ctx({"enabled": False})
    cases = [
        (EmailDraft(), {"to": ["a@b.c"], "subject": "s", "body": "b"}),
        (EmailSend(), {"to": ["a@b.c"], "subject": "s", "body": "b"}),
        (EmailSendDraft(), {"draft_id": "abc"}),
        (EmailRead(), {}),
    ]
    for tool, args in cases:
        with pytest.raises(ToolError, match="email is disabled"):
            run(tool.run(args, ctx))


def test_draft_refuses_without_a_sender() -> None:
    ctx = _ctx({"enabled": True})
    with pytest.raises(ToolError, match="no sender configured"):
        run(
            EmailDraft().run(
                {"to": ["a@b.c"], "subject": "s", "body": "b"},
                ctx,
            )
        )


def test_email_draft_persists_and_previews(tmp_path) -> None:  # noqa: ANN001
    ctx = _ctx(SMTP_CONFIG, data_dir=str(tmp_path))
    result = run(
        EmailDraft().run(
            {
                "to": ["alex@example.com"],
                "subject": "Numbers attached",
                "body": "Hi Alex,\n\nAll good.",
                "attachments": [],
            },
            ctx,
        )
    )
    assert result.ok
    assert "draft saved (nothing sent yet)" in result.output
    assert "Numbers attached" in result.output
    assert result.data["draft"]["to"] == ["alex@example.com"]
    assert len(list_drafts(tmp_path)) == 1


def test_email_draft_validates_before_persisting(tmp_path) -> None:  # noqa: ANN001
    ctx = _ctx(SMTP_CONFIG, data_dir=str(tmp_path))
    with pytest.raises(ToolError, match="line breaks"):
        run(
            EmailDraft().run(
                {"to": ["a@b.c"], "subject": "s\nBcc: x", "body": "b"},
                ctx,
            )
        )
    assert list_drafts(tmp_path) == []


def test_email_send_reports_a_receipt(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    captured = {}

    def fake_send(config, message):  # noqa: ANN001, ANN201
        captured["config"] = config
        captured["message"] = message
        return {
            "sent": True,
            "message_id": "<1@x>",
            "to": ["alex@example.com"],
            "subject": message["Subject"],
            "size_bytes": 512,
            "refused": {},
        }

    monkeypatch.setattr("luxion.tools.builtin.email_tools.send_message", fake_send)
    result = run(
        EmailSend().run(
            {"to": ["alex@example.com"], "subject": "Hi", "body": "body"},
            _ctx(SMTP_CONFIG, data_dir=str(tmp_path)),
        )
    )
    assert "email sent to alex@example.com" in result.output
    assert result.data["receipt"]["size_bytes"] == 512
    assert isinstance(captured["message"], EmailMessage)


def test_email_send_draft_sends_then_deletes(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    draft = create_draft(
        tmp_path,
        {"to": ["a@b.c"], "subject": "Approved", "body": "final text"},
    )
    sent = {}

    def fake_send(config, message):  # noqa: ANN001, ANN201
        sent["subject"] = message["Subject"]
        return {
            "sent": True,
            "message_id": "",
            "to": ["a@b.c"],
            "subject": message["Subject"],
            "size_bytes": 10,
            "refused": {},
        }

    monkeypatch.setattr("luxion.tools.builtin.email_tools.send_message", fake_send)
    result = run(
        EmailSendDraft().run(
            {"draft_id": draft.id},
            _ctx(SMTP_CONFIG, data_dir=str(tmp_path)),
        )
    )
    assert sent["subject"] == "Approved"
    assert f"draft {draft.id} sent" in result.output
    assert list_drafts(tmp_path) == []


def test_email_send_draft_unknown_id_is_honest(tmp_path) -> None:  # noqa: ANN001
    ctx = _ctx(SMTP_CONFIG, data_dir=str(tmp_path))
    with pytest.raises(ToolError, match="no draft with id"):
        run(EmailSendDraft().run({"draft_id": "deadbeefdead"}, ctx))


def test_email_read_formats_messages(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(
        "luxion.tools.builtin.email_tools.read_inbox",
        lambda config, *, limit, query: [
            {
                "uid": "1",
                "from": "Alice <alice@example.com>",
                "to": "me@test.com",
                "subject": "Hello",
                "date": "Mon, 19 Oct 2026",
                "preview": "numbers attached",
            }
        ],
    )
    result = run(EmailRead().run({"limit": 3}, _ctx(SMTP_CONFIG, data_dir=str(tmp_path))))
    assert "1 inbox message(s)" in result.output
    assert "Alice <alice@example.com>" in result.output
    assert result.data["messages"][0]["subject"] == "Hello"


def test_email_read_empty_is_an_honest_failure(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(
        "luxion.tools.builtin.email_tools.read_inbox",
        lambda config, *, limit, query: [],
    )
    result = run(EmailRead().run({}, _ctx(SMTP_CONFIG, data_dir=str(tmp_path))))
    assert result.ok is False
    assert result.error == "no results"


# --------------------------------------------------------------------------- API
def test_config_read_hides_the_secret_and_reports_readiness(clean_email: TestClient) -> None:
    bundle = clean_email.get("/api/email").json()
    assert set(bundle) == {"config", "defaults", "status", "drafts"}
    assert "smtp_password" not in bundle["config"]
    assert "smtp_password" not in bundle["defaults"]
    assert "smtp_password" not in bundle["status"]
    assert bundle["defaults"]["smtp_host"] == ""
    status = bundle["status"]
    assert set(status) == {
        "enabled",
        "smtp_configured",
        "imap_configured",
        "password_configured",
        "password_env",
        "from_address",
    }
    assert status["smtp_configured"] is False


def test_config_patch_mirrors_every_writable_knob() -> None:
    from luxion.api.routes.email import EmailConfigPatch

    assert set(EmailConfigPatch.model_fields) == set(EmailConfig.model_fields) - EMAIL_SECRET_FIELDS


def test_overlay_and_settings_secret_sets_agree() -> None:
    assert set(EMAIL_SECRET_FIELDS) == set(email_override.SECRET_FIELDS)


def test_put_merges_into_email_json_and_survives_reload(clean_email: TestClient) -> None:
    first = clean_email.put(
        "/api/email/config",
        json={
            "enabled": True,
            "smtp_host": "smtp.gmail.com",
            "from_address": "me@test.com",
            "read_limit": 5,
        },
    ).json()
    assert first["config"]["smtp_host"] == "smtp.gmail.com"
    assert first["status"]["smtp_configured"] is True

    reset_settings_cache()
    assert get_settings().email.smtp_host == "smtp.gmail.com"
    assert get_settings().email.read_limit == 5

    clean_email.put("/api/email/config", json={"from_name": "Harsh"})
    reset_settings_cache()
    again = get_settings().email
    assert again.from_name == "Harsh"
    assert again.smtp_host == "smtp.gmail.com"  # earlier edit survives


def test_put_cannot_write_a_password(clean_email: TestClient) -> None:
    response = clean_email.put("/api/email/config", json={"smtp_password": "s3cret"})
    assert response.status_code == 422  # extra=forbid — no password field exists

    # A hand-edited overlay carrying the key is stripped on load.
    email_override.save_overrides(
        get_settings().app.data_dir, {"smtp_password": "leaked", "smtp_host": "smtp.x"}
    )
    reset_settings_cache()
    assert get_settings().email.smtp_password == ""
    assert get_settings().email.smtp_host == "smtp.x"
    on_disk = json.loads((get_settings().app.data_dir / "email.json").read_text(encoding="utf-8"))
    assert "smtp_password" not in on_disk  # validator dropped it before the merge


def test_put_rejects_unknown_keys_but_ignores_bad_values(clean_email: TestClient) -> None:
    assert clean_email.put("/api/email/config", json={"nonsense": 1}).status_code == 422
    clean_email.put("/api/email/config", json={"smtp_port": 99999})
    reset_settings_cache()
    assert get_settings().email.smtp_port == EmailConfig().smtp_port


def test_delete_drops_the_overlay(clean_email: TestClient) -> None:
    clean_email.put("/api/email/config", json={"enabled": True})
    reset_settings_cache()
    assert get_settings().email.enabled is True

    clean_email.delete("/api/email/config")
    reset_settings_cache()
    assert get_settings().email.enabled == EmailConfig().enabled
    assert not email_override.email_path(get_settings().app.data_dir).exists()


def test_probe_skips_and_reports_per_leg(clean_email: TestClient, monkeypatch) -> None:  # noqa: ANN001
    # Disabled → everything skipped without touching the network.
    results = clean_email.post("/api/email/probe").json()["results"]
    assert results["smtp"] == "skipped: email is disabled"
    assert results["imap"] == "skipped: email is disabled"

    # Patch the probes *before* enabling — no socket may open during the run.
    monkeypatch.setattr("luxion.api.routes.email.probe_smtp", lambda cfg: "ok (STARTTLS offered)")
    monkeypatch.setattr("luxion.api.routes.email.probe_imap", lambda cfg: "ok (42 messages)")

    clean_email.put("/api/email/config", json={"enabled": True, "smtp_host": "smtp.test"})
    results = clean_email.post("/api/email/probe").json()["results"]
    assert results["smtp"] == "ok (STARTTLS offered)"
    assert results["imap"] == "skipped: no IMAP host configured"

    clean_email.put("/api/email/config", json={"imap_host": "imap.test"})
    results = clean_email.post("/api/email/probe").json()["results"]
    assert results["imap"] == "ok (42 messages)"


def test_probe_reports_errors_as_text(clean_email: TestClient, monkeypatch) -> None:  # noqa: ANN001
    clean_email.put("/api/email/config", json={"enabled": True, "smtp_host": "smtp.test"})

    def boom(cfg):  # noqa: ANN001, ANN201
        raise MailError("could not reach the SMTP server smtp.test:587")

    monkeypatch.setattr("luxion.api.routes.email.probe_smtp", boom)
    results = clean_email.post("/api/email/probe").json()["results"]
    assert results["smtp"].startswith("error: could not reach")


def test_draft_endpoints_list_and_delete(clean_email: TestClient) -> None:
    data_dir = get_settings().app.data_dir
    draft = create_draft(data_dir, {"to": ["a@b.c"], "subject": "Mine", "body": "b"})

    listed = [d["id"] for d in clean_email.get("/api/email/drafts").json()]
    assert draft.id in listed

    assert clean_email.delete(f"/api/email/drafts/{draft.id}").status_code == 200
    assert draft.id not in [d["id"] for d in clean_email.get("/api/email/drafts").json()]
    assert clean_email.delete(f"/api/email/drafts/{draft.id}").status_code == 404
    assert delete_draft(data_dir, "nope") is False

import json
import logging

from luxion.logging_setup import JsonFormatter, RedactionFilter, get_logger, redact


def _record(msg: str, **extra: object) -> logging.LogRecord:
    record = logging.LogRecord("test", logging.INFO, __file__, 1, msg, (), None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_redact_masks_api_keys() -> None:
    assert "***REDACTED***" in redact("using key sk-abc123def456ghi789")
    assert "hello" not in redact("password=hello world").split("***REDACTED***")[1]


def test_redact_masks_bearer_tokens() -> None:
    out = redact("Authorization: Bearer abcdefghijklmnop")
    assert "abcdefghijklmnop" not in out


def test_filter_scrubs_sensitive_extras() -> None:
    record = _record("calling provider", api_key="sk-secret12345", tool="read_file")
    assert RedactionFilter().filter(record) is True
    assert record.api_key == "***REDACTED***"
    assert record.tool == "read_file"


def test_filter_scrubs_message_text() -> None:
    record = _record("token=abcdef1234567890")
    RedactionFilter().filter(record)
    assert "abcdef1234567890" not in record.msg


def test_json_formatter_outputs_valid_json_with_extras() -> None:
    record = _record("hello", tool="system_stats", duration_ms=12.5)
    RedactionFilter().filter(record)
    payload = json.loads(JsonFormatter().format(record))
    assert payload["msg"] == "hello"
    assert payload["level"] == "INFO"
    assert payload["tool"] == "system_stats"
    assert payload["duration_ms"] == 12.5
    assert "ts" in payload


def test_get_logger_returns_named_logger() -> None:
    logger = get_logger("luxion.agent")
    assert logger.name == "luxion.agent"

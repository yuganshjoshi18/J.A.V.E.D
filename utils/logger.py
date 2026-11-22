"""Logging setup with rotation and defensive secret redaction.

No API key should ever reach the source of a log call, but the filter is a
second line of defence: retrieved documents and third-party error messages can
contain credential-shaped strings.
"""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler

from utils.paths import AppPaths

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 3

# Google API keys ("AIza..."), OpenAI-style keys, Bearer tokens, and long
# opaque query parameters. Kept deliberately conservative to avoid mangling
# ordinary log messages.
_SECRET_PATTERNS = (
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"\bsk-[0-9A-Za-z_\-]{16,}\b"),
    re.compile(r"(?i)(bearer\s+)[0-9A-Za-z._\-]{16,}"),
    re.compile(r"(?i)((?:api[_-]?key|token|secret|password)=)[^\s&]+"),
)

_configured = False


def redact_text(text: str) -> str:
    """Return text with credential-shaped substrings removed."""
    redacted = text
    for pattern in _SECRET_PATTERNS:
        if pattern.groups:
            redacted = pattern.sub(lambda match: f"{match.group(1)}[REDACTED]", redacted)
        else:
            redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = record.getMessage()
        except Exception:  # pragma: no cover - malformed logging call
            return True
        safe = redact_text(rendered)
        if safe != rendered:
            record.msg = safe
            record.args = ()
        if record.exc_info:
            # Let the formatter render the traceback, then redact it below.
            formatter = logging.Formatter()
            exception_text = formatter.formatException(record.exc_info)
            safe_exception = redact_text(exception_text)
            if safe_exception != exception_text:
                record.exc_text = safe_exception
        return True


def configure_logging(paths: AppPaths, level: str = "INFO") -> None:
    """Install console + rotating-file handlers exactly once per process."""
    global _configured
    if _configured:
        return

    paths.logs_dir.mkdir(parents=True, exist_ok=True)
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(numeric_level)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)
    redactor = RedactionFilter()

    file_handler = RotatingFileHandler(
        paths.log_file,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(redactor)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.addFilter(redactor)

    root.addHandler(file_handler)
    root.addHandler(console)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"javed.{name}")

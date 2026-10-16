"""Typed failures and shared validation for the read-only demonstration adapters."""

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit


class AdapterError(Exception):
    def __init__(self, kind, code, message, retry_after=None):
        super().__init__(message)
        self.kind = kind
        self.code = code
        self.message = message
        self.retry_after = retry_after


def identifier(data):
    value = str(data.get("identifier", "")).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise AdapterError(
            "invalid",
            "invalid_identifier",
            "Identifier must contain 1–64 letters, digits, underscores or hyphens.",
        )
    return value


def source_base():
    from app.config import settings

    base = settings.demo_base_url.rstrip("/")
    parsed = urlsplit(base)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path
    ):
        raise AdapterError(
            "blocked",
            "source_configuration",
            "Demo source must be an HTTP origin configured by the operator.",
        )
    return base


def retry_after_seconds(value):
    if not value:
        return None
    try:
        return min(3600, max(0, float(value)))
    except ValueError:
        try:
            return min(
                3600,
                max(0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()),
            )
        except (ValueError, TypeError, OverflowError):
            return None


def check_response(status, retry_after=None):
    if status == 404:
        raise AdapterError("missing", "not_found", "The identifier was not found.")
    if status in {401, 403}:
        kind = "login_required" if status == 401 else "blocked"
        raise AdapterError(
            kind,
            kind,
            "The source requires authorization."
            if status == 401
            else "The source blocked this request.",
        )
    if status == 429 or status >= 500:
        raise AdapterError(
            "transient",
            "rate_limited" if status == 429 else "source_unavailable",
            "The source is temporarily unavailable.",
            retry_after_seconds(retry_after),
        )
    if 300 <= status < 400:
        raise AdapterError("blocked", "redirect_blocked", "Source redirects are disabled.")
    if status >= 400:
        raise AdapterError("permanent", "source_rejected", "The source rejected this request.")

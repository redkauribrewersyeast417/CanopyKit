"""Deterministic secret redaction for structured data.

Operates only on dict/list/JSON-compatible objects and known sensitive key
names.  Does not apply regex over free-form text; safe to call on any
machine-generated evidence or status payload before it is emitted.
"""

from __future__ import annotations

from typing import Any

REDACTED_PLACEHOLDER = "[REDACTED]"

# Substrings that, when found anywhere in a lowercased key name, cause the
# corresponding value to be replaced with REDACTED_PLACEHOLDER.
_SENSITIVE_KEY_SUBSTRINGS: frozenset[str] = frozenset(
    {
        "api_key",
        "apikey",
        "token",
        "secret",
        "password",
        "passwd",
        "authorization",
        "bearer",
        "access_key",
        "refresh_token",
    }
)


def _is_sensitive_key(key: str) -> bool:
    """Return True if *key* matches any known-sensitive substring."""
    lower = key.lower()
    return any(pattern in lower for pattern in _SENSITIVE_KEY_SUBSTRINGS)


def redact_secrets(obj: Any) -> Any:
    """Recursively redact sensitive values in a structured object.

    * dict  – values whose key matches a sensitive pattern are replaced with
              ``REDACTED_PLACEHOLDER``; other values are recursed into.
    * list  – every element is recursed into.
    * other – returned unchanged (strings, numbers, booleans, None, …).

    The original object is never mutated; a new structure is returned.
    """
    if isinstance(obj, dict):
        return {
            k: REDACTED_PLACEHOLDER if _is_sensitive_key(str(k)) else redact_secrets(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact_secrets(item) for item in obj]
    return obj

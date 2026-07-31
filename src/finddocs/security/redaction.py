"""Redakcja danych wrazliwych przed zapisem do logow i raportow.

Zasada: do logow trafiaja fakty o przetwarzaniu (identyfikator, etap, kod bledu,
czas, rozmiar), a nie tresc. Ten modul jest ostatnia linia obrony: nawet jesli
ktos przekaze do loggera token albo fragment dokumentu, zostanie on zamaskowany.
"""

from __future__ import annotations

import re
from typing import Any

REDACTED = "[usunieto]"

#: Klucze, ktorych wartosci nigdy nie trafiaja do logow.
SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "access_token",
        "refresh_token",
        "id_token",
        "authorization",
        "auth",
        "password",
        "passwd",
        "secret",
        "client_secret",
        "api_key",
        "apikey",
        "token",
        "credential",
        "credentials",
        "cookie",
        "set-cookie",
        "x-api-key",
        "proxy-authorization",
        "content",
        "text",
        "body",
        "snippet",
        "chunk_text",
        "document_text",
        "full_text",
        "query",
        "query_text",
        "search_query",
        "embedding",
        "vector",
    }
)

#: Klucze, przy ktorych zamiast wartosci logujemy sama dlugosc.
LENGTH_ONLY_KEYS: frozenset[str] = frozenset(
    {"content", "text", "body", "snippet", "chunk_text", "document_text", "full_text"}
)

_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-+/=]{8,}")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b")
_KEYVALUE_RE = re.compile(
    r"(?i)\b(access_token|refresh_token|id_token|client_secret|password|api[_-]?key|token)"
    r"\s*[=:]\s*[\"']?([^\s\"',;&]{4,})"
)
_LONG_HEX_RE = re.compile(r"\b[A-Fa-f0-9]{40,}\b")

MAX_VALUE_CHARS = 200


def redact_text(value: str) -> str:
    """Maskuje wzorce sekretow w dowolnym tekscie."""
    out = _BEARER_RE.sub(f"Bearer {REDACTED}", value)
    out = _JWT_RE.sub(REDACTED, out)
    out = _KEYVALUE_RE.sub(lambda m: f"{m.group(1)}={REDACTED}", out)
    out = _LONG_HEX_RE.sub(REDACTED, out)
    if len(out) > MAX_VALUE_CHARS:
        out = out[:MAX_VALUE_CHARS] + f"...[+{len(out) - MAX_VALUE_CHARS} znakow]"
    return out


def redact_value(key: str, value: Any, *, depth: int = 0) -> Any:
    """Zwraca bezpieczna reprezentacje wartosci dla podanego klucza."""
    lowered = key.lower()
    if lowered in LENGTH_ONLY_KEYS:
        try:
            return f"<{len(value)} znakow>"
        except TypeError:
            return REDACTED
    if lowered in SENSITIVE_KEYS:
        return REDACTED
    if depth > 4:
        return REDACTED
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {k: redact_value(str(k), v, depth=depth + 1) for k, v in value.items()}
    if isinstance(value, list | tuple):
        limited = list(value)[:20]
        return [redact_value(key, v, depth=depth + 1) for v in limited]
    if isinstance(value, int | float | bool) or value is None:
        return value
    return redact_text(str(value))


def redact_mapping(data: dict[str, Any]) -> dict[str, Any]:
    """Redaguje caly slownik zdarzenia logu."""
    return {k: redact_value(str(k), v) for k, v in data.items()}


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    """Redaguje naglowki HTTP przed zapisem do diagnostyki."""
    safe: dict[str, str] = {}
    for key, value in headers.items():
        safe[key] = REDACTED if key.lower() in SENSITIVE_KEYS else redact_text(value)
    return safe


def safe_url(url: str) -> str:
    """Usuwa czesc zapytania z adresu URL (moze zawierac tokeny SAS)."""
    without_fragment = url.split("#", 1)[0]
    base, sep, _query = without_fragment.partition("?")
    return base + ("?[parametry usuniete]" if sep else "")


__all__ = [
    "LENGTH_ONLY_KEYS",
    "REDACTED",
    "SENSITIVE_KEYS",
    "redact_headers",
    "redact_mapping",
    "redact_text",
    "redact_value",
    "safe_url",
]

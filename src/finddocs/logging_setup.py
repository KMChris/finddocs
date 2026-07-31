"""Konfiguracja strukturalnego logowania z wbudowana redakcja.

Logi ida do pliku w katalogu danych uzytkownika (rotacja rozmiarowa) oraz,
przy uruchomieniu z konsoli, na stderr. Zadne zdarzenie nie opuszcza komputera.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

import structlog

from finddocs.security.redaction import redact_mapping
from finddocs.version import APP_VERSION

_configured = False
#: True, gdy logowanie ustawil samoczynnie ``get_logger``, a nie jawne wywolanie.
#: Taka konfiguracja nie ma pliku logu, wiec pierwsze jawne wywolanie musi ja zastapic.
_configured_implicitly = False


def _redaction_processor(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Procesor structlog usuwajacy dane wrazliwe z kazdego zdarzenia."""
    return redact_mapping(dict(event_dict))


def _add_app_version(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    event_dict.setdefault("app_version", APP_VERSION)
    return event_dict


def configure_logging(
    *,
    log_file: Path | None = None,
    level: str = "INFO",
    json_output: bool = True,
    console: bool = False,
    max_bytes: int = 20 * 1024 * 1024,
    backup_count: int = 5,
    force: bool = False,
    _implicit: bool = False,
) -> None:
    """Ustawia logowanie aplikacji. Wywolanie wielokrotne jest bezpieczne.

    Moduly tworza loggery przy imporcie, wiec ``get_logger`` czesto ustawia
    logowanie zanim aplikacja pozna sciezke pliku logu. Taka konfiguracja jest
    tymczasowa: pierwsze jawne wywolanie ja zastepuje i dopina plik.
    """
    global _configured, _configured_implicitly
    if _configured and not force and not (_configured_implicitly and not _implicit):
        return

    numeric_level = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.setLevel(numeric_level)

    plain = logging.Formatter("%(message)s")

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(plain)
        file_handler.setLevel(numeric_level)
        root.addHandler(file_handler)

    if console:
        stream = logging.StreamHandler(stream=sys.stderr)
        stream.setFormatter(plain)
        stream.setLevel(numeric_level)
        root.addHandler(stream)

    if not root.handlers:
        root.addHandler(logging.NullHandler())

    renderer: Any = (
        structlog.processors.JSONRenderer(ensure_ascii=False)
        if json_output
        else structlog.dev.ConsoleRenderer(colors=False)
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso", utc=False),
            _add_app_version,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            _redaction_processor,
            renderer,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _configured = True
    _configured_implicitly = _implicit


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Zwraca logger o podanej nazwie. Konfiguruje logowanie, jesli trzeba."""
    if not _configured:
        configure_logging(log_file=None, console=False, _implicit=True)
    return structlog.get_logger(name)  # type: ignore[no-any-return]


def bind_context(**kwargs: Any) -> None:
    """Dopina kontekst do wszystkich kolejnych zdarzen w tym watku."""
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_context() -> None:
    structlog.contextvars.clear_contextvars()


__all__ = ["bind_context", "clear_context", "configure_logging", "get_logger"]

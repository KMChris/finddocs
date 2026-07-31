"""Bezpieczenstwo: poswiadczenia, redakcja logow, kontrola ruchu sieciowego.

Eksporty sa leniwe. ``finddocs.logging_setup`` importuje ``security.redaction``,
a ``security.credentials`` importuje logger, wiec zachlanne importy w tym pliku
tworzylyby cykl.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - tylko dla kontroli typow
    from finddocs.security.credentials import CredentialStore, create_credential_store
    from finddocs.security.network import (
        EgressCategory,
        NetworkPolicy,
        get_policy,
        set_policy,
    )
    from finddocs.security.redaction import redact_mapping, redact_text, safe_url

_LAZY: dict[str, str] = {
    "CredentialStore": "finddocs.security.credentials",
    "create_credential_store": "finddocs.security.credentials",
    "EgressCategory": "finddocs.security.network",
    "NetworkPolicy": "finddocs.security.network",
    "get_policy": "finddocs.security.network",
    "set_policy": "finddocs.security.network",
    "redact_mapping": "finddocs.security.redaction",
    "redact_text": "finddocs.security.redaction",
    "safe_url": "finddocs.security.redaction",
}


def __getattr__(name: str) -> Any:
    module_name = _LAZY.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(module_name), name)


def __dir__() -> list[str]:
    return sorted(_LAZY)


__all__ = [
    "CredentialStore",
    "EgressCategory",
    "NetworkPolicy",
    "create_credential_store",
    "get_policy",
    "redact_mapping",
    "redact_text",
    "safe_url",
    "set_policy",
]

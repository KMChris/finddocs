"""Bezpieczne przechowywanie poswiadczen i tokenow.

Kolejnosc preferencji na Windows:

1. Windows Credential Manager przez biblioteke ``keyring``.
2. DPAPI (``CryptProtectData``) z zapisem zaszyfrowanego pliku w katalogu danych.
3. Pamiec procesu, gdy dwa poprzednie mechanizmy sa niedostepne.

Zaden z mechanizmow nie zapisuje sekretu jawnym tekstem na dysku. Trzeci wariant
istnieje po to, zeby aplikacja dzialala w srodowisku testowym bez magazynu systemowego,
i jawnie informuje o braku trwalosci.
"""

from __future__ import annotations

import base64
import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Final

from finddocs.errors import CredentialStoreError
from finddocs.logging_setup import get_logger

log = get_logger(__name__)

SERVICE_NAME: Final = "FindDocs"


class CredentialStore(ABC):
    """Interfejs magazynu sekretow."""

    name: str = "abstract"
    persistent: bool = False

    @abstractmethod
    def set_secret(self, key: str, value: str) -> None: ...

    @abstractmethod
    def get_secret(self, key: str) -> str | None: ...

    @abstractmethod
    def delete_secret(self, key: str) -> None: ...

    def set_json(self, key: str, value: dict[str, Any]) -> None:
        self.set_secret(key, json.dumps(value, ensure_ascii=False))

    def get_json(self, key: str) -> dict[str, Any] | None:
        raw = self.get_secret(key)
        if raw is None:
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("credentials.corrupted_entry", key=key)
            return None
        return parsed if isinstance(parsed, dict) else None


class KeyringCredentialStore(CredentialStore):
    """Windows Credential Manager przez ``keyring``."""

    name = "windows_credential_manager"
    persistent = True

    def __init__(self, service: str = SERVICE_NAME) -> None:
        import keyring
        from keyring.errors import KeyringError

        backend = keyring.get_keyring()
        backend_name = type(backend).__name__
        if "fail" in backend_name.lower():
            raise CredentialStoreError("Magazyn poświadczeń systemu nie jest dostępny.")
        self._keyring = keyring
        self._error = KeyringError
        self._service = service
        self.backend_name = backend_name

    def set_secret(self, key: str, value: str) -> None:
        try:
            self._keyring.set_password(self._service, key, value)
        except self._error as exc:
            raise CredentialStoreError(
                "Nie udało się zapisać poświadczeń w Menedżerze poświadczeń Windows.",
                cause=exc,
            ) from exc

    def get_secret(self, key: str) -> str | None:
        try:
            stored: str | None = self._keyring.get_password(self._service, key)
            return stored
        except self._error as exc:
            raise CredentialStoreError(
                "Nie udało się odczytać poświadczeń z Menedżera poświadczeń Windows.",
                cause=exc,
            ) from exc

    def delete_secret(self, key: str) -> None:
        try:
            self._keyring.delete_password(self._service, key)
        except Exception:
            log.debug("credentials.delete_missing", key=key)


class DpapiCredentialStore(CredentialStore):
    """Szyfrowanie DPAPI powiazane z kontem uzytkownika Windows."""

    name = "dpapi"
    persistent = True

    def __init__(self, storage_file: Path) -> None:
        try:
            import win32crypt  # noqa: F401
        except ImportError as exc:  # pragma: no cover - tylko poza Windows
            raise CredentialStoreError(
                "DPAPI jest dostępne wyłącznie na Windows.", cause=exc
            ) from exc
        self._storage_file = storage_file
        self._storage_file.parent.mkdir(parents=True, exist_ok=True)

    def _protect(self, value: str) -> str:
        import win32crypt

        blob = win32crypt.CryptProtectData(value.encode("utf-8"), SERVICE_NAME, None, None, None, 0)
        return base64.b64encode(blob).decode("ascii")

    def _unprotect(self, value: str) -> str | None:
        import win32crypt

        try:
            raw = base64.b64decode(value.encode("ascii"))
            _desc, plain = win32crypt.CryptUnprotectData(raw, None, None, None, 0)
        except Exception:
            log.warning("credentials.dpapi_unprotect_failed")
            return None
        return plain.decode("utf-8")  # type: ignore[no-any-return]

    def _load(self) -> dict[str, str]:
        if not self._storage_file.exists():
            return {}
        try:
            data = json.loads(self._storage_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            log.warning("credentials.store_unreadable")
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict[str, str]) -> None:
        tmp = self._storage_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._storage_file)

    def set_secret(self, key: str, value: str) -> None:
        data = self._load()
        data[key] = self._protect(value)
        self._save(data)

    def get_secret(self, key: str) -> str | None:
        raw = self._load().get(key)
        return self._unprotect(raw) if raw is not None else None

    def delete_secret(self, key: str) -> None:
        data = self._load()
        if data.pop(key, None) is not None:
            self._save(data)


class MemoryCredentialStore(CredentialStore):
    """Magazyn w pamieci procesu. Sekrety gina po zamknieciu aplikacji."""

    name = "memory"
    persistent = False

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def set_secret(self, key: str, value: str) -> None:
        self._data[key] = value

    def get_secret(self, key: str) -> str | None:
        return self._data.get(key)

    def delete_secret(self, key: str) -> None:
        self._data.pop(key, None)


def create_credential_store(storage_dir: Path, *, prefer: str = "auto") -> CredentialStore:
    """Tworzy najlepszy dostepny magazyn poswiadczen.

    ``prefer`` przyjmuje: auto, keyring, dpapi, memory.
    """
    order: list[str]
    if prefer == "auto":
        order = ["keyring", "dpapi", "memory"]
    else:
        order = [prefer, "memory"]

    errors: list[str] = []
    for kind in order:
        try:
            if kind == "keyring":
                store: CredentialStore = KeyringCredentialStore()
            elif kind == "dpapi":
                store = DpapiCredentialStore(storage_dir / "credentials.dat")
            else:
                store = MemoryCredentialStore()
        except Exception as exc:
            errors.append(f"{kind}: {type(exc).__name__}")
            continue
        log.info("credentials.store_selected", store=store.name, persistent=store.persistent)
        if not store.persistent:
            log.warning("credentials.non_persistent_store", tried=errors)
        return store

    raise CredentialStoreError("Nie udało się utworzyć żadnego magazynu poświadczeń.")


def token_cache_key(source_id: str) -> str:
    """Klucz wpisu z pamiecia podreczna tokenow MSAL dla danego zrodla."""
    return f"msal-token-cache::{source_id}"


#: Nazwa wpisu z kluczem API zdalnego dostawcy embeddingow.
EMBEDDING_API_KEY_NAME: Final = "embedding-api-key"


__all__ = [
    "EMBEDDING_API_KEY_NAME",
    "SERVICE_NAME",
    "CredentialStore",
    "DpapiCredentialStore",
    "KeyringCredentialStore",
    "MemoryCredentialStore",
    "create_credential_store",
    "token_cache_key",
]

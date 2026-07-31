"""Uwierzytelnienie do Microsoft Graph oparte o biblioteke MSAL.

Modul udostepnia klase :class:`GraphAuthenticator`, ktora zdobywa tokeny dostepu
dla konta uzytkownika (przeplyw interaktywny albo kod urzadzenia) i utrzymuje
pamiec podreczna tokenow MSAL w magazynie poswiadczen z modulu
``finddocs.security.credentials``.

Zasady bezpieczenstwa:

1. Token i pamiec podreczna nigdy nie trafiaja do pliku konfiguracyjnego.
2. Zaden token, naglowek autoryzacji ani kod urzadzenia nie trafia do logow.
3. Kazdy adres uzyty do polaczenia przechodzi przez polityke sieciowa aplikacji.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any

import msal

from finddocs.config import SharePointSourceSettings
from finddocs.errors import AuthenticationError, CredentialStoreError
from finddocs.logging_setup import get_logger
from finddocs.security.credentials import CredentialStore, token_cache_key
from finddocs.security.network import EgressCategory, NetworkPolicy, get_policy
from finddocs.security.redaction import redact_text

log = get_logger(__name__)

#: Zakresy rezerwowane przez MSAL. Biblioteka dodaje je sama i odrzuca w wywolaniach.
RESERVED_SCOPES: frozenset[str] = frozenset({"openid", "profile", "offline_access"})

#: Katalog uzywany, gdy konfiguracja nie wskazuje konkretnego tenanta.
DEFAULT_TENANT = "organizations"

#: Domyslny adres uslugi logowania Microsoft Entra ID.
DEFAULT_AUTHORITY = "https://login.microsoftonline.com"

AUTH_FLOW_INTERACTIVE = "interactive"
AUTH_FLOW_DEVICE_CODE = "device_code"

#: Dozwolone wartosci pola ``auth_flow`` w ustawieniach zrodla.
SUPPORTED_AUTH_FLOWS: frozenset[str] = frozenset({AUTH_FLOW_INTERACTIVE, AUTH_FLOW_DEVICE_CODE})


class GraphAuthenticator:
    """Zdobywa i odswieza tokeny dostepu do Microsoft Graph.

    Obiekt jest zwiazany z jednym zrodlem dokumentow. Pamiec podreczna tokenow
    jest serializowana do magazynu poswiadczen pod kluczem zaleznym od
    identyfikatora zrodla, wiec kilka zrodel moze korzystac z roznych kont.
    """

    def __init__(
        self,
        settings: SharePointSourceSettings,
        credential_store: CredentialStore,
        source_id: str,
        policy: NetworkPolicy | None = None,
    ) -> None:
        self._settings = settings
        self._store = credential_store
        self._source_id = source_id
        self._policy = policy if policy is not None else get_policy()
        self._cache_key = token_cache_key(source_id)
        self._cache: Any = msal.SerializableTokenCache()
        self._app: Any = None
        self._device_code_callback: Callable[[str, str], None] | None = None
        self._load_cache()

    # --- konfiguracja -----------------------------------------------------

    @property
    def authority(self) -> str:
        """Pelny adres autorytetu, np. ``https://login.microsoftonline.com/<tenant>``."""
        base = (self._settings.authority or DEFAULT_AUTHORITY).strip().rstrip("/")
        tenant = self._settings.tenant_id.strip().strip("/") or DEFAULT_TENANT
        return f"{base}/{tenant}"

    @property
    def source_id(self) -> str:
        return self._source_id

    def set_device_code_callback(self, callback: Callable[[str, str], None] | None) -> None:
        """Ustawia funkcje pokazujaca uzytkownikowi kod urzadzenia i adres logowania.

        Callback dostaje dwa argumenty: kod uzytkownika oraz adres weryfikacji.
        Gdy nie zostanie ustawiony, kod trafia na standardowe wyjscie bledow.
        """
        self._device_code_callback = callback

    def effective_scopes(self) -> list[str]:
        """Zakresy przekazywane do MSAL, bez zakresow rezerwowanych i duplikatow."""
        seen: set[str] = set()
        scopes: list[str] = []
        for raw in self._settings.scopes:
            candidate = raw.strip()
            if not candidate or candidate.lower() in RESERVED_SCOPES:
                continue
            if candidate.lower() in seen:
                continue
            seen.add(candidate.lower())
            scopes.append(candidate)
        if not scopes:
            raise AuthenticationError(
                "Nie skonfigurowano zadnego zakresu uprawnien do Microsoft Graph. "
                "Uzupelnij pole 'scopes' w ustawieniach zrodla, na przyklad Files.Read.All."
            )
        return scopes

    # --- polityka sieciowa ------------------------------------------------

    def check_endpoints(self) -> None:
        """Sprawdza adresy logowania i Microsoft Graph wzgledem polityki sieciowej."""
        self._policy.check(self.authority, EgressCategory.MICROSOFT_GRAPH)
        endpoint = self._settings.graph_endpoint.strip()
        if endpoint:
            self._policy.check(endpoint, EgressCategory.MICROSOFT_GRAPH)

    # --- aplikacja MSAL ---------------------------------------------------

    def _application(self) -> Any:
        """Tworzy albo zwraca aplikacje MSAL. Konstruktor wykonuje zapytanie sieciowe."""
        if self._app is not None:
            return self._app
        client_id = self._settings.client_id.strip()
        if not client_id:
            raise AuthenticationError(
                "Nie skonfigurowano identyfikatora aplikacji (client_id) dla zrodla SharePoint. "
                "Uzupelnij go w ustawieniach zrodla."
            )
        self.check_endpoints()
        try:
            self._app = msal.PublicClientApplication(
                client_id,
                authority=self.authority,
                token_cache=self._cache,
            )
        except ValueError as exc:
            raise AuthenticationError(
                "Adres uslugi logowania albo identyfikator tenanta jest nieprawidlowy: "
                f"{redact_text(str(exc))}",
                cause=exc,
            ) from exc
        except Exception as exc:
            raise AuthenticationError(
                "Nie udalo sie polaczyc z usluga logowania Microsoft Entra ID. "
                "Sprawdz polaczenie z siecia firmowa oraz ustawienia serwera proxy.",
                cause=exc,
            ) from exc
        log.info("auth.application_ready", source_id=self._source_id)
        return self._app

    # --- pamiec podreczna tokenow ----------------------------------------

    def _load_cache(self) -> None:
        """Wczytuje pamiec podreczna tokenow z magazynu poswiadczen."""
        try:
            raw = self._store.get_secret(self._cache_key)
        except CredentialStoreError as exc:
            log.warning(
                "auth.cache_read_failed", source_id=self._source_id, reason=type(exc).__name__
            )
            return
        if not raw:
            return
        try:
            self._cache.deserialize(raw)
        except Exception:
            log.warning("auth.cache_corrupted", source_id=self._source_id)
            self._cache = msal.SerializableTokenCache()

    def _persist_cache(self) -> None:
        """Zapisuje pamiec podreczna, gdy MSAL zglosil zmiane stanu."""
        if not self._cache.has_state_changed:
            return
        try:
            self._store.set_secret(self._cache_key, self._cache.serialize())
        except CredentialStoreError as exc:
            log.warning(
                "auth.cache_write_failed", source_id=self._source_id, reason=type(exc).__name__
            )
        else:
            log.debug("auth.cache_saved", source_id=self._source_id, store=self._store.name)

    def _cached_accounts(self) -> list[dict[str, Any]]:
        """Konta zapisane w pamieci podrecznej. Odczyt nie wymaga sieci."""
        try:
            found = self._cache.find(msal.TokenCache.CredentialType.ACCOUNT)
        except Exception:
            log.warning("auth.cache_accounts_failed", source_id=self._source_id)
            return []
        return [entry for entry in found if isinstance(entry, dict)]

    # --- zdobywanie tokenu -----------------------------------------------

    def acquire_token_silent(self, *, force_refresh: bool = False) -> str | None:
        """Zwraca token z pamieci podrecznej albo odswieza go bez udzialu uzytkownika.

        Zwraca ``None``, gdy w pamieci nie ma konta albo odswiezenie sie nie powiodlo.
        """
        if not self._cached_accounts():
            return None
        app = self._application()
        scopes = self.effective_scopes()
        result: Any = None
        try:
            for account in app.get_accounts():
                result = app.acquire_token_silent(
                    scopes, account=account, force_refresh=force_refresh
                )
                if result:
                    break
        except Exception as exc:
            log.warning("auth.silent_failed", source_id=self._source_id, reason=type(exc).__name__)
            result = None
        finally:
            self._persist_cache()
        if not isinstance(result, dict):
            return None
        token = result.get("access_token")
        if isinstance(token, str) and token:
            log.info("auth.token_acquired", source_id=self._source_id, flow="silent")
            return token
        return None

    def acquire_token_interactive(self, timeout: int = 300) -> str:
        """Loguje uzytkownika w oknie przegladarki i zwraca token dostepu."""
        app = self._application()
        scopes = self.effective_scopes()
        log.info("auth.interactive_started", source_id=self._source_id)
        try:
            result = app.acquire_token_interactive(scopes, timeout=timeout)
        except Exception as exc:
            raise AuthenticationError(
                "Logowanie w oknie przegladarki nie powiodlo sie. "
                "Sprawdz, czy przegladarka jest dostepna i czy nie uplynal czas oczekiwania.",
                cause=exc,
            ) from exc
        finally:
            self._persist_cache()
        return self._token_from_result(result, "logowanie interaktywne")

    def acquire_token_device_code(self, callback: Callable[[str, str], None]) -> str:
        """Loguje uzytkownika kodem urzadzenia i zwraca token dostepu.

        Callback dostaje kod uzytkownika oraz adres, pod ktorym nalezy go wpisac.
        """
        app = self._application()
        scopes = self.effective_scopes()
        try:
            flow = app.initiate_device_flow(scopes=scopes)
        except Exception as exc:
            raise AuthenticationError(
                "Nie udalo sie rozpoczac logowania kodem urzadzenia. "
                "Sprawdz polaczenie z usluga logowania Microsoft.",
                cause=exc,
            ) from exc
        if not isinstance(flow, dict) or not flow.get("user_code"):
            raise AuthenticationError(
                "Usluga logowania nie zwrocila kodu urzadzenia: "
                f"{self._describe_error(flow if isinstance(flow, dict) else None)}"
            )
        verification_uri = str(flow.get("verification_uri") or flow.get("verification_url") or "")
        log.info("auth.device_code_started", source_id=self._source_id)
        callback(str(flow["user_code"]), verification_uri)
        try:
            result = app.acquire_token_by_device_flow(flow)
        except Exception as exc:
            raise AuthenticationError(
                "Logowanie kodem urzadzenia nie zostalo dokonczone. "
                "Kod mogl wygasnac, sprobuj ponownie.",
                cause=exc,
            ) from exc
        finally:
            self._persist_cache()
        return self._token_from_result(result, "logowanie kodem urzadzenia")

    def get_token(self, *, force_refresh: bool = False) -> str:
        """Zwraca wazny token dostepu, w razie potrzeby prosi uzytkownika o logowanie."""
        token = self.acquire_token_silent(force_refresh=force_refresh)
        if token:
            return token
        flow = (self._settings.auth_flow or AUTH_FLOW_INTERACTIVE).strip().lower()
        if flow == AUTH_FLOW_DEVICE_CODE:
            return self.acquire_token_device_code(
                self._device_code_callback or self._fallback_device_code_callback
            )
        if flow == AUTH_FLOW_INTERACTIVE:
            return self.acquire_token_interactive()
        raise AuthenticationError(
            f"Nieznany tryb logowania '{flow}'. Dozwolone wartosci to: "
            f"{AUTH_FLOW_INTERACTIVE}, {AUTH_FLOW_DEVICE_CODE}."
        )

    # --- konto ------------------------------------------------------------

    def sign_out(self) -> None:
        """Usuwa konta z pamieci podrecznej i kasuje wpis w magazynie poswiadczen."""
        if self._app is not None:
            try:
                for account in self._app.get_accounts():
                    self._app.remove_account(account)
            except Exception:
                log.warning("auth.sign_out_partial", source_id=self._source_id)
        self._cache = msal.SerializableTokenCache()
        self._app = None
        try:
            self._store.delete_secret(self._cache_key)
        except CredentialStoreError as exc:
            log.warning(
                "auth.cache_delete_failed", source_id=self._source_id, reason=type(exc).__name__
            )
        log.info("auth.signed_out", source_id=self._source_id)

    def account_info(self) -> dict[str, str]:
        """Opis zalogowanego konta bez zadnych tokenow. Pusty slownik gdy brak konta."""
        accounts = self._cached_accounts()
        if not accounts:
            return {}
        account = accounts[0]
        tenant = str(account.get("realm") or "").strip()
        return {
            "username": str(account.get("username") or ""),
            "tenant": tenant or self._settings.tenant_id.strip() or DEFAULT_TENANT,
            "environment": str(account.get("environment") or ""),
        }

    def has_account(self) -> bool:
        """True, gdy w pamieci podrecznej jest zapisane konto uzytkownika."""
        return bool(self._cached_accounts())

    # --- pomocnicze -------------------------------------------------------

    def _fallback_device_code_callback(self, user_code: str, verification_uri: str) -> None:
        """Zapasowa prezentacja kodu urzadzenia na standardowym wyjsciu bledow.

        Kod jest jednorazowym poswiadczeniem, wiec nie trafia do logow.
        """
        log.info("auth.device_code_ready", source_id=self._source_id, uri=verification_uri)
        sys.stderr.write(f"Otworz strone {verification_uri} i wpisz kod logowania: {user_code}\n")
        sys.stderr.flush()

    def _token_from_result(self, result: Any, operation: str) -> str:
        """Wyciaga token z odpowiedzi MSAL albo rzuca czytelny blad."""
        if not isinstance(result, dict):
            raise AuthenticationError(
                f"Usluga logowania nie zwrocila odpowiedzi ({operation}). Sprobuj ponownie."
            )
        token = result.get("access_token")
        if isinstance(token, str) and token:
            log.info("auth.token_acquired", source_id=self._source_id, flow=operation)
            return token
        raise AuthenticationError(
            f"Uwierzytelnienie nie powiodlo sie ({operation}): {self._describe_error(result)}",
            details={"error": str(result.get("error") or "")},
        )

    @staticmethod
    def _describe_error(result: dict[str, Any] | None) -> str:
        """Buduje opis bledu na podstawie odpowiedzi MSAL, bez danych wrazliwych."""
        if not result:
            return "brak szczegolow odpowiedzi."
        description = result.get("error_description") or result.get("error") or ""
        text = str(description).strip().replace("\r", " ").replace("\n", " ")
        return redact_text(text) if text else "brak szczegolow odpowiedzi."


__all__ = [
    "AUTH_FLOW_DEVICE_CODE",
    "AUTH_FLOW_INTERACTIVE",
    "DEFAULT_AUTHORITY",
    "DEFAULT_TENANT",
    "RESERVED_SCOPES",
    "SUPPORTED_AUTH_FLOWS",
    "GraphAuthenticator",
]

"""Centralna hierarchia wyjatkow FindDocs.

Kazdy wyjatek niesie stabilny kod bledu oraz komunikat po polsku, ktory mozna
pokazac uzytkownikowi. Kody sluza do raportow i diagnostyki, komunikaty do GUI.
"""

from __future__ import annotations

from typing import Any


class FindDocsError(Exception):
    """Bazowy wyjatek aplikacji."""

    code: str = "FD-0000"
    default_message: str = "Wystapil nieoczekiwany blad aplikacji."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        self.user_message = message or self.default_message
        self.details: dict[str, Any] = details or {}
        super().__init__(f"[{self.code}] {self.user_message}")
        if cause is not None:
            self.__cause__ = cause

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.user_message,
            "type": type(self).__name__,
            "details": self.details,
        }


# --- konfiguracja i srodowisko -------------------------------------------------


class ConfigurationError(FindDocsError):
    code = "FD-1001"
    default_message = "Konfiguracja aplikacji jest nieprawidlowa."


class StorageSpaceError(FindDocsError):
    code = "FD-1002"
    default_message = "Brakuje wolnego miejsca na dysku."


class TemporaryStorageError(FindDocsError):
    code = "FD-1003"
    default_message = "Nie udalo sie przygotowac przestrzeni tymczasowej."


class DependencyUnavailableError(FindDocsError):
    code = "FD-1004"
    default_message = "Wymagany komponent nie jest dostepny w tym systemie."


class NetworkPolicyError(FindDocsError):
    code = "FD-1005"
    default_message = "Polaczenie sieciowe zostalo zablokowane przez polityke aplikacji."


# --- zrodla danych -------------------------------------------------------------


class ConnectorError(FindDocsError):
    code = "FD-2000"
    default_message = "Blad zrodla dokumentow."


class SourceUnavailableError(ConnectorError):
    code = "FD-2001"
    default_message = "Zrodlo dokumentow jest niedostepne."


class AuthenticationError(ConnectorError):
    code = "FD-2002"
    default_message = "Uwierzytelnienie nie powiodlo sie."


class TransientConnectorError(ConnectorError):
    """Blad przejsciowy: warto ponowic probe."""

    code = "FD-2003"
    default_message = "Chwilowy problem z polaczeniem. Sprobuj ponownie."


class RateLimitedError(TransientConnectorError):
    code = "FD-2004"
    default_message = "Zrodlo ograniczylo liczbe zapytan. Aplikacja odczeka i ponowi probe."

    def __init__(
        self,
        message: str | None = None,
        *,
        retry_after: float | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message, details=details, cause=cause)
        self.retry_after = retry_after


class DownloadError(ConnectorError):
    code = "FD-2005"
    default_message = "Nie udalo sie pobrac pliku ze zrodla."


# --- ekstrakcja ----------------------------------------------------------------


class ExtractionError(FindDocsError):
    code = "FD-3000"
    default_message = "Nie udalo sie odczytac tresci dokumentu."


class UnsupportedFormatError(ExtractionError):
    code = "FD-3001"
    default_message = "Format pliku nie jest obslugiwany."


class CorruptedFileError(ExtractionError):
    code = "FD-3002"
    default_message = "Plik jest uszkodzony lub niekompletny."


class PasswordProtectedError(ExtractionError):
    code = "FD-3003"
    default_message = "Plik jest zabezpieczony haslem."


class EmptyDocumentError(ExtractionError):
    code = "FD-3004"
    default_message = "Dokument nie zawiera tresci mozliwej do zaindeksowania."


class ExtractionTimeoutError(ExtractionError):
    code = "FD-3005"
    default_message = "Przekroczono czas odczytu dokumentu."


# --- OCR -----------------------------------------------------------------------


class OcrError(FindDocsError):
    code = "FD-4000"
    default_message = "Blad rozpoznawania tekstu (OCR)."


class OcrEngineUnavailableError(OcrError):
    code = "FD-4001"
    default_message = "Zaden silnik OCR nie jest dostepny."


class OcrCancelledError(OcrError):
    code = "FD-4002"
    default_message = "Rozpoznawanie tekstu zostalo przerwane."


# --- indeks --------------------------------------------------------------------


class IndexError_(FindDocsError):
    code = "FD-5000"
    default_message = "Blad indeksu."


class IndexIncompatibleError(IndexError_):
    code = "FD-5001"
    default_message = (
        "Istniejacy indeks nie jest zgodny z biezaca konfiguracja. Wymagana jest przebudowa."
    )


class IndexCorruptedError(IndexError_):
    code = "FD-5002"
    default_message = "Indeks jest uszkodzony."


class MigrationError(IndexError_):
    code = "FD-5003"
    default_message = "Migracja schematu indeksu nie powiodla sie."


# --- embeddingi ----------------------------------------------------------------


class ProviderError(FindDocsError):
    code = "FD-6000"
    default_message = "Blad dostawcy embeddingow."


class ModelNotAvailableError(ProviderError):
    code = "FD-6001"
    default_message = "Model embeddingow nie jest dostepny lokalnie."


class ModelIntegrityError(ProviderError):
    code = "FD-6002"
    default_message = "Suma kontrolna pliku modelu jest niezgodna."


# --- wyszukiwanie --------------------------------------------------------------


class SearchError(FindDocsError):
    code = "FD-7000"
    default_message = "Blad wyszukiwania."


class QuerySyntaxError(SearchError):
    code = "FD-7001"
    default_message = "Zapytanie ma nieprawidlowa skladnie."


class SearchCancelledError(SearchError):
    code = "FD-7002"
    default_message = "Wyszukiwanie zostalo przerwane."


# --- zadania -------------------------------------------------------------------


class JobError(FindDocsError):
    code = "FD-8000"
    default_message = "Blad zadania w tle."


class JobCancelledError(JobError):
    code = "FD-8001"
    default_message = "Zadanie zostalo anulowane."


class CredentialStoreError(FindDocsError):
    code = "FD-9001"
    default_message = "Nie udalo sie zapisac lub odczytac poswiadczen."


__all__ = [
    "AuthenticationError",
    "ConfigurationError",
    "ConnectorError",
    "CorruptedFileError",
    "CredentialStoreError",
    "DependencyUnavailableError",
    "DownloadError",
    "EmptyDocumentError",
    "ExtractionError",
    "ExtractionTimeoutError",
    "FindDocsError",
    "IndexCorruptedError",
    "IndexError_",
    "IndexIncompatibleError",
    "JobCancelledError",
    "JobError",
    "MigrationError",
    "ModelIntegrityError",
    "ModelNotAvailableError",
    "NetworkPolicyError",
    "OcrCancelledError",
    "OcrEngineUnavailableError",
    "OcrError",
    "PasswordProtectedError",
    "ProviderError",
    "QuerySyntaxError",
    "RateLimitedError",
    "SearchCancelledError",
    "SearchError",
    "SourceUnavailableError",
    "StorageSpaceError",
    "TemporaryStorageError",
    "TransientConnectorError",
    "UnsupportedFormatError",
]

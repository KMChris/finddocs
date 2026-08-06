"""Wersje aplikacji i komponentow wplywajacych na zgodnosc indeksu."""

from __future__ import annotations

APP_NAME = "FindDocs"
APP_VERSION = "0.2.3"

#: Wersja schematu bazy metadanych. Podnies przy kazdej migracji.
SCHEMA_VERSION = 1

#: Wersja potoku normalizacji. Zmiana wymusza ponowne przetworzenie tekstu.
NORMALIZATION_VERSION = 1

#: Wersja algorytmu fragmentacji. Zmiana wymusza ponowna fragmentacje dokumentow.
CHUNKING_VERSION = 1

#: Wersja formatu skladowania indeksu wektorowego.
VECTOR_STORE_VERSION = 1

__all__ = [
    "APP_NAME",
    "APP_VERSION",
    "CHUNKING_VERSION",
    "NORMALIZATION_VERSION",
    "SCHEMA_VERSION",
    "VECTOR_STORE_VERSION",
]

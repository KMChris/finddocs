"""Wersje aplikacji i komponentow wplywajacych na zgodnosc indeksu."""

from __future__ import annotations

APP_NAME = "FindDocs"
APP_VERSION = "0.3.0"

#: Wersja schematu bazy metadanych. Podnies przy kazdej migracji.
SCHEMA_VERSION = 1

#: Wersja potoku normalizacji. Zmiana wymusza ponowne przetworzenie tekstu.
NORMALIZATION_VERSION = 1

#: Wersja algorytmu fragmentacji. Zmiana wymusza ponowna fragmentacje dokumentow.
CHUNKING_VERSION = 1

#: Wersja formatu skladowania indeksu wektorowego.
VECTOR_STORE_VERSION = 1

#: Wersja formatu naglowka kontekstu dokumentu (nazwa pliku i sciezka) doklejanego
#: do fragmentow przed osadzeniem. Wchodzi do skrotu zgodnosci czesci wektorowej
#: wylacznie przy wlaczonym wzbogaceniu. Zmiana formatu naglowka wymaga podniesienia.
EMBED_CONTEXT_VERSION = 1

__all__ = [
    "APP_NAME",
    "APP_VERSION",
    "CHUNKING_VERSION",
    "EMBED_CONTEXT_VERSION",
    "NORMALIZATION_VERSION",
    "SCHEMA_VERSION",
    "VECTOR_STORE_VERSION",
]

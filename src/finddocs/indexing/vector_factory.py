"""Fabryka magazynow wektorow.

Wybor implementacji zalezy od ``vector_store.backend`` w konfiguracji.
Domyslny pozostaje lokalny plik FAISS; zewnetrzna baza pgvector wymaga
swiadomego wlaczenia i kompletu danych polaczenia.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from finddocs.app_paths import AppPaths
from finddocs.config import AppConfig
from finddocs.errors import ConfigurationError
from finddocs.indexing.base import VectorIndex
from finddocs.indexing.pgvector import PgVectorStore
from finddocs.indexing.vector import VectorStore
from finddocs.logging_setup import get_logger

log = get_logger(__name__)

BACKEND_FAISS = "faiss"
BACKEND_PGVECTOR = "pgvector"


def pgvector_password_provider(config_dir: Path) -> Callable[[], str | None]:
    """Buduje funkcje odczytu hasla bazy z magazynu poswiadczen.

    Haslo jest odczytywane dopiero przy nawiazywaniu polaczenia, wiec jego
    zmiana w magazynie dziala bez ponownego tworzenia magazynu wektorow.
    """
    from finddocs.security.credentials import PGVECTOR_PASSWORD_NAME, create_credential_store

    def read_password() -> str | None:
        try:
            store = create_credential_store(config_dir)
            return store.get_secret(PGVECTOR_PASSWORD_NAME)
        except Exception as exc:
            log.warning("vector.password_unavailable", error_type=type(exc).__name__)
            return None

    return read_password


def create_vector_store(config: AppConfig, paths: AppPaths) -> VectorIndex:
    """Tworzy magazyn wektorow zgodnie z konfiguracja.

    Samo utworzenie nie nawiazuje zadnego polaczenia; robi to dopiero ``open``.
    """
    backend = (config.vector_store.backend or BACKEND_FAISS).strip().lower()
    if backend == BACKEND_FAISS:
        return VectorStore(paths.vector_file, paths.vector_meta_file)
    if backend == BACKEND_PGVECTOR:
        return PgVectorStore(
            config.vector_store,
            password_provider=pgvector_password_provider(paths.config_dir),
        )
    raise ConfigurationError(
        f"Nieznany magazyn wektorów: '{config.vector_store.backend}'. "
        "Dozwolone wartości: faiss, pgvector."
    )


__all__ = [
    "BACKEND_FAISS",
    "BACKEND_PGVECTOR",
    "create_vector_store",
    "pgvector_password_provider",
]

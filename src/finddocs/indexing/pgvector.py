"""Magazyn wektorow w zewnetrznej bazie PostgreSQL z rozszerzeniem pgvector.

Alternatywa dla lokalnego pliku FAISS, przeznaczona dla stanowisk z dostepem do
bazy danych utrzymywanej przez organizacje. Wlaczenie wymaga swiadomej
konfiguracji (``vector_store.backend = pgvector``) i przechodzi przez polityke
sieciowa: dozwolony jest wylacznie host podany w konfiguracji, a polaczenie
z hostem innym niz lokalny wymaga TLS (sslmode co najmniej ``require``).

Podzial odpowiedzialnosci jest taki sam jak przy FAISS: SQLite pozostaje
zrodlem prawdy o dokumentach i fragmentach, a baza pgvector trzyma wylacznie
pary (chunk_id, wektor). Do bazy nie trafia zaden tekst. Usuniecia sa
wykonywane od razu (DELETE), wiec nagrobki i kompaktacja nie sa potrzebne.
Metadane zgodnosci (wersja formatu, model, wymiar, skrot konfiguracji) leza
w tabeli obok wektorow i sa sprawdzane przy otwarciu tak samo, jak metadane
pliku FAISS. Dzieki temu indeksu zbudowanego inna konfiguracja nie da sie
przypadkiem domieszac.

Haslo uzytkownika bazy nie jest zapisywane w konfiguracji. Magazyn dostaje
funkcje zwracajaca haslo z magazynu poswiadczen i odczytuje je dopiero przy
nawiazywaniu polaczenia.

Sterownik ``psycopg`` jest zaleznoscia opcjonalna (``requirements-pgvector.txt``)
i jest importowany dopiero przy pierwszym polaczeniu. Argument ``driver``
konstruktora to hak testowy, pozwalajacy podstawic sterownik udawany.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import json
import re
import threading
from collections.abc import Callable, Iterator
from typing import Any

import numpy as np

from finddocs.config import VectorStoreSettings
from finddocs.errors import (
    ConfigurationError,
    DependencyUnavailableError,
    IndexCorruptedError,
    IndexIncompatibleError,
    VectorBackendUnavailableError,
)
from finddocs.indexing.vector import HNSW_EF_CONSTRUCTION, HNSW_EF_SEARCH, HNSW_M
from finddocs.logging_setup import get_logger
from finddocs.security.network import LOCAL_HOSTS, EgressCategory, NetworkPolicy, get_policy
from finddocs.version import VECTOR_STORE_VERSION

log = get_logger(__name__)

#: Tryby sslmode gwarantujace szyfrowanie polaczenia.
TLS_SSLMODES = frozenset({"require", "verify-ca", "verify-full"})

#: Wszystkie tryby sslmode znane sterownikowi libpq.
KNOWN_SSLMODES = TLS_SSLMODES | frozenset({"disable", "allow", "prefer"})

#: Gorny limit parametru hnsw.ef_search po stronie pgvector.
MAX_EF_SEARCH = 1000

#: Liczba wierszy wstawianych jedna paczka.
INSERT_BATCH_ROWS = 500

#: Typ kolumny wektora. ``halfvec`` (polowa precyzji) przyjmuje w indeksie HNSW
#: do 4000 wymiarow, podczas gdy ``vector`` konczy sie na 2000. Wektory sa
#: znormalizowane L2, wiec float16 wystarcza, a tabela zajmuje polowe miejsca.
VECTOR_COLUMN_TYPE = "halfvec"

#: Klasa operatorow HNSW dla iloczynu skalarnego przy typie ``halfvec``.
VECTOR_OPS_CLASS = "halfvec_ip_ops"

#: Najstarsza wersja pgvector z typem ``halfvec``.
MIN_PGVECTOR_VERSION = (0, 7, 0)

#: Identyfikator SQL bez cudzyslowow. Limit 57 znakow zostawia miejsce na
#: przyrostek ``__meta`` w granicach 63 znakow PostgreSQL.
_IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]{0,56}$")


def validate_identifier(value: str, what: str) -> str:
    """Sprawdza nazwe schematu albo tabeli. Zwraca nazwe oczyszczona.

    Nazwy trafiaja do polecen DDL, ktorych nie da sie parametryzowac, wiec
    dozwolone sa wylacznie male litery ASCII, cyfry i podkreslenia.
    """
    cleaned = (value or "").strip()
    if not _IDENTIFIER_RE.match(cleaned):
        raise ConfigurationError(
            f"Nieprawidłowa nazwa ({what}): '{cleaned}'. Dozwolone są małe litery "
            "ASCII, cyfry i podkreślenia, maksymalnie 57 znaków."
        )
    return cleaned


def vector_literal(vector: np.ndarray) -> str:
    """Zapis wektora w formacie tekstowym pgvector, np. ``[0.25,-1.5]``."""
    return "[" + ",".join(repr(float(value)) for value in vector) + "]"


def _parse_vector(text: str) -> np.ndarray:
    """Odczytuje wektor z formatu tekstowego pgvector (zgodny z JSON)."""
    return np.asarray(json.loads(text), dtype="float32")


def _timestamp() -> str:
    return _dt.datetime.now().astimezone().isoformat()


class PgVectorStore:
    """Magazyn wektorow fragmentow w tabeli PostgreSQL z typem ``halfvec``.

    Implementuje protokol ``finddocs.indexing.base.VectorIndex``. Obok tabeli
    danych zyje tabela ``<nazwa>__meta`` z metadanymi zgodnosci.

    Kolumna ma typ ``halfvec`` (float16), bo indeks HNSW przyjmuje dla niego do
    4000 wymiarow zamiast 2000 przy typie ``vector``. Wektory sa znormalizowane
    L2, wiec polowa precyzji nie psuje rankingu, a tabela zajmuje polowe miejsca.
    Typ kolumny trafia do metadanych (``vector_type``): tabele zapisane starsza
    wersja aplikacji sa odrzucane z zadaniem przebudowy, zamiast byc czytane
    niewlasciwym rzutowaniem.
    """

    def __init__(
        self,
        settings: VectorStoreSettings,
        *,
        password_provider: Callable[[], str | None] | None = None,
        policy: NetworkPolicy | None = None,
        driver: Any | None = None,
    ) -> None:
        host = settings.pgvector_host.strip()
        if not host:
            raise ConfigurationError("Nie podano adresu serwera PostgreSQL dla magazynu wektorów.")
        if not settings.pgvector_database.strip():
            raise ConfigurationError("Nie podano nazwy bazy danych dla magazynu wektorów.")
        if not settings.pgvector_user.strip():
            raise ConfigurationError("Nie podano użytkownika bazy danych dla magazynu wektorów.")

        sslmode = settings.pgvector_sslmode.strip().lower() or "require"
        if sslmode not in KNOWN_SSLMODES:
            raise ConfigurationError(
                f"Nieznany tryb sslmode: '{sslmode}'. Dozwolone wartości: "
                + ", ".join(sorted(KNOWN_SSLMODES))
                + "."
            )
        if host.lower() not in LOCAL_HOSTS and sslmode not in TLS_SSLMODES:
            raise ConfigurationError(
                "Połączenie z zewnętrzną bazą wektorową wymaga szyfrowania TLS. "
                "Ustaw sslmode na require, verify-ca albo verify-full."
            )

        schema = validate_identifier(settings.pgvector_schema, "schemat")
        table = validate_identifier(settings.pgvector_table, "tabela")

        self._settings = settings
        self._host = host
        self._sslmode = sslmode
        self._qualified = f'"{schema}"."{table}"'
        self._qualified_meta = f'"{schema}"."{table}__meta"'
        self._schema = schema
        self._table = table
        self._policy = policy or get_policy()
        self._password_provider = password_provider
        self._driver = driver
        self._conn: Any | None = None
        self._lock = threading.RLock()
        self._opened = False
        self._dimension = 0
        self._model_key = ""
        self._model_version = ""
        self._compat_hash = ""

    # --- sterownik i polaczenie ---------------------------------------------

    def _load_driver(self) -> Any:
        if self._driver is None:
            try:
                import psycopg
            except ImportError as exc:
                raise DependencyUnavailableError(
                    "Sterownik psycopg nie jest zainstalowany. Magazyn pgvector "
                    "wymaga polecenia: pip install -r requirements-pgvector.txt.",
                    cause=exc,
                ) from exc
            self._driver = psycopg
        return self._driver

    def _connect(self) -> Any:
        driver = self._load_driver()
        self._policy.check_host(self._host, EgressCategory.VECTOR_DB)
        password = self._password_provider() if self._password_provider is not None else None
        try:
            conn = driver.connect(
                host=self._host,
                port=int(self._settings.pgvector_port),
                dbname=self._settings.pgvector_database.strip(),
                user=self._settings.pgvector_user.strip(),
                password=password,
                sslmode=self._sslmode,
                connect_timeout=max(1, int(self._settings.pgvector_connect_timeout_seconds)),
                application_name="FindDocs",
                autocommit=True,
            )
        except driver.OperationalError as exc:
            raise VectorBackendUnavailableError(
                "Nie udało się połączyć z bazą wektorową. Sprawdź adres serwera, "
                "dane logowania i dostępność bazy.",
                cause=exc,
            ) from exc
        timeout_ms = max(1000, int(self._settings.pgvector_statement_timeout_seconds * 1000))
        conn.execute("SELECT set_config('statement_timeout', %s, false)", (str(timeout_ms),))
        log.info("vector.pgvector_connected", host=self._host, table=self._table)
        return conn

    def _require_conn(self) -> Any:
        if self._conn is None:
            self._conn = self._connect()
        return self._conn

    def _drop_connection(self) -> None:
        if self._conn is not None:
            with contextlib.suppress(Exception):
                self._conn.close()
            self._conn = None

    @contextlib.contextmanager
    def _translate_errors(self) -> Iterator[None]:
        """Zamienia wyjatki sterownika na wyjatki aplikacji.

        Blad polaczenia (OperationalError) zamyka polaczenie, zeby nastepna
        operacja sprobowala nawiazac je od nowa.
        """
        driver = self._load_driver()
        try:
            yield
        except driver.OperationalError as exc:
            self._drop_connection()
            raise VectorBackendUnavailableError(cause=exc) from exc
        except driver.Error as exc:
            raise IndexCorruptedError(
                "Operacja na bazie wektorowej nie powiodła się.", cause=exc
            ) from exc

    # --- cykl zycia ----------------------------------------------------------

    def open(
        self,
        *,
        dimension: int,
        model_key: str,
        model_version: str,
        vector_compat_hash: str,
        create: bool = True,
    ) -> None:
        """Otwiera istniejacy indeks w bazie albo tworzy nowy.

        Rzuca ``IndexIncompatibleError``, gdy metadane w bazie nie zgadzaja sie
        z biezacym modelem. Tabela nie jest wtedy modyfikowana ani czyszczona.
        """
        if dimension <= 0:
            raise IndexCorruptedError(f"Nieprawidłowy wymiar wektora: {dimension}.")
        with self._lock:
            if self._opened:
                return
            self._conn = self._connect()
            try:
                with self._translate_errors():
                    self._ensure_extension()
                    self._ensure_meta_table()
                    stored = self._read_meta()
                    if stored:
                        self._verify_meta(
                            stored,
                            dimension=dimension,
                            vector_compat_hash=vector_compat_hash,
                        )
                    elif not create:
                        raise IndexCorruptedError("Indeks wektorowy nie istnieje.")
                    self._ensure_data_table(dimension)
                    self._check_column_dimension(dimension)
                    if not stored:
                        self._write_meta(
                            dimension=dimension,
                            model_key=model_key,
                            model_version=model_version,
                            vector_compat_hash=vector_compat_hash,
                        )
                self._dimension = dimension
                self._model_key = model_key
                self._model_version = model_version
                self._compat_hash = vector_compat_hash
                self._opened = True
            except BaseException:
                self._drop_connection()
                raise

    def close(self) -> None:
        with self._lock:
            self._drop_connection()
            self._opened = False

    def save(self) -> None:
        """Nic do zrobienia: kazdy zapis jest utrwalany po stronie serwera."""

    @property
    def is_open(self) -> bool:
        return self._opened

    @property
    def dimension(self) -> int:
        return self._dimension

    # --- przygotowanie schematu ----------------------------------------------

    def _ensure_extension(self) -> None:
        conn = self._require_conn()
        row = conn.execute(
            "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
        ).fetchone()
        if row is None:
            driver = self._load_driver()
            try:
                conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            except driver.Error as exc:
                raise ConfigurationError(
                    "Baza PostgreSQL nie ma zainstalowanego rozszerzenia pgvector, "
                    "a bieżący użytkownik nie może go utworzyć. Poproś administratora "
                    "bazy o wykonanie polecenia CREATE EXTENSION vector.",
                    cause=exc,
                ) from exc
            row = conn.execute(
                "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
            ).fetchone()
        self._check_extension_version(str(row[0]) if row else "")

    def _check_extension_version(self, version: str) -> None:
        """Sprawdza, czy pgvector zna typ ``halfvec`` (od 0.7.0).

        Nieczytelny numer wersji przepuszczamy: lepiej pozwolic serwerowi
        odpowiedziec bledem na CREATE TABLE niz blokowac dzialajaca baze
        z powodu nietypowego formatu wersji.
        """
        parts: list[int] = []
        for piece in version.split(".")[:3]:
            digits = "".join(c for c in piece if c.isdigit())
            if not digits:
                return
            parts.append(int(digits))
        if not parts:
            return
        while len(parts) < 3:
            parts.append(0)
        if tuple(parts) < MIN_PGVECTOR_VERSION:
            wymagana = ".".join(str(number) for number in MIN_PGVECTOR_VERSION)
            raise ConfigurationError(
                f"Rozszerzenie pgvector w bazie ma wersję {version}, a magazyn "
                f"wektorów wymaga co najmniej {wymagana} (typ halfvec). "
                "Poproś administratora bazy o aktualizację rozszerzenia."
            )

    def _ensure_meta_table(self) -> None:
        self._require_conn().execute(
            f"CREATE TABLE IF NOT EXISTS {self._qualified_meta} "
            "(key text PRIMARY KEY, value text NOT NULL)"
        )

    def _ensure_data_table(self, dimension: int) -> None:
        conn = self._require_conn()
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {self._qualified} "
            f"(chunk_id bigint PRIMARY KEY, "
            f"embedding {VECTOR_COLUMN_TYPE}({dimension}) NOT NULL)"
        )
        conn.execute(
            f'CREATE INDEX IF NOT EXISTS "{self._table}__embedding_idx" '
            f"ON {self._qualified} USING hnsw (embedding {VECTOR_OPS_CLASS}) "
            f"WITH (m = {HNSW_M}, ef_construction = {HNSW_EF_CONSTRUCTION})"
        )

    def _check_column_dimension(self, dimension: int) -> None:
        """Porownuje kolumne w bazie z biezacym modelem: typ i wymiar.

        Chroni przed tabela utworzona poza aplikacja, dla innego modelu albo
        przez starsza wersje FindDocs (typ ``vector`` zamiast ``halfvec``).
        Dla obu typow atttypmod przechowuje wprost liczbe wymiarow.
        """
        row = (
            self._require_conn()
            .execute(
                "SELECT a.atttypmod, t.typname FROM pg_attribute a "
                "JOIN pg_class c ON c.oid = a.attrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "JOIN pg_type t ON t.oid = a.atttypid "
                "WHERE n.nspname = %s AND c.relname = %s AND a.attname = 'embedding'",
                (self._schema, self._table),
            )
            .fetchone()
        )
        if row is None:
            return
        stored = int(row[0])
        if stored > 0 and stored != dimension:
            raise IndexIncompatibleError(
                f"Tabela wektorów w bazie ma wymiar {stored}, a wybrany model "
                f"tworzy wektory o wymiarze {dimension}."
            )
        stored_type = str(row[1] or "")
        if stored_type and stored_type != VECTOR_COLUMN_TYPE:
            raise IndexIncompatibleError(
                f"Tabela wektorów w bazie używa typu kolumny '{stored_type}', "
                f"a bieżąca wersja aplikacji zapisuje typ '{VECTOR_COLUMN_TYPE}'. "
                "Wymagana jest przebudowa części semantycznej indeksu."
            )

    # --- metadane zgodnosci ----------------------------------------------------

    def _read_meta(self) -> dict[str, str]:
        rows = (
            self._require_conn()
            .execute(f"SELECT key, value FROM {self._qualified_meta}")
            .fetchall()
        )
        return {str(key): str(value) for key, value in rows}

    def _write_meta(
        self,
        *,
        dimension: int,
        model_key: str,
        model_version: str,
        vector_compat_hash: str,
    ) -> None:
        entries = {
            "store_version": str(VECTOR_STORE_VERSION),
            "dimension": str(dimension),
            "model_key": model_key,
            "model_version": model_version,
            "vector_compat_hash": vector_compat_hash,
            "metric": "inner_product",
            "index_type": "hnsw",
            "vector_type": VECTOR_COLUMN_TYPE,
            "created_at": _timestamp(),
        }
        conn = self._require_conn()
        with conn.transaction():
            for key, value in entries.items():
                conn.execute(
                    f"INSERT INTO {self._qualified_meta} (key, value) VALUES (%s, %s) "
                    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                    (key, value),
                )

    def _verify_meta(
        self, stored: dict[str, str], *, dimension: int, vector_compat_hash: str
    ) -> None:
        version = stored.get("store_version", "")
        if version != str(VECTOR_STORE_VERSION):
            raise IndexIncompatibleError(
                "Format indeksu wektorowego w bazie pochodzi z innej wersji aplikacji. "
                "Wymagana jest przebudowa części semantycznej."
            )
        stored_dimension = int(stored.get("dimension", "0") or "0")
        if stored_dimension != dimension:
            raise IndexIncompatibleError(
                f"Indeks wektorowy w bazie ma wymiar {stored_dimension}, "
                f"a wybrany model tworzy wektory o wymiarze {dimension}."
            )
        # Tabele sprzed przejscia na halfvec nie maja tego klucza. Brak wartosci
        # oznacza wiec stary typ vector, ktorego nie da sie czytac biezacym
        # rzutowaniem, a nie tabele bez metadanych.
        stored_type = stored.get("vector_type", "vector")
        if stored_type != VECTOR_COLUMN_TYPE:
            raise IndexIncompatibleError(
                f"Indeks wektorowy w bazie zapisano typem '{stored_type}', "
                f"a bieżąca wersja aplikacji używa typu '{VECTOR_COLUMN_TYPE}'. "
                "Wymagana jest przebudowa części semantycznej indeksu."
            )
        if stored.get("vector_compat_hash", "") != vector_compat_hash:
            raise IndexIncompatibleError(
                "Konfiguracja modelu albo fragmentacji zmienila sie od czasu "
                "zbudowania indeksu wektorowego. Wymagana jest przebudowa."
            )

    # --- operacje ---------------------------------------------------------------

    def count(self) -> int:
        with self._lock:
            if not self._opened:
                return 0
            with self._translate_errors():
                row = (
                    self._require_conn()
                    .execute(f"SELECT COUNT(*) FROM {self._qualified}")
                    .fetchone()
                )
        return int(row[0]) if row is not None else 0

    def raw_count(self) -> int:
        return self.count()

    def deleted_count(self) -> int:
        """Magazyn nie uzywa nagrobkow: usuniecie jest natychmiastowe."""
        return 0

    def needs_compaction(self) -> bool:
        return False

    def add(self, ids: list[int], vectors: np.ndarray) -> None:
        """Dodaje albo nadpisuje wektory. Ponowny zapis identyfikatora to aktualizacja."""
        if not ids:
            return
        with self._lock:
            if not self._opened:
                raise IndexCorruptedError("Indeks wektorowy nie jest otwarty.")
            array = np.ascontiguousarray(vectors, dtype="float32")
            if array.ndim != 2 or array.shape[1] != self._dimension:
                raise IndexCorruptedError(
                    f"Oczekiwano wektorów o wymiarze {self._dimension}, "
                    f"otrzymano ksztalt {array.shape}."
                )
            if array.shape[0] != len(ids):
                raise IndexCorruptedError(
                    "Liczba identyfikatorów nie zgadza się z liczba wektorów."
                )
            rows = [
                (int(chunk_id), vector_literal(array[position]))
                for position, chunk_id in enumerate(ids)
            ]
            with self._translate_errors():
                conn = self._require_conn()
                with conn.transaction(), conn.cursor() as cursor:
                    for start in range(0, len(rows), INSERT_BATCH_ROWS):
                        cursor.executemany(
                            f"INSERT INTO {self._qualified} (chunk_id, embedding) "
                            f"VALUES (%s, %s::{VECTOR_COLUMN_TYPE}) "
                            "ON CONFLICT (chunk_id) DO UPDATE SET embedding = EXCLUDED.embedding",
                            rows[start : start + INSERT_BATCH_ROWS],
                        )

    def remove(self, ids: list[int]) -> None:
        """Usuwa wektory od razu, bez nagrobkow."""
        if not ids:
            return
        with self._lock:
            if not self._opened:
                return
            with self._translate_errors():
                self._require_conn().execute(
                    f"DELETE FROM {self._qualified} WHERE chunk_id = ANY(%s)",
                    ([int(chunk_id) for chunk_id in ids],),
                )

    def search(
        self, query: np.ndarray, k: int, *, overfetch: float = 2.0
    ) -> list[tuple[int, float]]:
        """Zwraca liste par (chunk_id, podobienstwo) posortowana malejaco.

        ``overfetch`` jest czescia wspolnego protokolu; tutaj nie ma nagrobkow,
        wiec nadmiarowe pobieranie nie jest potrzebne.
        """
        with self._lock:
            if not self._opened:
                return []
            wanted = max(1, k)
            ef_search = min(MAX_EF_SEARCH, max(HNSW_EF_SEARCH, wanted))
            literal = vector_literal(np.ascontiguousarray(query, dtype="float32").reshape(-1))
            with self._translate_errors():
                conn = self._require_conn()
                with conn.transaction():
                    conn.execute("SELECT set_config('hnsw.ef_search', %s, true)", (str(ef_search),))
                    rows = conn.execute(
                        f"SELECT chunk_id, (embedding <#> %s::{VECTOR_COLUMN_TYPE}) * -1.0 "
                        f"FROM {self._qualified} "
                        f"ORDER BY embedding <#> %s::{VECTOR_COLUMN_TYPE} LIMIT %s",
                        (literal, literal, wanted),
                    ).fetchall()
        return [(int(chunk_id), float(score)) for chunk_id, score in rows]

    def reconstruct(self, chunk_id: int) -> np.ndarray | None:
        """Odtwarza wektor o podanym identyfikatorze, jesli istnieje."""
        with self._lock:
            if not self._opened:
                return None
            with self._translate_errors():
                row = (
                    self._require_conn()
                    .execute(
                        f"SELECT embedding::text FROM {self._qualified} WHERE chunk_id = %s",
                        (int(chunk_id),),
                    )
                    .fetchone()
                )
        if row is None:
            return None
        return _parse_vector(str(row[0]))

    def compact(self, active_ids: list[int], vectors: np.ndarray) -> None:
        """Zastepuje zawartosc tabeli podanym zbiorem aktywnych wektorow.

        Magazyn nie ma nagrobkow, wiec kompaktacja nie jest potrzebna na co
        dzien. Operacja pozostaje dostepna jako pelna resynchronizacja,
        np. po okresie niedostepnosci bazy.
        """
        with self._lock:
            if not self._opened:
                raise IndexCorruptedError("Indeks wektorowy nie jest otwarty.")
            with self._translate_errors():
                conn = self._require_conn()
                with conn.transaction():
                    conn.execute(f"DELETE FROM {self._qualified}")
            if active_ids:
                self.add(active_ids, vectors)
        log.info("vector.pgvector_compacted", vectors=len(active_ids))

    def reset(self) -> None:
        """Czysci tabele wektorow, zachowujac metadane modelu."""
        with self._lock:
            if not self._opened:
                return
            with self._translate_errors():
                self._require_conn().execute(f"DELETE FROM {self._qualified}")

    def size_bytes(self) -> int:
        """Rozmiar tabeli po stronie serwera. Zero, gdy nie da sie go odczytac."""
        with self._lock:
            if not self._opened:
                return 0
            try:
                row = (
                    self._require_conn()
                    .execute(
                        "SELECT pg_total_relation_size(%s::regclass)",
                        (f'"{self._schema}"."{self._table}"',),
                    )
                    .fetchone()
                )
            except Exception:
                return 0
        return int(row[0]) if row is not None else 0

    def describe(self) -> dict[str, Any]:
        try:
            active = self.count()
        except Exception:
            active = -1
        return {
            "magazyn": "pgvector",
            "serwer": f"{self._host}:{self._settings.pgvector_port}",
            "baza": self._settings.pgvector_database.strip(),
            "tabela": f"{self._schema}.{self._table}",
            "model": self._model_key,
            "wersja_modelu": self._model_version,
            "wymiar": self._dimension,
            "typ_indeksu": "hnsw",
            "metryka": "inner_product",
            "wektory_aktywne": active,
            "nagrobki": 0,
            "rozmiar_bajty": self.size_bytes(),
        }

    # --- diagnostyka -------------------------------------------------------------

    def ping(self) -> dict[str, Any]:
        """Nawiazuje probne polaczenie i sprawdza obecnosc rozszerzenia pgvector.

        Zwraca opis serwera do pokazania w interfejsie. Nie wymaga wczesniejszego
        ``open`` i nie zostawia otwartego polaczenia.
        """
        conn = self._connect()
        try:
            with self._translate_errors():
                version_row = conn.execute("SHOW server_version").fetchone()
                extension_row = conn.execute(
                    "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
                ).fetchone()
        finally:
            with contextlib.suppress(Exception):
                conn.close()
        return {
            "serwer": f"{self._host}:{self._settings.pgvector_port}",
            "wersja_serwera": str(version_row[0]) if version_row else "nieznana",
            "pgvector": str(extension_row[0]) if extension_row else None,
        }


__all__ = [
    "INSERT_BATCH_ROWS",
    "KNOWN_SSLMODES",
    "MAX_EF_SEARCH",
    "TLS_SSLMODES",
    "PgVectorStore",
    "validate_identifier",
    "vector_literal",
]

"""Migracje schematu bazy indeksu.

Migracje sa uporzadkowana lista krokow. Kazdy krok ma numer wersji, opis
i funkcje wykonujaca zmiany. Uruchomienie jest idempotentne: aplikowane sa tylko
kroki o numerze wyzszym niz zapisany w bazie.

Aktualizacja aplikacji nigdy nie kasuje danych. Gdy krok migracji zawiedzie,
transakcja jest wycofywana, a baza pozostaje w poprzedniej, spojnej wersji.
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from finddocs.errors import MigrationError
from finddocs.indexing.schema import (
    META_APP_VERSION,
    META_CREATED_AT,
    META_SCHEMA_VERSION,
    SCHEMA_VERSION,
    create_schema,
    current_schema_version,
)
from finddocs.logging_setup import get_logger
from finddocs.version import APP_VERSION

log = get_logger(__name__)

MigrationFunc = Callable[[sqlite3.Connection], None]


@dataclass(frozen=True, slots=True)
class Migration:
    """Pojedynczy krok migracji."""

    version: int
    description: str
    apply: MigrationFunc


def _migration_001_initial(conn: sqlite3.Connection) -> None:
    """Tworzy pelny schemat poczatkowy."""
    create_schema(conn)


MIGRATIONS: list[Migration] = [
    Migration(1, "schemat poczatkowy", _migration_001_initial),
]


def column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Sprawdza, czy tabela ma podana kolumne. Przydatne w krokach migracji."""
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.OperationalError:
        return False
    return any(row[1] == column for row in rows)


def add_column_if_missing(
    conn: sqlite3.Connection, table: str, column: str, definition: str
) -> None:
    """Dodaje kolumne, jesli jeszcze jej nie ma."""
    if not column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def pending_migrations(conn: sqlite3.Connection) -> list[Migration]:
    """Lista krokow do zastosowania dla biezacej bazy."""
    version = current_schema_version(conn)
    return [m for m in MIGRATIONS if m.version > version]


def migrate(conn: sqlite3.Connection, *, target: int | None = None) -> int:
    """Doprowadza baze do wskazanej wersji schematu. Zwraca osiagnieta wersje."""
    goal = SCHEMA_VERSION if target is None else target
    version = current_schema_version(conn)
    if version > goal:
        raise MigrationError(
            f"Baza ma wersje schematu {version}, nowsza niz obslugiwana {goal}. "
            "Zaktualizuj aplikacje albo odbuduj indeks."
        )
    if version == goal:
        return version

    now = _dt.datetime.now().astimezone().isoformat()
    for migration in MIGRATIONS:
        if migration.version <= version or migration.version > goal:
            continue
        log.info("migration.apply", version=migration.version, description=migration.description)
        conn.execute("BEGIN IMMEDIATE")
        try:
            migration.apply(conn)
            conn.execute(
                "INSERT OR REPLACE INTO schema_migrations(version, applied_at, description) "
                "VALUES (?, ?, ?)",
                (migration.version, now, migration.description),
            )
            conn.execute(
                "INSERT OR REPLACE INTO index_meta(key, value) VALUES (?, ?)",
                (META_SCHEMA_VERSION, str(migration.version)),
            )
        except Exception as exc:
            conn.execute("ROLLBACK")
            raise MigrationError(
                f"Migracja do wersji {migration.version} nie powiodla sie: {exc}",
                details={"version": migration.version},
                cause=exc,
            ) from exc
        conn.execute("COMMIT")
        version = migration.version

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "INSERT OR REPLACE INTO index_meta(key, value) VALUES (?, ?)",
            (META_APP_VERSION, APP_VERSION),
        )
        conn.execute(
            "INSERT OR IGNORE INTO index_meta(key, value) VALUES (?, ?)",
            (META_CREATED_AT, now),
        )
    except Exception as exc:  # pragma: no cover - zapis metadanych jest trywialny
        conn.execute("ROLLBACK")
        raise MigrationError("Nie udalo sie zapisac metadanych indeksu.", cause=exc) from exc
    conn.execute("COMMIT")

    return version


__all__ = [
    "MIGRATIONS",
    "Migration",
    "MigrationFunc",
    "add_column_if_missing",
    "column_exists",
    "migrate",
    "pending_migrations",
]

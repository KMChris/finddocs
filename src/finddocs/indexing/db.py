"""Polaczenie z SQLite: tryb WAL, pragmy wydajnosciowe i pomoc transakcyjna.

Aplikacja uzywa jednego pliku bazy dla metadanych, fragmentow i indeksu FTS5.
Polaczenia sa tworzone per watek, bo modul ``sqlite3`` nie pozwala dzielic ich
miedzy watkami.
"""

from __future__ import annotations

import contextlib
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from finddocs.errors import IndexCorruptedError
from finddocs.logging_setup import get_logger

log = get_logger(__name__)

#: Pragmy ustawiane dla kazdego polaczenia.
CONNECTION_PRAGMAS: tuple[tuple[str, str], ...] = (
    ("journal_mode", "WAL"),
    ("synchronous", "NORMAL"),
    ("foreign_keys", "ON"),
    ("temp_store", "MEMORY"),
    ("cache_size", "-65536"),
    ("busy_timeout", "15000"),
    ("mmap_size", "268435456"),
)


def _row_factory(cursor: sqlite3.Cursor, row: tuple[Any, ...]) -> sqlite3.Row:
    return sqlite3.Row(cursor, row)


def open_connection(path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    """Otwiera polaczenie z baza i ustawia pragmy."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if read_only:
        uri = f"file:{path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=15.0, isolation_level=None)
    else:
        conn = sqlite3.connect(str(path), timeout=15.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    for name, value in CONNECTION_PRAGMAS:
        if read_only and name in {"journal_mode", "synchronous"}:
            continue
        conn.execute(f"PRAGMA {name}={value}")
    return conn


def check_fts5(conn: sqlite3.Connection) -> bool:
    """Sprawdza, czy biblioteka SQLite ma modul FTS5."""
    try:
        conn.execute("CREATE VIRTUAL TABLE temp.fts5_probe USING fts5(x)")
        conn.execute("DROP TABLE temp.fts5_probe")
    except sqlite3.OperationalError:
        return False
    return True


class Database:
    """Uchwyt bazy z polaczeniami per watek."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._local = threading.local()
        self._connections: list[sqlite3.Connection] = []
        self._lock = threading.Lock()
        self._write_lock = threading.RLock()

    # --- polaczenia -------------------------------------------------------

    @property
    def connection(self) -> sqlite3.Connection:
        """Polaczenie przypisane do biezacego watku."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = open_connection(self.path)
            self._local.conn = conn
            with self._lock:
                self._connections.append(conn)
        return conn

    def close(self) -> None:
        """Zamyka wszystkie otwarte polaczenia."""
        with self._lock:
            for conn in self._connections:
                # Blad zamkniecia polaczenia nie ma znaczenia: proces i tak konczy prace.
                with contextlib.suppress(sqlite3.Error):
                    conn.close()
            self._connections.clear()
        self._local = threading.local()

    # --- transakcje -------------------------------------------------------

    @contextmanager
    def transaction(self, *, immediate: bool = True) -> Iterator[sqlite3.Connection]:
        """Transakcja z blokada zapisu. Wycofuje zmiany przy wyjatku."""
        conn = self.connection
        with self._write_lock:
            conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            else:
                conn.execute("COMMIT")

    @contextmanager
    def savepoint(self, name: str = "sp") -> Iterator[sqlite3.Connection]:
        """Zagniezdzony punkt zapisu."""
        conn = self.connection
        safe = "".join(ch for ch in name if ch.isalnum() or ch == "_") or "sp"
        conn.execute(f"SAVEPOINT {safe}")
        try:
            yield conn
        except BaseException:
            conn.execute(f"ROLLBACK TO {safe}")
            conn.execute(f"RELEASE {safe}")
            raise
        else:
            conn.execute(f"RELEASE {safe}")

    # --- operacje pomocnicze ---------------------------------------------

    def execute(self, sql: str, params: object = ()) -> sqlite3.Cursor:
        return self.connection.execute(sql, params)  # type: ignore[arg-type]

    def query_one(self, sql: str, params: object = ()) -> sqlite3.Row | None:
        cur = self.connection.execute(sql, params)  # type: ignore[arg-type]
        row = cur.fetchone()
        cur.close()
        return row  # type: ignore[no-any-return]

    def query_all(self, sql: str, params: object = ()) -> list[sqlite3.Row]:
        cur = self.connection.execute(sql, params)  # type: ignore[arg-type]
        rows = cur.fetchall()
        cur.close()
        return rows

    def query_scalar(self, sql: str, params: object = (), default: Any = None) -> Any:
        row = self.query_one(sql, params)
        return default if row is None else row[0]

    # --- konserwacja ------------------------------------------------------

    def integrity_check(self) -> list[str]:
        """Uruchamia PRAGMA integrity_check. Pusta lista oznacza brak problemow."""
        rows = self.query_all("PRAGMA integrity_check")
        messages = [str(r[0]) for r in rows]
        return [] if messages == ["ok"] else messages

    def fts_integrity_check(self) -> list[str]:
        """Sprawdza spojnosc indeksu FTS5."""
        try:
            self.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('integrity-check')")
        except sqlite3.DatabaseError as exc:
            return [f"chunks_fts: {exc}"]
        return []

    def optimize(self) -> None:
        """Optymalizuje indeks FTS5 i statystyki planera."""
        with self._write_lock:
            try:
                self.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('optimize')")
            except sqlite3.DatabaseError as exc:
                log.warning("db.fts_optimize_failed", error=str(exc))
            self.execute("PRAGMA optimize")

    def vacuum(self) -> None:
        with self._write_lock:
            self.execute("VACUUM")

    def checkpoint(self) -> None:
        """Wymusza zrzut dziennika WAL do pliku glownego."""
        with self._write_lock:
            self.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def size_bytes(self) -> int:
        total = 0
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(self.path) + suffix)
            if candidate.exists():
                total += candidate.stat().st_size
        return total

    def require_healthy(self) -> None:
        """Rzuca wyjatek, gdy baza jest uszkodzona."""
        problems = self.integrity_check()
        if problems:
            raise IndexCorruptedError(
                "Plik indeksu jest uszkodzony. Wykonaj odbudowę indeksu.",
                details={"problems": problems[:5]},
            )


__all__ = ["CONNECTION_PRAGMAS", "Database", "check_fts5", "open_connection"]

"""Schemat bazy metadanych i indeksu pelnotekstowego.

Uwagi projektowe:

* Indeks FTS5 dziala w trybie ``external content`` nad tabela ``chunks``. Dzieki temu
  tekst jest przechowywany raz, a FTS trzyma wylacznie odwrocony indeks.
  Synchronizacje zapewniaja wyzwalacze, wiec kazda sciezka zapisu jest spojna.
* Kolumna ``folded`` zawiera tekst po zlozeniu znakow diakrytycznych. To ona jest
  indeksowana. Wyszukiwanie ``lodz`` i ``Lodz`` znajduje ten sam dokument.
  Pisownia oryginalna zostaje w kolumnie ``text`` i sluzy do prezentacji.
* Kolumna ``norm`` zawiera tokeny dat, kwot, numerow i identyfikatorow.
"""

from __future__ import annotations

import sqlite3

from finddocs.version import SCHEMA_VERSION

#: Tokenizator FTS5. Kolumna ``folded`` jest juz zlozona w kodzie aplikacji,
#: bo unicode61 nie usuwa polskiego ``l`` z kreska (to osobna litera alfabetu).
FTS_TOKENIZER = "unicode61 remove_diacritics 2 categories 'L* N* Co'"

SCHEMA_SQL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version     INTEGER PRIMARY KEY,
        applied_at  TEXT NOT NULL,
        description TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS index_meta (
        key   TEXT PRIMARY KEY,
        value TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sources (
        source_id          TEXT PRIMARY KEY,
        kind               TEXT NOT NULL,
        label              TEXT NOT NULL,
        location           TEXT NOT NULL,
        enabled            INTEGER NOT NULL DEFAULT 1,
        last_scan_at       TEXT,
        last_full_index_at TEXT,
        last_scan_id       INTEGER NOT NULL DEFAULT 0,
        delta_token        TEXT,
        created_at         TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS documents (
        doc_id                INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id             TEXT NOT NULL,
        external_id           TEXT NOT NULL,
        name                  TEXT NOT NULL,
        name_folded           TEXT NOT NULL DEFAULT '',
        logical_path          TEXT NOT NULL,
        path_folded           TEXT NOT NULL DEFAULT '',
        extension             TEXT NOT NULL DEFAULT '',
        mime_type             TEXT,
        size                  INTEGER,
        modified_at           TEXT,
        created_at            TEXT,
        indexed_at            TEXT,
        status                TEXT NOT NULL DEFAULT 'pending',
        change_key            TEXT,
        content_sha256        TEXT,
        etag                  TEXT,
        author                TEXT,
        title                 TEXT,
        web_url               TEXT,
        parent_url            TEXT,
        local_path            TEXT,
        library               TEXT,
        chunk_count           INTEGER NOT NULL DEFAULT 0,
        page_count            INTEGER,
        used_ocr              INTEGER NOT NULL DEFAULT 0,
        ocr_pages             INTEGER NOT NULL DEFAULT 0,
        ocr_confidence        REAL,
        text_origin           TEXT NOT NULL DEFAULT 'native',
        parser_name           TEXT,
        support_level         TEXT,
        error_code            TEXT,
        error_message         TEXT,
        vector_indexed        INTEGER NOT NULL DEFAULT 0,
        fts_indexed           INTEGER NOT NULL DEFAULT 0,
        normalization_version INTEGER NOT NULL DEFAULT 0,
        chunking_version      INTEGER NOT NULL DEFAULT 0,
        model_key             TEXT,
        attempt_count         INTEGER NOT NULL DEFAULT 0,
        last_attempt_at       TEXT,
        attachment_of         INTEGER REFERENCES documents(doc_id) ON DELETE CASCADE,
        seen_scan_id          INTEGER NOT NULL DEFAULT 0,
        UNIQUE (source_id, external_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status)",
    "CREATE INDEX IF NOT EXISTS idx_documents_source ON documents(source_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_documents_extension ON documents(extension)",
    "CREATE INDEX IF NOT EXISTS idx_documents_modified ON documents(modified_at)",
    "CREATE INDEX IF NOT EXISTS idx_documents_library ON documents(library)",
    "CREATE INDEX IF NOT EXISTS idx_documents_author ON documents(author)",
    "CREATE INDEX IF NOT EXISTS idx_documents_path ON documents(path_folded)",
    "CREATE INDEX IF NOT EXISTS idx_documents_scan ON documents(source_id, seen_scan_id)",
    "CREATE INDEX IF NOT EXISTS idx_documents_attachment ON documents(attachment_of)",
    """
    CREATE TABLE IF NOT EXISTS chunks (
        chunk_id       INTEGER PRIMARY KEY AUTOINCREMENT,
        doc_id         INTEGER NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
        ordinal        INTEGER NOT NULL,
        text           TEXT NOT NULL,
        folded         TEXT NOT NULL,
        norm           TEXT NOT NULL DEFAULT '',
        origin         TEXT NOT NULL DEFAULT 'native',
        ocr_confidence REAL,
        page           INTEGER,
        sheet          TEXT,
        row_start      INTEGER,
        row_end        INTEGER,
        heading        TEXT,
        section_kind   TEXT NOT NULL DEFAULT 'text',
        char_start     INTEGER NOT NULL DEFAULT 0,
        char_end       INTEGER NOT NULL DEFAULT 0,
        has_vector     INTEGER NOT NULL DEFAULT 0,
        UNIQUE (doc_id, ordinal)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id)",
    "CREATE INDEX IF NOT EXISTS idx_chunks_vector ON chunks(has_vector)",
    f"""
    CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
        folded,
        norm,
        content='chunks',
        content_rowid='chunk_id',
        tokenize="{FTS_TOKENIZER}"
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
        INSERT INTO chunks_fts(rowid, folded, norm)
        VALUES (new.chunk_id, new.folded, new.norm);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
        INSERT INTO chunks_fts(chunks_fts, rowid, folded, norm)
        VALUES ('delete', old.chunk_id, old.folded, old.norm);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
        INSERT INTO chunks_fts(chunks_fts, rowid, folded, norm)
        VALUES ('delete', old.chunk_id, old.folded, old.norm);
        INSERT INTO chunks_fts(rowid, folded, norm)
        VALUES (new.chunk_id, new.folded, new.norm);
    END
    """,
    """
    CREATE TABLE IF NOT EXISTS jobs (
        job_id       TEXT PRIMARY KEY,
        kind         TEXT NOT NULL,
        state        TEXT NOT NULL,
        source_ids   TEXT NOT NULL DEFAULT '',
        params       TEXT NOT NULL DEFAULT '{}',
        progress     TEXT NOT NULL DEFAULT '{}',
        created_at   TEXT NOT NULL,
        started_at   TEXT,
        finished_at  TEXT,
        updated_at   TEXT,
        error_code   TEXT,
        error_message TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state)",
    """
    CREATE TABLE IF NOT EXISTS scan_checkpoints (
        source_id        TEXT NOT NULL,
        job_id           TEXT NOT NULL,
        scan_id          INTEGER NOT NULL,
        cursor           TEXT,
        discovered       INTEGER NOT NULL DEFAULT 0,
        processed        INTEGER NOT NULL DEFAULT 0,
        discovery_done   INTEGER NOT NULL DEFAULT 0,
        updated_at       TEXT NOT NULL,
        PRIMARY KEY (source_id, job_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS error_log (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        source_id  TEXT,
        doc_id     INTEGER,
        file_name  TEXT,
        stage      TEXT NOT NULL,
        code       TEXT NOT NULL,
        exception  TEXT,
        message    TEXT,
        retryable  INTEGER NOT NULL DEFAULT 0
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_error_log_created ON error_log(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_error_log_code ON error_log(code)",
    """
    CREATE TABLE IF NOT EXISTS ocr_cache (
        content_sha256 TEXT NOT NULL,
        engine         TEXT NOT NULL,
        engine_version TEXT NOT NULL DEFAULT '',
        dpi            INTEGER NOT NULL DEFAULT 0,
        pages          INTEGER NOT NULL DEFAULT 0,
        confidence     REAL,
        text           TEXT NOT NULL,
        created_at     TEXT NOT NULL,
        PRIMARY KEY (content_sha256, engine, engine_version, dpi)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS scan_stats (
        source_id     TEXT NOT NULL,
        scan_id       INTEGER NOT NULL,
        started_at    TEXT NOT NULL,
        finished_at   TEXT,
        discovered    INTEGER NOT NULL DEFAULT 0,
        processed     INTEGER NOT NULL DEFAULT 0,
        unchanged     INTEGER NOT NULL DEFAULT 0,
        failed        INTEGER NOT NULL DEFAULT 0,
        deleted       INTEGER NOT NULL DEFAULT 0,
        complete      INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (source_id, scan_id)
    )
    """,
)


#: Klucze przechowywane w tabeli ``index_meta``.
META_SCHEMA_VERSION = "schema_version"
META_APP_VERSION = "app_version"
META_CREATED_AT = "created_at"
META_INDEX_COMPAT = "index_compat_hash"
META_VECTOR_COMPAT = "vector_compat_hash"
META_MODEL_KEY = "model_key"
META_MODEL_VERSION = "model_version"
META_EMBEDDING_DIM = "embedding_dim"
META_NORMALIZATION_VERSION = "normalization_version"
META_CHUNKING_VERSION = "chunking_version"
META_VECTOR_STORE_VERSION = "vector_store_version"
META_LAST_SCAN_AT = "last_scan_at"
META_LAST_FULL_INDEX_AT = "last_full_index_at"
META_LAST_SCAN_ID = "last_scan_id"


def create_schema(conn: sqlite3.Connection) -> None:
    """Tworzy pelny schemat. Operacja jest idempotentna."""
    for statement in SCHEMA_SQL:
        conn.execute(statement)


def current_schema_version(conn: sqlite3.Connection) -> int:
    """Zwraca wersje schematu zapisana w bazie, albo 0 dla nowej bazy."""
    try:
        row = conn.execute(
            "SELECT value FROM index_meta WHERE key = ?", (META_SCHEMA_VERSION,)
        ).fetchone()
    except sqlite3.OperationalError:
        return 0
    if row is None or row[0] is None:
        return 0
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return 0


__all__ = [
    "FTS_TOKENIZER",
    "META_APP_VERSION",
    "META_CHUNKING_VERSION",
    "META_CREATED_AT",
    "META_EMBEDDING_DIM",
    "META_INDEX_COMPAT",
    "META_LAST_FULL_INDEX_AT",
    "META_LAST_SCAN_AT",
    "META_LAST_SCAN_ID",
    "META_MODEL_KEY",
    "META_MODEL_VERSION",
    "META_NORMALIZATION_VERSION",
    "META_SCHEMA_VERSION",
    "META_VECTOR_COMPAT",
    "META_VECTOR_STORE_VERSION",
    "SCHEMA_SQL",
    "SCHEMA_VERSION",
    "create_schema",
    "current_schema_version",
]

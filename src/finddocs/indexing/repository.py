"""Dostep do metadanych: dokumenty, fragmenty, zadania, checkpointy, bledy.

Repozytorium jest jedynym miejscem, w ktorym pisze sie SQL dotyczacy metadanych.
Warstwy wyzsze operuja na typach z ``finddocs.types``.
"""

from __future__ import annotations

import datetime as _dt
import json
import sqlite3
from collections.abc import Iterable, Iterator
from dataclasses import asdict
from typing import Any

from finddocs.indexing.db import Database
from finddocs.indexing.schema import (
    META_LAST_FULL_INDEX_AT,
    META_LAST_SCAN_AT,
    META_LAST_SCAN_ID,
)
from finddocs.logging_setup import get_logger
from finddocs.normalization.text import fold_for_search
from finddocs.types import (
    Chunk,
    DocumentRecord,
    DocumentStatus,
    JobKind,
    JobState,
    NonSearchableDocument,
    ProgressSnapshot,
    SourceItem,
    SourceKind,
    SupportLevel,
    TextOrigin,
)

log = get_logger(__name__)


def to_iso(value: _dt.datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.astimezone()
    return value.isoformat()


def from_iso(value: str | None) -> _dt.datetime | None:
    if not value:
        return None
    try:
        return _dt.datetime.fromisoformat(value)
    except ValueError:
        return None


def now() -> _dt.datetime:
    return _dt.datetime.now().astimezone()


def _row_to_document(row: sqlite3.Row) -> DocumentRecord:
    return DocumentRecord(
        doc_id=int(row["doc_id"]),
        source_id=str(row["source_id"]),
        external_id=str(row["external_id"]),
        name=str(row["name"]),
        logical_path=str(row["logical_path"]),
        extension=str(row["extension"] or ""),
        mime_type=row["mime_type"],
        size=row["size"],
        modified_at=from_iso(row["modified_at"]),
        created_at=from_iso(row["created_at"]),
        indexed_at=from_iso(row["indexed_at"]),
        status=DocumentStatus(row["status"]),
        change_key=row["change_key"],
        content_sha256=row["content_sha256"],
        etag=row["etag"],
        author=row["author"],
        title=row["title"],
        web_url=row["web_url"],
        parent_url=row["parent_url"],
        local_path=row["local_path"],
        library=row["library"],
        chunk_count=int(row["chunk_count"] or 0),
        page_count=row["page_count"],
        used_ocr=bool(row["used_ocr"]),
        ocr_pages=int(row["ocr_pages"] or 0),
        ocr_confidence=row["ocr_confidence"],
        text_origin=TextOrigin(row["text_origin"] or "native"),
        parser_name=row["parser_name"],
        support_level=SupportLevel(row["support_level"] or "full"),
        error_code=row["error_code"],
        error_message=row["error_message"],
        vector_indexed=bool(row["vector_indexed"]),
        fts_indexed=bool(row["fts_indexed"]),
        normalization_version=int(row["normalization_version"] or 0),
        chunking_version=int(row["chunking_version"] or 0),
        model_key=row["model_key"],
        attachment_of=row["attachment_of"],
    )


class Repository:
    """Operacje na metadanych indeksu."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # --- metadane indeksu -------------------------------------------------

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self.db.query_one("SELECT value FROM index_meta WHERE key = ?", (key,))
        return default if row is None else row["value"]

    def set_meta(self, key: str, value: str | None) -> None:
        self.db.execute(
            "INSERT INTO index_meta(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def set_meta_many(self, values: dict[str, str | None]) -> None:
        for key, value in values.items():
            self.set_meta(key, value)

    def all_meta(self) -> dict[str, str | None]:
        return {r["key"]: r["value"] for r in self.db.query_all("SELECT key, value FROM index_meta")}

    def get_meta_int(self, key: str, default: int = 0) -> int:
        raw = self.get_meta(key)
        try:
            return int(raw) if raw is not None else default
        except ValueError:
            return default

    # --- zrodla -----------------------------------------------------------

    def upsert_source(
        self, source_id: str, kind: SourceKind, label: str, location: str, enabled: bool
    ) -> None:
        self.db.execute(
            """
            INSERT INTO sources(source_id, kind, label, location, enabled, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
                kind = excluded.kind,
                label = excluded.label,
                location = excluded.location,
                enabled = excluded.enabled
            """,
            (source_id, kind.value, label, location, int(enabled), to_iso(now())),
        )

    def delete_source(self, source_id: str) -> int:
        """Usuwa zrodlo wraz z jego dokumentami. Zwraca liczbe usunietych dokumentow."""
        count = int(
            self.db.query_scalar(
                "SELECT COUNT(*) FROM documents WHERE source_id = ?", (source_id,), 0
            )
        )
        self.db.execute("DELETE FROM documents WHERE source_id = ?", (source_id,))
        self.db.execute("DELETE FROM sources WHERE source_id = ?", (source_id,))
        self.db.execute("DELETE FROM scan_checkpoints WHERE source_id = ?", (source_id,))
        return count

    def next_scan_id(self) -> int:
        value = self.get_meta_int(META_LAST_SCAN_ID, 0) + 1
        self.set_meta(META_LAST_SCAN_ID, str(value))
        return value

    def mark_source_scanned(self, source_id: str, scan_id: int, *, full: bool) -> None:
        stamp = to_iso(now())
        self.db.execute(
            "UPDATE sources SET last_scan_at = ?, last_scan_id = ? WHERE source_id = ?",
            (stamp, scan_id, source_id),
        )
        if full:
            self.db.execute(
                "UPDATE sources SET last_full_index_at = ? WHERE source_id = ?",
                (stamp, source_id),
            )
            self.set_meta(META_LAST_FULL_INDEX_AT, stamp)
        self.set_meta(META_LAST_SCAN_AT, stamp)

    # --- dokumenty --------------------------------------------------------

    def get_document(self, doc_id: int) -> DocumentRecord | None:
        row = self.db.query_one("SELECT * FROM documents WHERE doc_id = ?", (doc_id,))
        return _row_to_document(row) if row else None

    def find_document(self, source_id: str, external_id: str) -> DocumentRecord | None:
        row = self.db.query_one(
            "SELECT * FROM documents WHERE source_id = ? AND external_id = ?",
            (source_id, external_id),
        )
        return _row_to_document(row) if row else None

    def get_documents(self, doc_ids: Iterable[int]) -> dict[int, DocumentRecord]:
        ids = list(doc_ids)
        if not ids:
            return {}
        placeholders = ",".join("?" * len(ids))
        rows = self.db.query_all(
            f"SELECT * FROM documents WHERE doc_id IN ({placeholders})",  # noqa: S608
            ids,
        )
        return {int(r["doc_id"]): _row_to_document(r) for r in rows}

    def register_item(self, item: SourceItem, scan_id: int, local_path: str | None = None) -> int:
        """Zapisuje lub odswieza rekord dokumentu wykrytego w zrodle.

        Zwraca ``doc_id``. Rekord istniejacy zachowuje swoj status, zeby wykrywanie
        zmian moglo porownac klucz zmiany przed decyzja o ponownym przetworzeniu.
        """
        existing = self.find_document(item.source_id, item.external_id)
        if existing is None:
            cursor = self.db.execute(
                """
                INSERT INTO documents(
                    source_id, external_id, name, name_folded, logical_path, path_folded,
                    extension, mime_type, size, modified_at, created_at, status,
                    change_key, etag, author, web_url, parent_url, local_path, library,
                    seen_scan_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.source_id,
                    item.external_id,
                    item.name,
                    fold_for_search(item.name),
                    item.logical_path,
                    fold_for_search(item.logical_path),
                    item.extension,
                    item.mime_type,
                    item.size,
                    to_iso(item.modified_at),
                    to_iso(item.created_at),
                    DocumentStatus.PENDING.value,
                    None,
                    item.etag,
                    item.author,
                    item.web_url,
                    item.parent_url,
                    local_path,
                    item.library,
                    scan_id,
                ),
            )
            return int(cursor.lastrowid or 0)

        self.db.execute(
            """
            UPDATE documents SET
                name = ?, name_folded = ?, logical_path = ?, path_folded = ?,
                extension = ?, mime_type = ?, size = ?, modified_at = ?, created_at = ?,
                etag = ?, author = ?, web_url = ?, parent_url = ?, local_path = ?,
                library = ?, seen_scan_id = ?
            WHERE doc_id = ?
            """,
            (
                item.name,
                fold_for_search(item.name),
                item.logical_path,
                fold_for_search(item.logical_path),
                item.extension,
                item.mime_type,
                item.size,
                to_iso(item.modified_at),
                to_iso(item.created_at),
                item.etag,
                item.author,
                item.web_url,
                item.parent_url,
                local_path,
                item.library,
                scan_id,
                existing.doc_id,
            ),
        )
        return existing.doc_id

    def needs_processing(
        self,
        doc_id: int,
        change_key: str,
        *,
        normalization_version: int,
        chunking_version: int,
        model_key: str | None,
        require_vectors: bool,
    ) -> bool:
        """Decyduje, czy dokument trzeba przetworzyc ponownie."""
        row = self.db.query_one(
            "SELECT status, change_key, normalization_version, chunking_version, "
            "model_key, vector_indexed, fts_indexed FROM documents WHERE doc_id = ?",
            (doc_id,),
        )
        if row is None:
            return True
        status = DocumentStatus(row["status"])
        if status is DocumentStatus.PENDING:
            return True
        if row["change_key"] != change_key:
            return True
        if int(row["normalization_version"] or 0) != normalization_version:
            return True
        if int(row["chunking_version"] or 0) != chunking_version:
            return True
        if not row["fts_indexed"] and status is DocumentStatus.INDEXED:
            return True
        if require_vectors and status in {DocumentStatus.INDEXED, DocumentStatus.PARTIAL}:
            if not row["vector_indexed"] or row["model_key"] != model_key:
                return True
        return False

    def mark_unchanged(self, doc_id: int, scan_id: int) -> None:
        self.db.execute(
            "UPDATE documents SET seen_scan_id = ? WHERE doc_id = ?",
            (scan_id, doc_id),
        )

    def set_document_status(
        self,
        doc_id: int,
        status: DocumentStatus,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
        increment_attempt: bool = False,
    ) -> None:
        self.db.execute(
            """
            UPDATE documents SET
                status = ?, error_code = ?, error_message = ?,
                last_attempt_at = ?,
                attempt_count = attempt_count + ?
            WHERE doc_id = ?
            """,
            (
                status.value,
                error_code,
                error_message,
                to_iso(now()),
                1 if increment_attempt else 0,
                doc_id,
            ),
        )

    def pending_documents(
        self, source_id: str | None = None, limit: int | None = None
    ) -> list[DocumentRecord]:
        sql = "SELECT * FROM documents WHERE status = ?"
        params: list[Any] = [DocumentStatus.PENDING.value]
        if source_id:
            sql += " AND source_id = ?"
            params.append(source_id)
        sql += " ORDER BY doc_id"
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        return [_row_to_document(r) for r in self.db.query_all(sql, params)]

    def stale_documents(self, source_id: str, scan_id: int) -> list[DocumentRecord]:
        """Dokumenty niewidziane w biezacym skanowaniu, czyli usuniete ze zrodla."""
        rows = self.db.query_all(
            "SELECT * FROM documents WHERE source_id = ? AND seen_scan_id < ? "
            "AND attachment_of IS NULL",
            (source_id, scan_id),
        )
        return [_row_to_document(r) for r in rows]

    def delete_document(self, doc_id: int) -> list[int]:
        """Usuwa dokument wraz z fragmentami. Zwraca identyfikatory usunietych wektorow."""
        chunk_ids = [
            int(r["chunk_id"])
            for r in self.db.query_all(
                "SELECT chunk_id FROM chunks WHERE doc_id = ? AND has_vector = 1", (doc_id,)
            )
        ]
        child_ids = [
            int(r["doc_id"])
            for r in self.db.query_all(
                "SELECT doc_id FROM documents WHERE attachment_of = ?", (doc_id,)
            )
        ]
        for child in child_ids:
            chunk_ids.extend(self.delete_document(child))
        self.db.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
        self.db.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
        return chunk_ids

    def delete_chunks(self, doc_id: int) -> list[int]:
        """Usuwa same fragmenty dokumentu. Zwraca identyfikatory usunietych wektorow."""
        chunk_ids = [
            int(r["chunk_id"])
            for r in self.db.query_all(
                "SELECT chunk_id FROM chunks WHERE doc_id = ? AND has_vector = 1", (doc_id,)
            )
        ]
        self.db.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
        self.db.execute("UPDATE documents SET chunk_count = 0 WHERE doc_id = ?", (doc_id,))
        return chunk_ids

    # --- fragmenty --------------------------------------------------------

    def insert_chunks(self, doc_id: int, chunks: Iterable[Chunk]) -> list[int]:
        """Wstawia fragmenty dokumentu. Zwraca nadane identyfikatory."""
        ids: list[int] = []
        for chunk in chunks:
            cursor = self.db.execute(
                """
                INSERT INTO chunks(
                    doc_id, ordinal, text, folded, norm, origin, ocr_confidence,
                    page, sheet, row_start, row_end, heading, section_kind,
                    char_start, char_end, has_vector
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    doc_id,
                    chunk.ordinal,
                    chunk.text,
                    chunk.folded_text,
                    chunk.normalized_tokens,
                    chunk.origin.value,
                    chunk.ocr_confidence,
                    chunk.page,
                    chunk.sheet,
                    chunk.row_start,
                    chunk.row_end,
                    chunk.heading,
                    chunk.section_kind,
                    chunk.char_start,
                    chunk.char_end,
                ),
            )
            ids.append(int(cursor.lastrowid or 0))
        return ids

    def mark_chunks_vectorized(self, chunk_ids: Iterable[int]) -> None:
        ids = list(chunk_ids)
        if not ids:
            return
        self.db.connection.executemany(
            "UPDATE chunks SET has_vector = 1 WHERE chunk_id = ?",
            [(i,) for i in ids],
        )

    def chunk_texts(self, chunk_ids: Iterable[int]) -> dict[int, sqlite3.Row]:
        ids = list(chunk_ids)
        if not ids:
            return {}
        placeholders = ",".join("?" * len(ids))
        rows = self.db.query_all(
            f"SELECT * FROM chunks WHERE chunk_id IN ({placeholders})",  # noqa: S608
            ids,
        )
        return {int(r["chunk_id"]): r for r in rows}

    def iter_chunks_without_vectors(self, batch: int = 256) -> Iterator[list[sqlite3.Row]]:
        """Iteruje po fragmentach, ktore nie maja jeszcze wektora."""
        last = 0
        while True:
            rows = self.db.query_all(
                "SELECT chunk_id, doc_id, text FROM chunks "
                "WHERE has_vector = 0 AND chunk_id > ? ORDER BY chunk_id LIMIT ?",
                (last, batch),
            )
            if not rows:
                return
            last = int(rows[-1]["chunk_id"])
            yield rows

    def count_chunks(self) -> int:
        return int(self.db.query_scalar("SELECT COUNT(*) FROM chunks", (), 0))

    def count_vectors(self) -> int:
        return int(self.db.query_scalar("SELECT COUNT(*) FROM chunks WHERE has_vector = 1", (), 0))

    # --- finalizacja dokumentu -------------------------------------------

    def finalize_document(
        self,
        doc_id: int,
        *,
        status: DocumentStatus,
        chunk_count: int,
        page_count: int | None,
        used_ocr: bool,
        ocr_pages: int,
        ocr_confidence: float | None,
        text_origin: TextOrigin,
        parser_name: str | None,
        support_level: SupportLevel,
        content_sha256: str | None,
        change_key: str,
        normalization_version: int,
        chunking_version: int,
        model_key: str | None,
        title: str | None,
        author: str | None,
        fts_indexed: bool,
        vector_indexed: bool,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        self.db.execute(
            """
            UPDATE documents SET
                status = ?, chunk_count = ?, page_count = ?, used_ocr = ?, ocr_pages = ?,
                ocr_confidence = ?, text_origin = ?, parser_name = ?, support_level = ?,
                content_sha256 = ?, change_key = ?, normalization_version = ?,
                chunking_version = ?, model_key = ?, indexed_at = ?,
                title = COALESCE(?, title), author = COALESCE(?, author),
                fts_indexed = ?, vector_indexed = ?, error_code = ?, error_message = ?,
                last_attempt_at = ?, attempt_count = attempt_count + 1
            WHERE doc_id = ?
            """,
            (
                status.value,
                chunk_count,
                page_count,
                int(used_ocr),
                ocr_pages,
                ocr_confidence,
                text_origin.value,
                parser_name,
                support_level.value,
                content_sha256,
                change_key,
                normalization_version,
                chunking_version,
                model_key,
                to_iso(now()),
                title,
                author,
                int(fts_indexed),
                int(vector_indexed),
                error_code,
                error_message,
                to_iso(now()),
                doc_id,
            ),
        )

    def create_attachment_document(
        self,
        parent: DocumentRecord,
        name: str,
        mime_type: str | None,
        scan_id: int,
    ) -> int:
        external_id = f"{parent.external_id}#att:{name}"
        existing = self.find_document(parent.source_id, external_id)
        if existing is not None:
            self.db.execute(
                "UPDATE documents SET seen_scan_id = ?, status = ? WHERE doc_id = ?",
                (scan_id, DocumentStatus.PENDING.value, existing.doc_id),
            )
            return existing.doc_id
        logical = f"{parent.logical_path} :: {name}"
        cursor = self.db.execute(
            """
            INSERT INTO documents(
                source_id, external_id, name, name_folded, logical_path, path_folded,
                extension, mime_type, size, modified_at, status, web_url, parent_url,
                library, attachment_of, seen_scan_id, local_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                parent.source_id,
                external_id,
                name,
                fold_for_search(name),
                logical,
                fold_for_search(logical),
                ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else "",
                mime_type,
                None,
                to_iso(parent.modified_at),
                DocumentStatus.PENDING.value,
                parent.web_url,
                parent.parent_url,
                parent.library,
                parent.doc_id,
                scan_id,
                parent.local_path,
            ),
        )
        return int(cursor.lastrowid or 0)

    # --- bledy ------------------------------------------------------------

    def log_error(
        self,
        *,
        stage: str,
        code: str,
        source_id: str | None = None,
        doc_id: int | None = None,
        file_name: str | None = None,
        exception: str | None = None,
        message: str | None = None,
        retryable: bool = False,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO error_log(
                created_at, source_id, doc_id, file_name, stage, code,
                exception, message, retryable
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                to_iso(now()),
                source_id,
                doc_id,
                file_name,
                stage,
                code,
                exception,
                message,
                int(retryable),
            ),
        )

    def recent_errors(self, limit: int = 200) -> list[sqlite3.Row]:
        return self.db.query_all(
            "SELECT * FROM error_log ORDER BY id DESC LIMIT ?",
            (limit,),
        )

    def error_counts(self) -> dict[str, int]:
        rows = self.db.query_all("SELECT code, COUNT(*) AS n FROM error_log GROUP BY code")
        return {str(r["code"]): int(r["n"]) for r in rows}

    def clear_errors(self) -> None:
        self.db.execute("DELETE FROM error_log")

    # --- zadania ----------------------------------------------------------

    def create_job(
        self, job_id: str, kind: JobKind, source_ids: list[str], params: dict[str, Any]
    ) -> None:
        self.db.execute(
            """
            INSERT INTO jobs(job_id, kind, state, source_ids, params, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                state = excluded.state, params = excluded.params, updated_at = excluded.updated_at
            """,
            (
                job_id,
                kind.value,
                JobState.QUEUED.value,
                ",".join(source_ids),
                json.dumps(params, ensure_ascii=False),
                to_iso(now()),
                to_iso(now()),
            ),
        )

    def update_job_state(
        self,
        job_id: str,
        state: JobState,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        stamp = to_iso(now())
        started = stamp if state is JobState.RUNNING else None
        finished = (
            stamp
            if state in {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED}
            else None
        )
        self.db.execute(
            """
            UPDATE jobs SET
                state = ?, updated_at = ?,
                started_at = COALESCE(started_at, ?),
                finished_at = COALESCE(?, finished_at),
                error_code = COALESCE(?, error_code),
                error_message = COALESCE(?, error_message)
            WHERE job_id = ?
            """,
            (state.value, stamp, started, finished, error_code, error_message, job_id),
        )

    def save_progress(self, job_id: str, snapshot: ProgressSnapshot) -> None:
        payload = asdict(snapshot)
        payload["kind"] = snapshot.kind.value
        payload["state"] = snapshot.state.value
        payload["started_at"] = to_iso(snapshot.started_at)
        payload["updated_at"] = to_iso(snapshot.updated_at)
        self.db.execute(
            "UPDATE jobs SET progress = ?, updated_at = ? WHERE job_id = ?",
            (json.dumps(payload, ensure_ascii=False), to_iso(now()), job_id),
        )

    def get_job(self, job_id: str) -> sqlite3.Row | None:
        return self.db.query_one("SELECT * FROM jobs WHERE job_id = ?", (job_id,))

    def resumable_jobs(self) -> list[sqlite3.Row]:
        """Zadania przerwane przez zamkniecie aplikacji albo restart systemu."""
        return self.db.query_all(
            "SELECT * FROM jobs WHERE state IN (?, ?, ?) ORDER BY created_at DESC",
            (JobState.RUNNING.value, JobState.PAUSED.value, JobState.QUEUED.value),
        )

    def recent_jobs(self, limit: int = 20) -> list[sqlite3.Row]:
        return self.db.query_all("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))

    # --- checkpointy ------------------------------------------------------

    def save_checkpoint(
        self,
        source_id: str,
        job_id: str,
        scan_id: int,
        cursor: str | None,
        discovered: int,
        processed: int,
        discovery_done: bool,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO scan_checkpoints(
                source_id, job_id, scan_id, cursor, discovered, processed,
                discovery_done, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id, job_id) DO UPDATE SET
                scan_id = excluded.scan_id,
                cursor = excluded.cursor,
                discovered = excluded.discovered,
                processed = excluded.processed,
                discovery_done = excluded.discovery_done,
                updated_at = excluded.updated_at
            """,
            (
                source_id,
                job_id,
                scan_id,
                cursor,
                discovered,
                processed,
                int(discovery_done),
                to_iso(now()),
            ),
        )

    def get_checkpoint(self, source_id: str, job_id: str) -> sqlite3.Row | None:
        return self.db.query_one(
            "SELECT * FROM scan_checkpoints WHERE source_id = ? AND job_id = ?",
            (source_id, job_id),
        )

    def clear_checkpoint(self, source_id: str, job_id: str) -> None:
        self.db.execute(
            "DELETE FROM scan_checkpoints WHERE source_id = ? AND job_id = ?",
            (source_id, job_id),
        )

    # --- statystyki -------------------------------------------------------

    def status_counts(self) -> dict[str, int]:
        rows = self.db.query_all(
            "SELECT status, COUNT(*) AS n FROM documents GROUP BY status",
        )
        return {str(r["status"]): int(r["n"]) for r in rows}

    def extension_counts(self) -> dict[str, int]:
        rows = self.db.query_all(
            "SELECT extension, COUNT(*) AS n FROM documents GROUP BY extension ORDER BY n DESC",
        )
        return {str(r["extension"] or "(brak)"): int(r["n"]) for r in rows}

    def parser_error_counts(self) -> dict[str, int]:
        rows = self.db.query_all(
            "SELECT COALESCE(error_code, 'brak') AS code, COUNT(*) AS n FROM documents "
            "WHERE error_code IS NOT NULL GROUP BY error_code ORDER BY n DESC",
        )
        return {str(r["code"]): int(r["n"]) for r in rows}

    def ocr_stats(self) -> tuple[int, int]:
        row = self.db.query_one(
            "SELECT COUNT(*) AS docs, COALESCE(SUM(ocr_pages), 0) AS pages "
            "FROM documents WHERE used_ocr = 1"
        )
        if row is None:
            return 0, 0
        return int(row["docs"]), int(row["pages"])

    def non_searchable_documents(self, limit: int = 5000) -> list[NonSearchableDocument]:
        rows = self.db.query_all(
            """
            SELECT doc_id, name, logical_path, status, error_code, error_message, extension
            FROM documents
            WHERE status NOT IN ('indexed', 'partial')
            ORDER BY status, name
            LIMIT ?
            """,
            (limit,),
        )
        return [
            NonSearchableDocument(
                doc_id=int(r["doc_id"]),
                name=str(r["name"]),
                logical_path=str(r["logical_path"]),
                status=DocumentStatus(r["status"]),
                error_code=r["error_code"],
                error_message=r["error_message"],
                extension=str(r["extension"] or ""),
            )
            for r in rows
        ]

    def distinct_values(self, column: str, limit: int = 500) -> list[str]:
        """Unikalne wartosci kolumny dokumentu, uzywane do wypelnienia filtrow."""
        allowed = {"extension", "author", "library", "source_id"}
        if column not in allowed:
            raise ValueError(f"Kolumna {column} nie jest dozwolona w filtrach.")
        rows = self.db.query_all(
            f"SELECT DISTINCT {column} AS v FROM documents "  # noqa: S608
            f"WHERE {column} IS NOT NULL AND {column} <> '' ORDER BY v LIMIT ?",
            (limit,),
        )
        return [str(r["v"]) for r in rows]

    # --- cache OCR --------------------------------------------------------

    def get_ocr_cache(
        self, content_sha256: str, engine: str, engine_version: str, dpi: int
    ) -> sqlite3.Row | None:
        return self.db.query_one(
            "SELECT * FROM ocr_cache WHERE content_sha256 = ? AND engine = ? "
            "AND engine_version = ? AND dpi = ?",
            (content_sha256, engine, engine_version, dpi),
        )

    def put_ocr_cache(
        self,
        content_sha256: str,
        engine: str,
        engine_version: str,
        dpi: int,
        pages: int,
        confidence: float | None,
        text: str,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO ocr_cache(
                content_sha256, engine, engine_version, dpi, pages, confidence, text, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(content_sha256, engine, engine_version, dpi) DO UPDATE SET
                pages = excluded.pages, confidence = excluded.confidence,
                text = excluded.text, created_at = excluded.created_at
            """,
            (
                content_sha256,
                engine,
                engine_version,
                dpi,
                pages,
                confidence,
                text,
                to_iso(now()),
            ),
        )

    def clear_ocr_cache(self) -> int:
        count = int(self.db.query_scalar("SELECT COUNT(*) FROM ocr_cache", (), 0))
        self.db.execute("DELETE FROM ocr_cache")
        return count


__all__ = ["Repository", "from_iso", "now", "to_iso"]

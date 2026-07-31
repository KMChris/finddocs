"""Przetwarzanie pojedynczego dokumentu.

Przeplyw jest zgodny z wymaganiem, zeby nigdy nie trzymac calego zbioru na dysku:

1. pobierz metadane (juz sa w ``SourceItem``);
2. sprawdz, czy dokument sie zmienil;
3. pobierz pojedynczy plik do przestrzeni tymczasowej;
4. wyodrebnij tekst;
5. uruchom OCR tylko, gdy jest potrzebny;
6. znormalizuj i podziel na fragmenty;
7. policz embeddingi;
8. zaktualizuj indeks w jednej transakcji;
9. usun plik tymczasowy, takze po bledzie.

Blad jednego dokumentu nigdy nie zatrzymuje calego procesu. Kazdy przypadek konczy
sie zapisaniem statusu, dzieki czemu raport pokrycia widzi wszystko, co sie nie udalo.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from finddocs.chunking import ChunkingConfig, chunk_document
from finddocs.config import AppConfig
from finddocs.connectors.base import SourceConnector
from finddocs.errors import (
    CorruptedFileError,
    DownloadError,
    EmptyDocumentError,
    ExtractionError,
    ExtractionTimeoutError,
    FindDocsError,
    JobCancelledError,
    OcrCancelledError,
    OcrEngineUnavailableError,
    OcrError,
    PasswordProtectedError,
    StorageSpaceError,
    TransientConnectorError,
    UnsupportedFormatError,
)
from finddocs.extractors.base import ExtractionContext
from finddocs.extractors.detect import FileTypeInfo, detect_file_type
from finddocs.extractors.registry import ExtractorRegistry
from finddocs.indexing.service import IndexService
from finddocs.indexing.writer import DocumentPayload
from finddocs.jobs.control import JobControl, RetryPolicy
from finddocs.logging_setup import get_logger
from finddocs.ocr.detector import decide as decide_ocr
from finddocs.ocr.detector import pages_needing_ocr
from finddocs.ocr.service import OcrService
from finddocs.types import (
    Chunk,
    DocumentRecord,
    DocumentStatus,
    ExtractedSection,
    ExtractionResult,
    SourceItem,
    SupportLevel,
    TextOrigin,
)

log = get_logger(__name__)

#: Mapowanie wyjatkow ekstrakcji na status dokumentu.
STATUS_BY_ERROR: dict[type[Exception], DocumentStatus] = {
    UnsupportedFormatError: DocumentStatus.UNSUPPORTED,
    CorruptedFileError: DocumentStatus.CORRUPTED,
    PasswordProtectedError: DocumentStatus.PASSWORD_PROTECTED,
    EmptyDocumentError: DocumentStatus.EMPTY,
    DownloadError: DocumentStatus.DOWNLOAD_FAILED,
    ExtractionTimeoutError: DocumentStatus.ERROR,
}


@dataclass(slots=True)
class DocumentOutcome:
    """Wynik przetworzenia jednego dokumentu."""

    doc_id: int
    status: DocumentStatus
    chunks: int = 0
    used_ocr: bool = False
    ocr_pages: int = 0
    bytes_processed: int = 0
    error_code: str | None = None
    error_message: str | None = None
    warnings: list[str] = field(default_factory=list)
    skipped_unchanged: bool = False

    @property
    def is_success(self) -> bool:
        return self.status in {DocumentStatus.INDEXED, DocumentStatus.PARTIAL}


class DocumentPipeline:
    """Przetwarza pojedyncze dokumenty i zapisuje je do indeksu."""

    def __init__(
        self,
        config: AppConfig,
        index: IndexService,
        registry: ExtractorRegistry,
        ocr: OcrService,
    ) -> None:
        self.config = config
        self.index = index
        self.registry = registry
        self.ocr = ocr
        self.retry = RetryPolicy(
            max_attempts=config.indexing.max_retries_per_document,
            base_delay=config.indexing.retry_backoff_seconds,
            max_delay=config.indexing.retry_backoff_max_seconds,
        )
        self._chunk_config = ChunkingConfig(
            target_chars=config.chunking.target_chars,
            overlap_chars=config.chunking.overlap_chars,
            min_chars=config.chunking.min_chars,
            max_chars=config.chunking.max_chars,
            table_rows_per_chunk=config.chunking.table_rows_per_chunk,
            table_include_header=config.chunking.table_include_header,
            max_chunks=config.chunking.max_chunks_per_document,
        )

    # --- wejscie ----------------------------------------------------------

    def process(
        self,
        connector: SourceConnector,
        item: SourceItem,
        doc_id: int,
        *,
        workspace: Path,
        control: JobControl,
        scan_id: int,
    ) -> DocumentOutcome:
        """Przetwarza dokument. Nie rzuca wyjatkow poza anulowaniem."""
        control.checkpoint()
        record = self.index.repository.get_document(doc_id)
        if record is None:
            return DocumentOutcome(doc_id=doc_id, status=DocumentStatus.ERROR)

        if item.extra.get("too_large"):
            self._fail(
                doc_id,
                DocumentStatus.SKIPPED,
                "FD-1006",
                f"Plik przekracza limit {self.config.indexing.max_file_size_mb} MB.",
                stage="scan",
                item=item,
            )
            return DocumentOutcome(doc_id=doc_id, status=DocumentStatus.SKIPPED)

        temp_dir = workspace / f"doc-{doc_id}"
        try:
            fetched = self._download(connector, item, temp_dir, control)
        except JobCancelledError:
            raise
        except StorageSpaceError:
            raise
        except FindDocsError as exc:
            self._fail(
                doc_id,
                DocumentStatus.DOWNLOAD_FAILED,
                exc.code,
                exc.user_message,
                stage="download",
                item=item,
                retryable=isinstance(exc, TransientConnectorError),
            )
            return DocumentOutcome(
                doc_id=doc_id,
                status=DocumentStatus.DOWNLOAD_FAILED,
                error_code=exc.code,
                error_message=exc.user_message,
            )

        try:
            return self._process_file(
                record=record,
                item=item,
                path=fetched.path,
                content_sha256=fetched.sha256,
                size=fetched.size,
                control=control,
                scan_id=scan_id,
                workspace=workspace,
            )
        except (JobCancelledError, StorageSpaceError):
            raise
        except FindDocsError as exc:
            status = STATUS_BY_ERROR.get(type(exc), DocumentStatus.ERROR)
            self._fail(doc_id, status, exc.code, exc.user_message, stage="process", item=item)
            return DocumentOutcome(
                doc_id=doc_id,
                status=status,
                error_code=exc.code,
                error_message=exc.user_message,
            )
        except Exception as exc:  # noqa: BLE001 - blad jednego pliku nie konczy zadania
            log.error(
                "pipeline.unexpected_error", doc_id=doc_id, error_type=type(exc).__name__
            )
            message = f"Nieoczekiwany blad przetwarzania: {type(exc).__name__}."
            self._fail(doc_id, DocumentStatus.ERROR, "FD-3000", message, stage="process", item=item)
            return DocumentOutcome(
                doc_id=doc_id,
                status=DocumentStatus.ERROR,
                error_code="FD-3000",
                error_message=message,
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    # --- kroki ------------------------------------------------------------

    def _download(
        self,
        connector: SourceConnector,
        item: SourceItem,
        destination: Path,
        control: JobControl,
    ) -> object:
        destination.mkdir(parents=True, exist_ok=True)
        last: Exception | None = None
        for attempt in range(1, max(1, self.retry.max_attempts) + 1):
            control.checkpoint()
            try:
                return connector.fetch(item, destination, cancel=control)
            except TransientConnectorError as exc:
                last = exc
                log.warning(
                    "pipeline.download_retry",
                    attempt=attempt,
                    file_name=item.name,
                    code=exc.code,
                )
                self.retry.sleep(attempt + 1, control)
            except FindDocsError:
                raise
            except OSError as exc:
                last = exc
                self.retry.sleep(attempt + 1, control)
        raise DownloadError(
            "Nie udalo sie pobrac pliku po kilku probach.",
            details={"file_name": item.name},
            cause=last,
        )

    def _process_file(
        self,
        *,
        record: DocumentRecord,
        item: SourceItem,
        path: Path,
        content_sha256: str,
        size: int,
        control: JobControl,
        scan_id: int,
        workspace: Path,
    ) -> DocumentOutcome:
        doc_id = record.doc_id
        context = ExtractionContext(
            max_bytes=self.config.indexing.max_file_size_mb * 1024 * 1024,
            timeout_seconds=self.config.indexing.extraction_timeout_seconds,
            cancel=control,
            office_com_enabled=self.config.indexing.office_com_enabled,
            office_com_timeout_seconds=self.config.indexing.office_com_timeout_seconds,
        )

        info = detect_file_type(path, declared_mime=item.mime_type, file_name=item.name)
        result: ExtractionResult | None = None
        extraction_error: FindDocsError | None = None
        try:
            result, info = self.registry.extract(
                path, context, declared_mime=item.mime_type, file_name=item.name
            )
        except JobCancelledError:
            raise
        except FindDocsError as exc:
            extraction_error = exc
        except Exception as exc:  # noqa: BLE001 - parser moze zglosic dowolny blad
            extraction_error = ExtractionError(
                "Parser zakonczyl prace nieoczekiwanym bledem.", cause=exc
            )

        warnings: list[str] = list(result.warnings) if result else []
        decision = decide_ocr(
            result,
            info,
            self.config.ocr,
            extraction_failed=extraction_error is not None,
        )

        ocr_pages = 0
        ocr_confidence: float | None = None
        origin = result.origin if result else TextOrigin.NATIVE
        sections: list[ExtractedSection] = list(result.sections) if result else []

        if decision.needed:
            control.checkpoint()
            try:
                ocr_sections, ocr_pages, ocr_confidence, ocr_warnings = self._run_ocr(
                    path=path,
                    info=info,
                    result=result,
                    content_sha256=content_sha256,
                    control=control,
                )
                warnings.extend(ocr_warnings)
                if ocr_sections:
                    if sections:
                        sections = _merge_sections(sections, ocr_sections)
                        origin = TextOrigin.MIXED
                    else:
                        sections = ocr_sections
                        origin = TextOrigin.OCR
            except (JobCancelledError, OcrCancelledError) as exc:
                raise JobCancelledError() from exc
            except OcrEngineUnavailableError as exc:
                warnings.append(exc.user_message)
                log.warning("pipeline.ocr_unavailable", doc_id=doc_id)
            except FindDocsError as exc:
                # Tu trafiaja takze bledy rasteryzacji, np. uszkodzony plik PDF,
                # ktorego nie da sie otworzyc. Nie moga zatrzymac calego zadania.
                warnings.append(f"OCR nie powiodl sie: {exc.user_message}")
                if extraction_error is None:
                    extraction_error = exc
                log.warning("pipeline.ocr_failed", doc_id=doc_id, code=exc.code)
            except Exception as exc:  # noqa: BLE001 - silnik OCR moze zglosic dowolny blad
                warnings.append("OCR nie powiodl sie z powodu nieoczekiwanego bledu.")
                log.warning("pipeline.ocr_crashed", doc_id=doc_id, error_type=type(exc).__name__)

        if not sections:
            status, code, message = self._classify_failure(extraction_error, decision.describe())
            self._fail(doc_id, status, code, message, stage="extract", item=item)
            return DocumentOutcome(
                doc_id=doc_id,
                status=status,
                error_code=code,
                error_message=message,
                used_ocr=ocr_pages > 0,
                ocr_pages=ocr_pages,
                bytes_processed=size,
                warnings=warnings,
            )

        control.checkpoint()
        chunks = chunk_document(sections, self._chunk_config, extension=item.extension)
        if not chunks:
            self._fail(
                doc_id,
                DocumentStatus.EMPTY,
                "FD-3004",
                "Dokument nie zawiera tresci mozliwej do zaindeksowania.",
                stage="chunk",
                item=item,
            )
            return DocumentOutcome(
                doc_id=doc_id, status=DocumentStatus.EMPTY, bytes_processed=size
            )

        embeddings = self._embed(chunks, control)
        metadata = result.metadata if result else None
        payload = DocumentPayload(
            doc_id=doc_id,
            chunks=chunks,
            change_key=item.change_key(),
            content_sha256=content_sha256,
            page_count=(metadata.page_count if metadata else None)
            or (result.total_pages if result else None),
            used_ocr=ocr_pages > 0,
            ocr_pages=ocr_pages,
            ocr_confidence=ocr_confidence,
            text_origin=origin,
            parser_name=result.parser_name if result else "ocr",
            support_level=result.support_level if result else SupportLevel.LIMITED,
            title=(metadata.title if metadata else None) or None,
            author=(metadata.author if metadata else None) or item.author,
            embeddings=embeddings,
            model_key=self.index.provider.info.model_key if self.index.provider else None,
            warnings=warnings,
        )
        write = self.index.writer.write_document(payload)

        attachments = result.attachments if result else []
        if attachments and self.config.indexing.office_com_enabled is not None:
            self._process_attachments(
                record=record,
                attachments=attachments,
                workspace=workspace,
                control=control,
                scan_id=scan_id,
            )

        for warning in warnings[:5]:
            self.index.repository.log_error(
                stage="warning",
                code="FD-0100",
                doc_id=doc_id,
                file_name=item.name,
                source_id=item.source_id,
                message=warning,
                retryable=False,
            )

        return DocumentOutcome(
            doc_id=doc_id,
            status=write.status,
            chunks=write.chunk_count,
            used_ocr=ocr_pages > 0,
            ocr_pages=ocr_pages,
            bytes_processed=size,
            warnings=warnings,
        )

    def _run_ocr(
        self,
        *,
        path: Path,
        info: FileTypeInfo,
        result: ExtractionResult | None,
        content_sha256: str,
        control: JobControl,
    ) -> tuple[list[ExtractedSection], int, float | None, list[str]]:
        pages: list[int] | None = None
        if result is not None and info.mime_type == "application/pdf" and result.total_pages:
            candidates = pages_needing_ocr(
                result, self.config.ocr, total_pages=result.total_pages
            )
            pages = candidates or None
        ocr_result = self.ocr.run(
            path, info, content_sha256=content_sha256, pages=pages, cancel=control
        )
        sections = self.ocr.to_sections(ocr_result)
        return sections, ocr_result.page_count, ocr_result.confidence, ocr_result.warnings

    def _embed(self, chunks: list[Chunk], control: JobControl):  # type: ignore[no-untyped-def]
        if not self.index.semantic_available or self.index.provider is None:
            return None
        control.checkpoint()
        try:
            return self.index.provider.embed_passages(
                [chunk.text for chunk in chunks], cancel=control
            )
        except JobCancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - brak wektorow nie blokuje indeksowania
            log.warning("pipeline.embedding_failed", error_type=type(exc).__name__)
            return None

    def _process_attachments(
        self,
        *,
        record: DocumentRecord,
        attachments: list[object],
        workspace: Path,
        control: JobControl,
        scan_id: int,
    ) -> None:
        """Indeksuje zalaczniki wiadomosci jako osobne dokumenty podrzedne."""
        for attachment in attachments:
            control.checkpoint()
            name = getattr(attachment, "name", "")
            data = getattr(attachment, "data", b"")
            mime = getattr(attachment, "mime_type", None)
            if not name or not data:
                continue
            child_id = self.index.repository.create_attachment_document(
                record, name, mime, scan_id
            )
            child_dir = workspace / f"att-{child_id}"
            child_dir.mkdir(parents=True, exist_ok=True)
            safe_name = _safe_filename(name)
            target = child_dir / safe_name
            try:
                target.write_bytes(data)
                child_record = self.index.repository.get_document(child_id)
                if child_record is None:
                    continue
                child_item = SourceItem(
                    source_id=record.source_id,
                    external_id=child_record.external_id,
                    name=name,
                    logical_path=child_record.logical_path,
                    size=len(data),
                    modified_at=record.modified_at,
                    mime_type=mime,
                    web_url=record.web_url,
                    parent_url=record.parent_url,
                    library=record.library,
                )
                import hashlib

                digest = hashlib.sha256(data).hexdigest()
                self._process_file(
                    record=child_record,
                    item=child_item,
                    path=target,
                    content_sha256=digest,
                    size=len(data),
                    control=control,
                    scan_id=scan_id,
                    workspace=child_dir,
                )
            except JobCancelledError:
                raise
            except FindDocsError as exc:
                self._fail(
                    child_id,
                    STATUS_BY_ERROR.get(type(exc), DocumentStatus.ERROR),
                    exc.code,
                    exc.user_message,
                    stage="attachment",
                    item=None,
                    file_name=name,
                    source_id=record.source_id,
                )
            except Exception as exc:  # noqa: BLE001
                self._fail(
                    child_id,
                    DocumentStatus.ERROR,
                    "FD-3000",
                    f"Nie udalo sie przetworzyc zalacznika: {type(exc).__name__}.",
                    stage="attachment",
                    item=None,
                    file_name=name,
                    source_id=record.source_id,
                )
            finally:
                shutil.rmtree(child_dir, ignore_errors=True)

    # --- pomocnicze -------------------------------------------------------

    def _classify_failure(
        self, error: FindDocsError | None, ocr_detail: str
    ) -> tuple[DocumentStatus, str, str]:
        if error is not None:
            status = STATUS_BY_ERROR.get(type(error), DocumentStatus.ERROR)
            return status, error.code, error.user_message
        return (
            DocumentStatus.EMPTY,
            "FD-3004",
            f"Nie udalo sie odczytac tresci dokumentu. {ocr_detail}".strip(),
        )

    def _fail(
        self,
        doc_id: int,
        status: DocumentStatus,
        code: str,
        message: str,
        *,
        stage: str,
        item: SourceItem | None,
        retryable: bool = False,
        file_name: str | None = None,
        source_id: str | None = None,
    ) -> None:
        self.index.writer.mark_failed(
            doc_id,
            status,
            error_code=code,
            error_message=message,
            stage=stage,
            file_name=file_name or (item.name if item else None),
            source_id=source_id or (item.source_id if item else None),
            retryable=retryable,
        )


def _merge_sections(
    native: list[ExtractedSection], ocr: list[ExtractedSection]
) -> list[ExtractedSection]:
    """Laczy sekcje natywne i z OCR, unikajac podwojenia tych samych stron."""
    ocr_pages = {section.page for section in ocr if section.page is not None}
    merged = [s for s in native if s.page is None or s.page not in ocr_pages]
    merged.extend(ocr)
    merged.sort(key=lambda s: (s.page if s.page is not None else 0, s.order))
    for index, section in enumerate(merged):
        section.order = index
    return merged


def _safe_filename(name: str) -> str:
    """Nazwa pliku bezpieczna dla systemu Windows."""
    invalid = '<>:"/\\|?*'
    cleaned = "".join("_" if ch in invalid or ord(ch) < 32 else ch for ch in name).strip()
    cleaned = cleaned.rstrip(". ") or "zalacznik"
    if len(cleaned) > 120:
        stem = Path(cleaned).stem[:100]
        suffix = Path(cleaned).suffix[:16]
        cleaned = f"{stem}{suffix}"
    return cleaned


__all__ = ["STATUS_BY_ERROR", "DocumentOutcome", "DocumentPipeline"]

"""Zadanie indeksowania: przejscie po zrodlach, checkpointy, wykrywanie zmian.

Zadanie nie pobiera calego zbioru z gory. Enumeracja i przetwarzanie sa
przeplecione: pierwszy dokument jest indeksowany, zanim konektor skonczy
wyliczac reszte. Postep jest zapisywany do bazy co kilkanascie dokumentow,
wiec zamkniecie aplikacji albo restart systemu kosztuje najwyzej te kilkanascie.
"""

from __future__ import annotations

import datetime as _dt
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from finddocs.app_paths import AppPaths
from finddocs.config import AppConfig, SourceConfig
from finddocs.connectors.base import ScanCursor, SourceConnector
from finddocs.errors import (
    FindDocsError,
    JobCancelledError,
    SourceUnavailableError,
    StorageSpaceError,
)
from finddocs.extractors.registry import ExtractorRegistry, build_default_registry
from finddocs.indexing.service import IndexService
from finddocs.jobs.control import JobControl
from finddocs.jobs.embed_batch import EmbeddingBatcher
from finddocs.jobs.pipeline import DocumentPipeline
from finddocs.logging_setup import bind_context, clear_context, get_logger
from finddocs.ocr.service import OcrService
from finddocs.types import (
    DocumentStatus,
    JobKind,
    JobState,
    ProgressSink,
    ProgressSnapshot,
    SourceKind,
)
from finddocs.version import CHUNKING_VERSION, NORMALIZATION_VERSION

log = get_logger(__name__)

#: Co ile dokumentow zapisujemy checkpoint i utrwalamy indeks wektorowy.
DEFAULT_CHECKPOINT_EVERY = 20

#: Co ile dokumentow odswiezamy postep w interfejsie.
PROGRESS_EVERY = 1


@dataclass(slots=True)
class JobOptions:
    """Parametry uruchomienia zadania."""

    kind: JobKind = JobKind.RESCAN
    source_ids: list[str] = field(default_factory=list)
    force_reindex: bool = False
    """Przetwarza także dokumenty niezmienione."""

    detect_deletions: bool = True
    resume_job_id: str | None = None


class IndexingJob:
    """Jedno uruchomienie indeksowania."""

    def __init__(
        self,
        config: AppConfig,
        index: IndexService,
        *,
        options: JobOptions | None = None,
        registry: ExtractorRegistry | None = None,
        ocr: OcrService | None = None,
        control: JobControl | None = None,
        progress: ProgressSink | None = None,
        paths: AppPaths | None = None,
    ) -> None:
        self.config = config
        self.index = index
        self.options = options or JobOptions()
        self.paths = paths or index.paths
        self.registry = registry or build_default_registry(
            office_com_enabled=config.indexing.office_com_enabled,
            archives_enabled=config.indexing.index_archives,
        )
        self.ocr = ocr or OcrService(
            config.ocr,
            repository=index.repository,
            model_dir=self.paths.models_dir,
            credentials_dir=self.paths.config_dir,
        )
        self.control = control or JobControl()
        self.progress_sink = progress
        self.job_id = self.options.resume_job_id or f"job-{uuid.uuid4().hex[:12]}"
        self.snapshot = ProgressSnapshot(
            job_id=self.job_id,
            kind=self.options.kind,
            state=JobState.QUEUED,
            stage="przygotowanie",
            stage_label="Przygotowanie",
        )
        # Tryb batchowy embeddingow: fragmenty kolejnych dokumentow sa osadzane
        # wspolnie. Wartosc 1 w konfiguracji wylacza bufor i przywraca zapis
        # kazdego dokumentu od razu.
        batch_documents = max(1, config.indexing.embed_batch_documents)
        self._batcher: EmbeddingBatcher | None = None
        if batch_documents > 1 and index.semantic_available:
            self._batcher = EmbeddingBatcher(
                index,
                max_documents=batch_documents,
                max_chunks=max(1, config.indexing.embed_batch_chunks),
            )
        self._pipeline = DocumentPipeline(
            config, index, self.registry, self.ocr, batcher=self._batcher
        )
        self._workspace: Path | None = None
        self._started = _dt.datetime.now().astimezone()

    # --- uruchomienie -----------------------------------------------------

    def run(self) -> ProgressSnapshot:
        """Wykonuje zadanie. Zwraca koncowa migawke postepu."""
        bind_context(job_id=self.job_id, job_kind=self.options.kind.value)
        repository = self.index.repository
        repository.create_job(
            self.job_id,
            self.options.kind,
            self.options.source_ids,
            {
                "force_reindex": self.options.force_reindex,
                "detect_deletions": self.options.detect_deletions,
            },
        )
        repository.update_job_state(self.job_id, JobState.RUNNING)
        self.snapshot.state = JobState.RUNNING
        self.snapshot.started_at = self._started
        self._emit("skanowanie", "Skanowanie źródeł")

        sources = self._selected_sources()
        if not sources:
            self._finish(JobState.FAILED, "Nie skonfigurowano żadnego aktywnego źródła.")
            return self.snapshot

        self._workspace = self.paths.new_temp_workspace(prefix=f"{self.job_id}-")
        try:
            for source in sources:
                self.control.checkpoint()
                self._run_source(source)
            self._finish(JobState.COMPLETED)
        except JobCancelledError:
            self._discard_embedding_buffer()
            self._finish(JobState.CANCELLED, "Zadanie zostało anulowane przez użytkownika.")
        except StorageSpaceError as exc:
            self._salvage_embedding_buffer()
            self._finish(JobState.FAILED, exc.user_message)
        except FindDocsError as exc:
            log.error("job.failed", code=exc.code, error_type=type(exc).__name__)
            self._salvage_embedding_buffer()
            self._finish(JobState.FAILED, exc.user_message)
        except Exception as exc:
            log.error("job.crashed", error_type=type(exc).__name__)
            self._salvage_embedding_buffer()
            self._finish(JobState.FAILED, f"Nieoczekiwany błąd zadania: {type(exc).__name__}.")
        finally:
            if self._workspace is not None:
                shutil.rmtree(self._workspace, ignore_errors=True)
            self.index.writer.flush(force=True)
            self.index.flush()
            clear_context()
        return self.snapshot

    @property
    def is_full_reindex(self) -> bool:
        """Czy zadanie liczy zbior od nowa, nie tylko zmiany."""
        return self.options.kind is JobKind.FULL_INDEX or self.options.force_reindex

    # --- pojedyncze zrodlo ------------------------------------------------

    def _run_source(self, source: SourceConfig) -> None:
        connector = self._build_connector(source)
        try:
            status = connector.test_connection()
            self.snapshot.connection_status = "połączono" if status.ok else "błąd połączenia"
            if not status.ok:
                raise SourceUnavailableError(status.message)

            repository = self.index.repository
            repository.upsert_source(
                source.source_id,
                source.kind,
                source.label,
                source.describe_location(),
                source.enabled,
            )

            checkpoint = repository.get_checkpoint(source.source_id, self.job_id)
            if checkpoint is None and self.is_full_reindex:
                self._forget_previous_problems(source)
            scan_id = (
                int(checkpoint["scan_id"]) if checkpoint is not None else repository.next_scan_id()
            )
            cursor = ScanCursor.from_json(checkpoint["cursor"]) if checkpoint is not None else None
            processed_before = int(checkpoint["processed"]) if checkpoint is not None else 0
            self.snapshot.processed = max(self.snapshot.processed, processed_before)

            self._emit("indeksowanie", f"Indeksowanie źródła: {source.label}")
            discovered = 0
            since_checkpoint = 0

            for item in connector.iter_items(cursor=cursor, cancel=self.control):
                self.control.checkpoint()
                discovered += 1
                self.snapshot.discovered += 1
                self.snapshot.current_file = item.logical_path

                local_path = None
                if source.kind is SourceKind.LOCAL_DIR:
                    resolver = getattr(connector, "local_path", None)
                    if callable(resolver):
                        local_path = str(resolver(item))

                with self.index.db.transaction():
                    doc_id = self.index.repository.register_item(item, scan_id, local_path)

                if not self._needs_processing(doc_id, item):
                    self.snapshot.unchanged += 1
                    with self.index.db.transaction():
                        self.index.repository.mark_unchanged(doc_id, scan_id)
                    self._emit_progress()
                    continue

                try:
                    outcome = self._pipeline.process(
                        connector,
                        item,
                        doc_id,
                        workspace=self._require_workspace(),
                        control=self.control,
                        scan_id=scan_id,
                    )
                except (JobCancelledError, StorageSpaceError):
                    raise
                except Exception as exc:
                    log.error(
                        "job.document_failed",
                        doc_id=doc_id,
                        error_type=type(exc).__name__,
                    )
                    self.snapshot.failed += 1
                    self.index.repository.log_error(
                        stage="pipeline",
                        code="FD-8002",
                        doc_id=doc_id,
                        file_name=item.name,
                        source_id=source.source_id,
                        message=f"Błąd przetwarzania: {type(exc).__name__}",
                    )
                    self._emit_progress()
                    continue
                if not outcome.deferred:
                    self._apply_outcome(outcome)
                self._drain_embedding_outcomes()
                since_checkpoint += 1

                if since_checkpoint >= self.config.indexing.checkpoint_every:
                    # Bufor batchera musi byc pusty przed checkpointem, inaczej
                    # licznik przetworzonych dokumentow wyprzedzilby zapisy.
                    self._flush_embeddings()
                    self._save_checkpoint(source, scan_id, connector.cursor(), discovered)
                    since_checkpoint = 0
                self._guard_temp_space()
                self._emit_progress()

            self.snapshot.discovery_complete = True
            self._flush_embeddings()
            self._save_checkpoint(source, scan_id, connector.cursor(), discovered, done=True)

            if self.options.detect_deletions:
                self._remove_deleted(source, scan_id)

            with self.index.db.transaction():
                self.index.repository.mark_source_scanned(
                    source.source_id,
                    scan_id,
                    full=self.is_full_reindex,
                )
            self.index.repository.clear_checkpoint(source.source_id, self.job_id)
        finally:
            connector.close()

    # --- batchowanie embeddingow -----------------------------------------

    def _drain_embedding_outcomes(self) -> None:
        """Dolicza do postepu dokumenty zapisane przez batcher od ostatniego razu."""
        if self._batcher is None:
            return
        for outcome in self._batcher.take_completed():
            self._apply_outcome(outcome)

    def _flush_embeddings(self) -> None:
        """Oproznia bufor batchera i dolicza wyniki do postepu."""
        if self._batcher is None:
            return
        self._batcher.flush(self.control)
        self._drain_embedding_outcomes()

    def _discard_embedding_buffer(self) -> None:
        """Porzuca bufor po anulowaniu. Dokumenty wroca przy nastepnym skanowaniu."""
        if self._batcher is not None:
            self._batcher.discard()

    def _salvage_embedding_buffer(self) -> None:
        """Po bledzie zadania probuje zapisac to, co czeka w buforze."""
        if self._batcher is None:
            return
        try:
            self._flush_embeddings()
        except Exception as exc:
            log.warning("job.embed_salvage_failed", error_type=type(exc).__name__)
            self._batcher.discard()

    # --- pomocnicze -------------------------------------------------------

    def _forget_previous_problems(self, source: SourceConfig) -> None:
        """Kasuje slad po nieudanych probach przed pelnym przeindeksowaniem.

        Pelne przeindeksowanie sprawdza kazdy plik od nowa, wiec stare bledy
        i pliki poza indeksem nie moga w nim zostawac: opisywalyby stan sprzed
        przebiegu. Wpis wraca na liste dopiero wtedy, gdy ten sam plik znowu
        sie nie uda. Czyszczenie dotyczy tylko skanowanego zrodla i tylko
        pierwszego przebiegu zadania, zeby wznowienie nie skasowalo bledow
        zapisanych chwile wczesniej przez to samo zadanie.
        """
        with self.index.db.transaction():
            requeued = self.index.repository.reset_source_problems(source.source_id)
        log.info("job.problems_reset", source_id=source.source_id, requeued=requeued)

    def _selected_sources(self) -> list[SourceConfig]:
        wanted = set(self.options.source_ids)
        sources = self.config.enabled_sources()
        if wanted:
            sources = [s for s in sources if s.source_id in wanted]
        return sources

    def _build_connector(self, source: SourceConfig) -> SourceConnector:
        if source.kind is SourceKind.LOCAL_DIR:
            from finddocs.connectors.local_dir import LocalDirectoryConnector

            return LocalDirectoryConnector.from_config(source)

        from finddocs.connectors.sharepoint import build_sharepoint_connector

        return build_sharepoint_connector(source, self.paths)

    def _needs_processing(self, doc_id: int, item: object) -> bool:
        if self.options.force_reindex:
            return True
        change_key = item.change_key()  # type: ignore[attr-defined]
        return self.index.repository.needs_processing(
            doc_id,
            change_key,
            normalization_version=NORMALIZATION_VERSION,
            chunking_version=CHUNKING_VERSION,
            model_key=self.index.provider.info.model_key if self.index.provider else None,
            require_vectors=self.index.semantic_available,
        )

    def _apply_outcome(self, outcome: object) -> None:
        status = outcome.status  # type: ignore[attr-defined]
        if status in {DocumentStatus.INDEXED, DocumentStatus.PARTIAL}:
            self.snapshot.processed += 1
        elif status in {
            DocumentStatus.SKIPPED,
            DocumentStatus.EMPTY,
            DocumentStatus.UNSUPPORTED,
        }:
            self.snapshot.skipped += 1
        else:
            self.snapshot.failed += 1
        if outcome.used_ocr:  # type: ignore[attr-defined]
            self.snapshot.ocr_documents += 1
            self.snapshot.ocr_pages += outcome.ocr_pages  # type: ignore[attr-defined]
        self.snapshot.bytes_processed += outcome.bytes_processed  # type: ignore[attr-defined]

    def _save_checkpoint(
        self,
        source: SourceConfig,
        scan_id: int,
        cursor: ScanCursor,
        discovered: int,
        *,
        done: bool = False,
    ) -> None:
        with self.index.db.transaction():
            self.index.repository.save_checkpoint(
                source.source_id,
                self.job_id,
                scan_id,
                cursor.to_json(),
                discovered,
                self.snapshot.processed,
                done,
            )
            self.index.repository.save_progress(self.job_id, self.snapshot)
        self.index.writer.flush(every=self.config.indexing.checkpoint_every)

    def _remove_deleted(self, source: SourceConfig, scan_id: int) -> None:
        stale = self.index.repository.stale_documents(source.source_id, scan_id)
        if not stale:
            return
        self._emit("usuwanie", f"Usuwanie dokumentów skasowanych w źródle: {len(stale)}")
        for record in stale:
            self.control.checkpoint()
            self.index.writer.delete_document(record.doc_id)
            self.snapshot.deleted += 1
        self.index.writer.flush(force=True)

    def _guard_temp_space(self) -> None:
        used = self.paths.temp_size_bytes()
        self.snapshot.temp_bytes_used = used
        if used > self.config.indexing.max_temp_bytes:
            log.warning("job.temp_space_high", used=used)
            self.paths.purge_temp()
            if self._workspace is not None:
                self._workspace.mkdir(parents=True, exist_ok=True)
        free = self.paths.free_space_bytes()
        if free < self.config.indexing.min_free_disk_bytes:
            raise StorageSpaceError(
                "Na dysku zabraklo miejsca, zeby bezpiecznie kontynuowac indeksowanie. "
                f"Wolne miejsce: {free // (1024 * 1024)} MB."
            )

    def _require_workspace(self) -> Path:
        if self._workspace is None:
            self._workspace = self.paths.new_temp_workspace(prefix=f"{self.job_id}-")
        return self._workspace

    # --- postep -----------------------------------------------------------

    def _emit(self, stage: str, label: str) -> None:
        self.snapshot.stage = stage
        self.snapshot.stage_label = label
        self._emit_progress()

    def _emit_progress(self) -> None:
        now = _dt.datetime.now().astimezone()
        self.snapshot.updated_at = now
        self.snapshot.elapsed_seconds = (
            now - self._started
        ).total_seconds() - self.control.paused_seconds
        if self.control.is_paused:
            self.snapshot.state = JobState.PAUSED
        elif self.snapshot.state is JobState.PAUSED:
            self.snapshot.state = JobState.RUNNING
        if self.progress_sink is not None:
            self.progress_sink.update(self.snapshot)

    def _finish(self, state: JobState, message: str | None = None) -> None:
        self.snapshot.state = state
        self.snapshot.message = message
        self.snapshot.current_file = None
        if state is JobState.COMPLETED:
            self.snapshot.stage = "zakonczone"
            self.snapshot.stage_label = "Zakonczono"
            self.snapshot.discovery_complete = True
        elif state is JobState.CANCELLED:
            self.snapshot.stage = "anulowane"
            self.snapshot.stage_label = "Anulowano"
        else:
            self.snapshot.stage = "blad"
            self.snapshot.stage_label = "Blad"
        with self.index.db.transaction():
            self.index.repository.save_progress(self.job_id, self.snapshot)
            self.index.repository.update_job_state(
                self.job_id,
                state,
                error_message=message if state is JobState.FAILED else None,
                error_code="FD-8000" if state is JobState.FAILED else None,
            )
        self._emit_progress()
        log.info(
            "job.finished",
            state=state.value,
            processed=self.snapshot.processed,
            failed=self.snapshot.failed,
            skipped=self.snapshot.skipped,
            unchanged=self.snapshot.unchanged,
            deleted=self.snapshot.deleted,
            ocr_documents=self.snapshot.ocr_documents,
        )


__all__ = ["DEFAULT_CHECKPOINT_EVERY", "PROGRESS_EVERY", "IndexingJob", "JobOptions"]

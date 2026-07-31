"""Fixture wspolne dla testow integracyjnych.

Testy integracyjne skladaja prawdziwe warstwy aplikacji: konektor katalogu
lokalnego, parsery, fragmentacje, indeks SQLite i zadanie indeksowania. Model
embeddingow nie jest uzywany, wiec caly przeplyw dziala na czesci pelnotekstowej.

Pomoc jest udostepniana wylacznie przez fixture, zeby moduly testowe nie musialy
importowac tego pliku (nazwa ``conftest`` powtarza sie w kilku katalogach).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from finddocs.config import AppConfig, LocalDirSourceSettings, SourceConfig
from finddocs.indexing.service import IndexService
from finddocs.jobs.control import JobControl
from finddocs.jobs.indexing_job import IndexingJob, JobOptions
from finddocs.search.service import SearchService
from finddocs.types import (
    JobKind,
    ProgressSnapshot,
    SearchMode,
    SearchRequest,
    SourceKind,
)

#: Identyfikator zrodla uzywany we wszystkich testach integracyjnych.
SOURCE_ID = "lokalne"


class _CollectingProgress:
    """Odbiornik postepu spelniajacy protokol ``ProgressSink``.

    Zapisuje kolejne stany licznikow i przekazuje migawke do funkcji testu, dzieki
    czemu test moze zareagowac w trakcie pracy zadania, na przyklad je anulowac.
    """

    def __init__(self, on_update: Callable[[ProgressSnapshot], None] | None = None) -> None:
        self.updates: list[tuple[str, int, int]] = []
        self._on_update = on_update

    def update(self, snapshot: ProgressSnapshot) -> None:
        self.updates.append((snapshot.stage, snapshot.processed, snapshot.failed))
        if self._on_update is not None:
            self._on_update(snapshot)


@pytest.fixture
def source_id() -> str:
    """Identyfikator zrodla lokalnego uzywanego w testach integracyjnych."""
    return SOURCE_ID


@pytest.fixture
def indexing_config(app_config: AppConfig) -> Callable[..., AppConfig]:
    """Zwraca funkcje ustawiajaca w konfiguracji jedno zrodlo typu katalog lokalny.

    OCR oraz automatyzacja Microsoft Office sa wylaczane, zeby wynik testu nie
    zalezal od tego, jakie komponenty sa zainstalowane na maszynie.
    """

    def configure(
        root: Path,
        *,
        include_extensions: Sequence[str] = (),
        exclude_extensions: Sequence[str] = (),
        exclude_globs: Sequence[str] = (),
        max_file_size_mb: int = 512,
    ) -> AppConfig:
        app_config.ocr.enabled = False
        app_config.indexing.office_com_enabled = False
        app_config.sources = [
            SourceConfig(
                source_id=SOURCE_ID,
                kind=SourceKind.LOCAL_DIR,
                label="Katalog testowy",
                local=LocalDirSourceSettings(root_path=str(root)),
                include_extensions=list(include_extensions),
                exclude_extensions=list(exclude_extensions),
                exclude_globs=list(exclude_globs),
                max_file_size_mb=max_file_size_mb,
            )
        ]
        return app_config

    return configure


@pytest.fixture
def run_job() -> Callable[..., ProgressSnapshot]:
    """Zwraca funkcje uruchamiajaca jedno zadanie indeksowania."""

    def run(
        config: AppConfig,
        index: IndexService,
        *,
        kind: JobKind = JobKind.FULL_INDEX,
        control: JobControl | None = None,
        on_progress: Callable[[ProgressSnapshot], None] | None = None,
        force_reindex: bool = False,
        detect_deletions: bool = True,
        resume_job_id: str | None = None,
    ) -> ProgressSnapshot:
        options = JobOptions(
            kind=kind,
            force_reindex=force_reindex,
            detect_deletions=detect_deletions,
            resume_job_id=resume_job_id,
        )
        job = IndexingJob(
            config,
            index,
            options=options,
            control=control or JobControl(),
            progress=_CollectingProgress(on_progress),
        )
        return job.run()

    return run


@pytest.fixture
def document_statuses() -> Callable[[IndexService], dict[str, str]]:
    """Zwraca funkcje budujaca mape nazwa pliku -> status dokumentu."""

    def statuses(index: IndexService) -> dict[str, str]:
        rows = index.db.query_all("SELECT name, status FROM documents ORDER BY name")
        return {str(row["name"]): str(row["status"]) for row in rows}

    return statuses


@pytest.fixture
def exact_search_count() -> Callable[[IndexService, str], int]:
    """Zwraca funkcje liczaca dokumenty znalezione w trybie dokladnym."""

    def count(index: IndexService, query: str) -> int:
        response = SearchService(index).search(
            SearchRequest(query=query, mode=SearchMode.EXACT)
        )
        return response.total_documents

    return count

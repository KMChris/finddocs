"""Testy ekranu indeksowania."""

from __future__ import annotations

import datetime as _dt
from collections.abc import Callable

import pytest
from PySide6.QtWidgets import QMessageBox

from finddocs.gui import i18n
from finddocs.gui.context import AppContext
from finddocs.gui.indexing_view import IndexingView
from finddocs.jobs.indexing_job import JobOptions
from finddocs.types import JobKind, JobState, ProgressSnapshot

#: Indeksowanie idzie do wlasnego watku, wiec czekamy na sygnal zamiast usypiac test.
TIMEOUT_MS = 20_000


class FakeRunner:
    """Atrapa wykonawcy zadan. Pozwala ustawic dowolny stan bez watku roboczego."""

    def __init__(self) -> None:
        self.is_running = False
        self.is_paused = False
        self.submitted: list[JobOptions] = []
        self.progress_callbacks: list[Callable[[ProgressSnapshot], None]] = []
        self.completion_callbacks: list[Callable[[ProgressSnapshot], None]] = []
        self.stopped = False

    def on_progress(self, callback: Callable[[ProgressSnapshot], None]) -> None:
        self.progress_callbacks.append(callback)

    def on_completed(self, callback: Callable[[ProgressSnapshot], None]) -> None:
        self.completion_callbacks.append(callback)

    def submit(self, options: JobOptions) -> JobOptions:
        self.submitted.append(options)
        self.is_running = True
        return options

    def pause(self) -> bool:
        self.is_paused = True
        return True

    def resume(self) -> bool:
        self.is_paused = False
        return True

    def cancel(self) -> bool:
        self.is_running = False
        self.is_paused = False
        return True

    def stop(self, *, wait: bool = True, timeout: float = 30.0) -> None:
        self.stopped = True

    def resumable_jobs(self) -> list[dict[str, object]]:
        return []


def _snapshot(**changes: object) -> ProgressSnapshot:
    """Migawka postepu z sensownymi wartosciami domyslnymi."""
    data: dict[str, object] = {
        "job_id": "job-testowy",
        "kind": JobKind.RESCAN,
        "state": JobState.RUNNING,
        "stage": "przetwarzanie",
        "stage_label": "Przetwarzanie dokumentow",
        "discovered": 20,
        "processed": 5,
        "unchanged": 2,
        "skipped": 2,
        "failed": 1,
        "deleted": 3,
        "ocr_documents": 4,
        "ocr_pages": 9,
        "current_file": "procedury/raport.pdf",
        "elapsed_seconds": 90.0,
        "temp_bytes_used": 2048,
        "connection_status": "polaczono",
        "discovery_complete": True,
    }
    data.update(changes)
    return ProgressSnapshot(**data)  # type: ignore[arg-type]


@pytest.fixture
def indexing_view(qtbot: object, gui_context_with_source: AppContext) -> IndexingView:
    """Widok indeksowania dla kontekstu ze skonfigurowanym zrodlem lokalnym."""
    view = IndexingView(gui_context_with_source)
    qtbot.addWidget(view)  # type: ignore[attr-defined]
    return view


@pytest.fixture
def fake_runner(monkeypatch: pytest.MonkeyPatch, gui_context_with_source: AppContext) -> FakeRunner:
    """Podmienia wykonawce zadan na atrape o sterowanym stanie."""
    runner = FakeRunner()
    monkeypatch.setattr(gui_context_with_source, "runner", runner)
    return runner


# --- stany przyciskow -----------------------------------------------------------


@pytest.mark.gui
def test_buttons_are_idle_before_start(indexing_view: IndexingView) -> None:
    """Przed uruchomieniem mozna zaczac skanowanie, ale nie ma czego wstrzymywac."""
    assert indexing_view.start_button.isEnabled()
    assert indexing_view.rescan_button.isEnabled()
    assert indexing_view.full_button.isEnabled()
    assert not indexing_view.pause_button.isEnabled()
    assert not indexing_view.resume_button.isEnabled()
    assert not indexing_view.cancel_button.isEnabled()


@pytest.mark.gui
def test_buttons_change_state_during_job(
    indexing_view: IndexingView, fake_runner: FakeRunner
) -> None:
    """W trakcie zadania start jest zablokowany, a pauza i anulowanie dostepne."""
    indexing_view.start_button.click()

    assert [options.kind for options in fake_runner.submitted] == [JobKind.RESCAN]
    assert not indexing_view.start_button.isEnabled()
    assert not indexing_view.rescan_button.isEnabled()
    assert not indexing_view.full_button.isEnabled()
    assert indexing_view.pause_button.isEnabled()
    assert not indexing_view.resume_button.isEnabled()
    assert indexing_view.cancel_button.isEnabled()

    indexing_view.pause_button.click()

    assert fake_runner.is_paused
    assert not indexing_view.pause_button.isEnabled()
    assert indexing_view.resume_button.isEnabled()

    indexing_view.resume_button.click()

    assert not fake_runner.is_paused
    assert indexing_view.pause_button.isEnabled()
    assert not indexing_view.resume_button.isEnabled()

    indexing_view.cancel_button.click()

    assert not fake_runner.is_running
    assert indexing_view.start_button.isEnabled()
    assert not indexing_view.cancel_button.isEnabled()


@pytest.mark.gui
def test_start_without_source_warns(
    qtbot: object, gui_context: AppContext, message_boxes: list[QMessageBox]
) -> None:
    """Bez skonfigurowanego zrodla widok ostrzega zamiast zlecac zadanie."""
    view = IndexingView(gui_context)
    qtbot.addWidget(view)  # type: ignore[attr-defined]

    view.start_scan()

    assert [box.text() for box in message_boxes] == [i18n.SOURCES_EMPTY]


@pytest.mark.gui
def test_full_reindex_needs_confirmation(
    indexing_view: IndexingView, fake_runner: FakeRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pelne przeindeksowanie rusza dopiero po potwierdzeniu w oknie dialogowym."""
    indexing_view.full_button.click()
    assert fake_runner.submitted == []

    def accept(box: QMessageBox) -> int:
        for button in box.buttons():
            if button.text() == "Tak":
                button.click()
        return int(QMessageBox.StandardButton.Yes)

    monkeypatch.setattr(QMessageBox, "exec", accept)

    indexing_view.full_button.click()

    assert [options.kind for options in fake_runner.submitted] == [JobKind.FULL_INDEX]
    assert fake_runner.submitted[0].force_reindex


@pytest.mark.gui
def test_real_job_finishes_and_releases_buttons(
    qtbot: object, indexing_view: IndexingView, gui_context_with_source: AppContext
) -> None:
    """Prawdziwe zadanie na malym katalogu konczy sie i odblokowuje przyciski."""
    with qtbot.waitSignal(indexing_view.index_changed, timeout=TIMEOUT_MS):  # type: ignore[attr-defined]
        indexing_view.start_button.click()

    assert indexing_view.start_button.isEnabled()
    assert not indexing_view.pause_button.isEnabled()
    assert not indexing_view.resume_button.isEnabled()
    assert not indexing_view.cancel_button.isEnabled()
    assert indexing_view.progress_bar.value() == 100
    assert int(indexing_view._stat_labels["processed"].text()) > 0
    assert gui_context_with_source.require_index().status().indexed_documents > 0


# --- postep ---------------------------------------------------------------------


@pytest.mark.gui
def test_progress_snapshot_updates_labels(indexing_view: IndexingView) -> None:
    """Migawka postepu aktualizuje etap, pasek i wszystkie etykiety statystyk."""
    indexing_view._on_progress(_snapshot())

    labels = indexing_view._stat_labels
    assert indexing_view.stage_label.text() == "Przetwarzanie dokumentow (w toku)"
    assert labels["discovered"].text() == "20"
    assert labels["processed"].text() == "5"
    assert labels["unchanged"].text() == "2"
    assert labels["skipped"].text() == "2"
    assert labels["failed"].text() == "1"
    assert labels["deleted"].text() == "3"
    assert labels["ocr_documents"].text() == "4"
    assert labels["ocr_pages"].text() == "9"
    assert labels["elapsed"].text() == i18n.format_duration(90.0)
    assert labels["connection"].text() == "polaczono"
    assert labels["temp"].text() == i18n.format_bytes(2048)
    assert indexing_view.current_file_label.text() == f"{i18n.STAT_CURRENT}: procedury/raport.pdf"


@pytest.mark.gui
def test_known_progress_fills_bar(indexing_view: IndexingView) -> None:
    """Znany postep ustawia wartosc paska i komunikat o przyblizeniu."""
    indexing_view._on_progress(_snapshot())

    assert indexing_view.progress_bar.maximum() == 100
    assert indexing_view.progress_bar.value() == 50
    assert indexing_view.progress_hint.text() == i18n.PROGRESS_APPROXIMATE.format(value="50.0%")


@pytest.mark.gui
def test_unknown_progress_shows_indeterminate_bar(indexing_view: IndexingView) -> None:
    """Przed zakonczeniem wykrywania pasek jest nieokreslony."""
    snapshot = _snapshot(discovery_complete=False, stage_label="Wykrywanie plikow")

    indexing_view._on_progress(snapshot)

    assert snapshot.progress_fraction is None
    assert indexing_view.progress_bar.minimum() == 0
    assert indexing_view.progress_bar.maximum() == 0
    assert indexing_view.progress_hint.text() == i18n.PROGRESS_UNKNOWN


@pytest.mark.gui
def test_completion_reports_summary(indexing_view: IndexingView, fake_runner: FakeRunner) -> None:
    """Zakonczone zadanie ustawia pasek na 100 procent i zglasza podsumowanie."""
    messages: list[str] = []
    indexing_view.status_message.connect(messages.append)

    indexing_view._on_completed(_snapshot(state=JobState.COMPLETED, processed=7))

    assert indexing_view.progress_bar.value() == 100
    assert any("Przetworzono 7 dokumentow" in message for message in messages)


# --- tabele ---------------------------------------------------------------------


@pytest.mark.gui
def test_tables_are_filled_from_repository(
    qtbot: object, indexed_gui_context: AppContext, corpus_stats: dict[str, int]
) -> None:
    """Tabela bledow i tabela plikow pominietych czytaja dane z repozytorium."""
    repository = indexed_gui_context.require_index().repository
    repository.log_error(
        stage="ekstrakcja",
        code="FD-3002",
        file_name="uszkodzony.pdf",
        message="Plik jest uszkodzony.",
    )
    view = IndexingView(indexed_gui_context)
    qtbot.addWidget(view)  # type: ignore[attr-defined]

    view.refresh_tables()

    # Indeksowanie samo zapisuje blad pustego pliku, wiec sprawdzamy zawartosc
    # wiersza, a nie liczbe wierszy. Najnowszy blad jest pierwszy.
    assert view.error_table.rowCount() >= 1
    assert view.error_table.item(0, 0).text() == "uszkodzony.pdf"
    assert view.error_table.item(0, 1).text() == "ekstrakcja"
    assert view.error_table.item(0, 2).text() == "FD-3002"
    assert view.error_table.item(0, 3).text() == "Plik jest uszkodzony."
    assert _dt.datetime.fromisoformat(view.error_table.item(0, 4).text())

    assert view.skipped_table.rowCount() == corpus_stats["niewyszukiwalne"]
    names = [view.skipped_table.item(row, 0).text() for row in range(view.skipped_table.rowCount())]
    assert "pusty.txt" in names
    statuses = {
        view.skipped_table.item(row, 2).text() for row in range(view.skipped_table.rowCount())
    }
    assert statuses == {"brak tresci"}

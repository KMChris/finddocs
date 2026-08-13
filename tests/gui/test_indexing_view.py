"""Testy ekranu indeksowania."""

from __future__ import annotations

import datetime as _dt
from collections.abc import Callable

import pytest
from PySide6.QtWidgets import QMessageBox

from finddocs.gui import i18n
from finddocs.gui.context import AppContext
from finddocs.gui.indexing_view import LIST_REFRESH_TICKS, ROW_ID_ROLE, IndexingView
from finddocs.jobs.indexing_job import JobOptions
from finddocs.types import DocumentStatus, JobKind, JobState, ProgressSnapshot

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


def _publish(view: IndexingView, snapshot: ProgressSnapshot) -> ProgressSnapshot:
    """Podaje migawke i wymusza takt zegara widoku.

    Widok laczy migawki przychodzace gesciej niz co ``TICK_MS`` i rysuje je
    zegarem. Test nie krec i petli zdarzen, wiec takt wywoluje sam.
    """
    view._on_progress(snapshot)
    view._tick()
    return snapshot


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
    assert indexing_view.start_button.text() == i18n.INDEXING_SCAN
    assert indexing_view.full_button.isEnabled()
    assert not indexing_view.pause_button.isEnabled()
    assert not indexing_view.cancel_button.isEnabled()


@pytest.mark.gui
def test_buttons_change_state_during_job(
    indexing_view: IndexingView, fake_runner: FakeRunner
) -> None:
    """W trakcie zadania start jest zablokowany, a pauza i anulowanie dostepne."""
    indexing_view.start_button.click()

    assert [options.kind for options in fake_runner.submitted] == [JobKind.RESCAN]
    assert not indexing_view.start_button.isEnabled()
    assert not indexing_view.full_button.isEnabled()
    assert indexing_view.pause_button.isEnabled()
    assert indexing_view.pause_button.text() == i18n.INDEXING_PAUSE
    assert indexing_view.cancel_button.isEnabled()

    # Jeden przycisk obsluguje wstrzymanie i wznowienie, wiec po klikniecie
    # zmienia napis na przeciwna akcje.
    indexing_view.pause_button.click()

    assert fake_runner.is_paused
    assert indexing_view.pause_button.isEnabled()
    assert indexing_view.pause_button.text() == i18n.INDEXING_RESUME

    indexing_view.pause_button.click()

    assert not fake_runner.is_paused
    assert indexing_view.pause_button.text() == i18n.INDEXING_PAUSE

    indexing_view.cancel_button.click()

    assert not fake_runner.is_running
    assert indexing_view.start_button.isEnabled()
    assert not indexing_view.cancel_button.isEnabled()
    assert not indexing_view.pause_button.isEnabled()


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
    assert not indexing_view.cancel_button.isEnabled()
    assert indexing_view.progress_bar.value() == 100
    assert int(indexing_view._stat_labels["processed"].text()) > 0
    assert gui_context_with_source.require_index().status().indexed_documents > 0


# --- postep ---------------------------------------------------------------------


@pytest.mark.gui
def test_statystyki_przed_startem_nie_pokazuja_zer_tam_gdzie_nie_ma_licznika(
    indexing_view: IndexingView,
) -> None:
    """Czas, polaczenie i miejsce tymczasowe nie sa licznikami, wiec nie sa zerami."""
    labels = indexing_view._stat_labels

    assert labels["discovered"].text() == "0"
    assert labels["processed"].text() == "0"
    assert labels["elapsed"].text() == i18n.format_duration(0)
    assert labels["connection"].text() == i18n.STAT_NONE
    assert labels["temp"].text() == i18n.format_bytes(0)


@pytest.mark.gui
def test_podpowiedz_postepu_jest_ukryta_przed_uruchomieniem(
    indexing_view: IndexingView,
) -> None:
    """Karta etapu nie moze opisywac postepu zadania, ktorego jeszcze nie ma."""
    assert indexing_view.progress_hint.isHidden()
    assert indexing_view.current_file_label.isHidden()

    indexing_view._on_progress(_snapshot())

    assert not indexing_view.progress_hint.isHidden()
    assert not indexing_view.current_file_label.isHidden()


@pytest.mark.gui
def test_karty_postepu_pojawiaja_sie_z_pierwsza_migawka(indexing_view: IndexingView) -> None:
    """W spoczynku pasek 0% wyglada jak zadanie, ktore stoi, wiec go nie ma."""
    assert indexing_view.progress_box.isHidden()
    assert indexing_view.stats_box.isHidden()

    indexing_view._on_progress(_snapshot())

    assert not indexing_view.progress_box.isHidden()
    assert not indexing_view.stats_box.isHidden()
    assert indexing_view.last_run_box.isHidden()


@pytest.mark.gui
def test_liczba_bledow_dostaje_kolor_bledu_i_otwiera_zakladke(
    indexing_view: IndexingView,
) -> None:
    """Bledy sa jedyna liczba wymagajaca reakcji, wiec sa wyroznione i klikalne."""
    indexing_view._on_progress(_snapshot(failed=3))
    failed = indexing_view.stats.labels["failed"]
    assert failed.property("valueRole") == "danger"
    assert failed.toolTip() == i18n.STAT_FAILED_HINT

    indexing_view._tabs.setCurrentIndex(1)
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    event = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(1, 1),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    indexing_view.eventFilter(failed, event)

    assert indexing_view._tabs.currentIndex() == 0

    _publish(indexing_view, _snapshot(failed=0))
    assert failed.property("valueRole") == ""


@pytest.mark.gui
def test_ostatni_przebieg_z_historii_zadan(qtbot: object, indexed_gui_context: AppContext) -> None:
    """Po ponownym uruchomieniu ekran opisuje ostatni przebieg zamiast zer."""
    view = IndexingView(indexed_gui_context)
    qtbot.addWidget(view)  # type: ignore[attr-defined]

    assert not view.last_run_box.isHidden()
    assert i18n.JOB_KIND_LABELS["rescan"] in view.last_run_label.text()
    assert "Przetworzone:" in view.last_run_label.text()


@pytest.mark.gui
def test_brak_historii_ukrywa_karte_ostatniego_przebiegu(
    indexing_view: IndexingView,
) -> None:
    assert indexing_view.last_run_box.isHidden()


@pytest.mark.gui
def test_nazwy_zakladek_niosa_liczbe_wierszy(
    qtbot: object, indexed_gui_context: AppContext, corpus_stats: dict[str, int]
) -> None:
    """Bez liczby w nazwie trzeba otworzyc zakladke, zeby sprawdzic, czy jest pusta."""
    view = IndexingView(indexed_gui_context)
    qtbot.addWidget(view)  # type: ignore[attr-defined]

    view.refresh_tables()

    problems = i18n.INDEXING_TAB_COUNT.format(
        name=i18n.INDEXING_TAB_PROBLEMS, count=corpus_stats["niewyszukiwalne"]
    )
    assert view._tabs.tabText(0) == problems
    assert view._tabs.tabText(1).startswith(i18n.INDEXING_TAB_ERRORS)


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
    """Po zakonczeniu wykrywania pasek pokazuje pewny procent i liczby."""
    _publish(indexing_view, _snapshot())

    assert indexing_view.progress_bar.maximum() == 100
    assert indexing_view.progress_bar.value() == 50
    assert indexing_view.progress_hint.text() == i18n.PROGRESS_EXACT.format(
        value="50.0%", done=10, total=20
    )


@pytest.mark.gui
def test_unknown_progress_shows_indeterminate_bar(indexing_view: IndexingView) -> None:
    """Bez oszacowania liczby plikow pasek jest nieokreslony."""
    snapshot = _snapshot(discovery_complete=False, stage_label="Wykrywanie plikow")

    _publish(indexing_view, snapshot)

    assert snapshot.progress_fraction is None
    assert indexing_view.progress_bar.minimum() == 0
    assert indexing_view.progress_bar.maximum() == 0
    assert indexing_view.progress_hint.text() == i18n.PROGRESS_UNKNOWN


@pytest.mark.gui
def test_oszacowanie_daje_procenty_przed_koncem_wykrywania(
    indexing_view: IndexingView,
) -> None:
    """Znany mianownik zamienia pasek nieokreslony na procenty, z zastrzezeniem."""
    snapshot = _snapshot(discovery_complete=False, estimated_total=40)

    _publish(indexing_view, snapshot)

    assert indexing_view.progress_bar.maximum() == 100
    assert indexing_view.progress_bar.value() == 25
    assert indexing_view.progress_hint.text() == i18n.PROGRESS_APPROXIMATE.format(
        value="25.0%", done=10, total=40
    )


@pytest.mark.gui
def test_czas_biegnie_miedzy_migawkami(indexing_view: IndexingView) -> None:
    """Dlugi plik nie przysyla migawek, a licznik czasu ma isc dalej."""
    _publish(indexing_view, _snapshot(elapsed_seconds=90.0))
    assert indexing_view._stat_labels["elapsed"].text() == i18n.format_duration(90.0)

    # Symulacja pliku przetwarzanego od pol minuty bez nowej migawki.
    indexing_view._snapshot_at -= 30.0
    indexing_view._tick()

    assert indexing_view._stat_labels["elapsed"].text() == i18n.format_duration(120.0)


@pytest.mark.gui
def test_czas_stoi_po_wstrzymaniu(indexing_view: IndexingView) -> None:
    """Zadanie wstrzymane nie nalicza czasu, wiec licznik tez stoi."""
    _publish(indexing_view, _snapshot(state=JobState.PAUSED, elapsed_seconds=90.0))

    indexing_view._snapshot_at -= 30.0
    indexing_view._tick()

    assert indexing_view._stat_labels["elapsed"].text() == i18n.format_duration(90.0)


@pytest.mark.gui
def test_completion_reports_summary(indexing_view: IndexingView, fake_runner: FakeRunner) -> None:
    """Zakonczone zadanie ustawia pasek na 100 procent i zglasza podsumowanie."""
    messages: list[str] = []
    indexing_view.status_message.connect(messages.append)

    indexing_view._on_completed(_snapshot(state=JobState.COMPLETED, processed=7))

    assert indexing_view.progress_bar.value() == 100
    assert any("Przetworzono 7 dokumentów" in message for message in messages)


# --- tabele ---------------------------------------------------------------------


@pytest.mark.gui
def test_tables_are_filled_from_repository(
    qtbot: object, indexed_gui_context: AppContext, corpus_stats: dict[str, int]
) -> None:
    """Dziennik bledow i lista plikow poza indeksem czytaja dane z repozytorium."""
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

    assert view.problems_table.rowCount() == corpus_stats["niewyszukiwalne"]
    names = [
        view.problems_table.item(row, 0).text() for row in range(view.problems_table.rowCount())
    ]
    assert "pusty.txt" in names
    statuses = {
        view.problems_table.item(row, 2).text() for row in range(view.problems_table.rowCount())
    }
    assert statuses == {i18n.status_label(DocumentStatus.EMPTY)}


@pytest.mark.gui
def test_kazda_lista_mowi_co_na_niej_jest(qtbot: object, indexed_gui_context: AppContext) -> None:
    """Zdanie nad tabela tlumaczy liste, a przy pustej liscie zmienia sie w dobra wiadomosc."""
    repository = indexed_gui_context.require_index().repository
    view = IndexingView(indexed_gui_context)
    qtbot.addWidget(view)  # type: ignore[attr-defined]

    view.refresh_tables()

    # Korpus testowy ma jeden plik bez tresci, wiec obie listy maja wiersze.
    assert view.problems_hint.text() == i18n.INDEXING_PROBLEMS_HINT
    assert view.errors_hint.text() == i18n.INDEXING_ERRORS_HINT

    repository.clear_errors()
    view.refresh_tables()

    assert view.errors_hint.text() == i18n.INDEXING_ERRORS_EMPTY


@pytest.mark.gui
def test_akcje_list_wymagaja_zaznaczenia(qtbot: object, indexed_gui_context: AppContext) -> None:
    """Przycisk dzialajacy na zaznaczeniu jest nieaktywny, dopoki nic nie wybrano."""
    view = IndexingView(indexed_gui_context)
    qtbot.addWidget(view)  # type: ignore[attr-defined]
    view.refresh_tables()

    assert not view.retry_button.isEnabled()
    assert not view.delete_errors_button.isEnabled()
    # Czyszczenie dziennika nie potrzebuje zaznaczenia, tylko niepustej listy.
    assert view.clear_errors_button.isEnabled()

    view.problems_table.selectRow(0)
    view.error_table.selectRow(0)

    assert view.retry_button.isEnabled()
    assert view.delete_errors_button.isEnabled()


@pytest.mark.gui
def test_ponowne_przetworzenie_usuwa_wpis_i_oddaje_plik_do_kolejki(
    qtbot: object,
    indexed_gui_context: AppContext,
    drain_tasks: Callable[[], None],
) -> None:
    """Zaznaczony plik znika z listy i czeka na kolejne skanowanie."""
    view = IndexingView(indexed_gui_context)
    qtbot.addWidget(view)  # type: ignore[attr-defined]
    view.refresh_tables()
    assert view.problems_table.rowCount() == 1
    doc_id = view.problems_table.item(0, 0).data(ROW_ID_ROLE)

    view.problems_table.selectRow(0)
    view.retry_button.click()
    drain_tasks()

    assert view.problems_table.rowCount() == 0
    assert view.problems_hint.text() == i18n.INDEXING_PROBLEMS_EMPTY
    record = indexed_gui_context.require_index().repository.get_document(int(doc_id))
    assert record is not None
    assert record.status is DocumentStatus.PENDING


@pytest.mark.gui
def test_wpisy_dziennika_mozna_usunac(
    qtbot: object,
    indexed_gui_context: AppContext,
    drain_tasks: Callable[[], None],
) -> None:
    """Dziennik opisuje przeszlosc, wiec wpis mozna z niego usunac."""
    repository = indexed_gui_context.require_index().repository
    repository.log_error(stage="scan", code="FD-1006", file_name="wielki.pdf", message="Za duzy.")
    view = IndexingView(indexed_gui_context)
    qtbot.addWidget(view)  # type: ignore[attr-defined]
    view.refresh_tables()
    przed = view.error_table.rowCount()
    assert przed >= 2

    view.error_table.selectRow(0)
    usuwany = view.error_table.item(0, 0).text()
    view.delete_errors_button.click()
    drain_tasks()

    assert view.error_table.rowCount() == przed - 1
    nazwy = [view.error_table.item(row, 0).text() for row in range(view.error_table.rowCount())]
    assert usuwany not in nazwy
    assert len(repository.recent_errors()) == przed - 1


@pytest.mark.gui
def test_listy_odswiezaja_sie_w_trakcie_zadania(
    qtbot: object, indexed_gui_context: AppContext
) -> None:
    """Pelne przeindeksowanie kasuje wpisy na starcie, a tabela ma to pokazac.

    Bez odswiezania w trakcie zadania wiersze zostawaly na ekranie do konca
    przebiegu i wygladalo to tak, jakby czyszczenie nie dzialalo.
    """
    view = IndexingView(indexed_gui_context)
    qtbot.addWidget(view)  # type: ignore[attr-defined]
    view.refresh_tables()
    assert view.problems_table.rowCount() == 1

    repository = indexed_gui_context.require_index().repository
    with indexed_gui_context.require_index().db.transaction():
        repository.reset_source_problems("zrodlo-testowe")

    # Zegar widoku siega po listy co kilka taktow, nie w kazdym.
    view._on_progress(_snapshot())
    for _ in range(LIST_REFRESH_TICKS):
        view._tick()

    assert view.problems_table.rowCount() == 0
    assert view.error_table.rowCount() == 0


@pytest.mark.gui
def test_listy_sa_zablokowane_w_trakcie_zadania(
    qtbot: object, indexed_gui_context: AppContext, fake_runner: FakeRunner
) -> None:
    """W trakcie skanowania listy zmienia potok, wiec recznie sie ich nie rusza."""
    view = IndexingView(indexed_gui_context)
    qtbot.addWidget(view)  # type: ignore[attr-defined]
    view.refresh_tables()
    view.problems_table.selectRow(0)
    assert view.retry_button.isEnabled()

    fake_runner.is_running = True
    view._refresh_buttons()

    assert not view.retry_button.isEnabled()
    assert not view.clear_errors_button.isEnabled()

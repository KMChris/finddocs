"""Ekran indeksowania: postep, sterowanie oraz listy plikow do wyjasnienia.

Wiersz sterowania ma tyle przyciskow, ile jest roznych operacji:

* skanowanie zrodel (dawne ,,Start'' i ,,Skanuj ponownie'' zlecaly to samo
  zadanie, wiec obok siebie sugerowaly dwie rozne operacje);
* wstrzymanie albo wznowienie, czyli jeden przycisk przelaczany, bo w danej
  chwili sensowna jest tylko jedna z tych dwoch akcji;
* anulowanie;
* pelne przeindeksowanie, jedyna operacja liczaca wszystko od nowa.

W spoczynku ekran nie pokazuje paska 0% ani statystyk z samych zer: pasek
0% wyglada jak zadanie, ktore stoi. Zamiast tego jest podsumowanie ostatniego
przebiegu z historii zadan. Karty postepu i statystyk pojawiaja sie wraz
z pierwsza migawka biezacego zadania.

Dolna czesc ekranu to dwie listy, ktore odpowiadaja na dwa rozne pytania:

* ,,Pliki poza indeksem'' to stan zbioru: czego nie znajde w wynikach i co z tym
  zrobic. Wiersz opisuje plik, wiec kazdy plik jest tu najwyzej raz i mozna
  oddac go do ponownego przetworzenia;
* ,,Dziennik bledow'' to zdarzenia: co sie stalo przy ostatniej probie. Wpisy
  mozna usunac, bo dziennik niczego nie naprawia, tylko opisuje.

Dawne nazwy ,,Bledy'' i ,,Pliki pominiete'' sugerowaly dwa rozlaczne zbiory
plikow, choc ten sam plik trafial na obie listy, a raz zapisany blad zostawal
tam na zawsze. Kazda lista zaczyna sie od zdania, ktore mowi, co na niej jest.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from finddocs.gui import i18n
from finddocs.gui.context import AppContext
from finddocs.gui.dialogs import ask_yes_no, show_error, show_info, show_warning
from finddocs.gui.tables import (
    configure_columns,
    filter_table_rows,
    format_stamp,
    populate_rows,
    text_item,
)
from finddocs.gui.theme import SPACE_SM, accent_icon, theme_icon
from finddocs.gui.widgets.page import PageHeader, page_layout
from finddocs.gui.widgets.stat_grid import StatGrid
from finddocs.gui.widgets.tabs import TabPanel
from finddocs.gui.workers import CallableTask, ProgressBridge, thread_pool
from finddocs.indexing.service import IndexService
from finddocs.jobs.indexing_job import JobOptions
from finddocs.logging_setup import get_logger
from finddocs.types import JobKind, JobState, ProgressSnapshot

log = get_logger(__name__)

ERROR_TABLE_LIMIT = 500

#: Rola danych, w ktorej wiersz tabeli trzyma identyfikator swojego rekordu.
#: Sortowanie i filtrowanie zmieniaja numery wierszy, identyfikator nie.
ROW_ID_ROLE = Qt.ItemDataRole.UserRole

#: Pary (klucz, podpis) siatki statystyk. Kolejnosc decyduje o ukladzie.
STAT_ENTRIES: tuple[tuple[str, str], ...] = (
    ("discovered", i18n.STAT_DISCOVERED),
    ("processed", i18n.STAT_PROCESSED),
    ("unchanged", i18n.STAT_UNCHANGED),
    ("skipped", i18n.STAT_SKIPPED),
    ("failed", i18n.STAT_FAILED),
    ("deleted", i18n.STAT_DELETED),
    ("ocr_documents", i18n.STAT_OCR),
    ("ocr_pages", i18n.STAT_OCR_PAGES),
    ("elapsed", i18n.STAT_ELAPSED),
    ("connection", i18n.STAT_CONNECTION),
    ("temp", i18n.STAT_TEMP),
)


def idle_stats() -> dict[str, str]:
    """Wartosci statystyk przed uruchomieniem zadania.

    Liczniki startuja od zera, ale czas trwania, stan polaczenia i zajete
    miejsce nie sa licznikami. ,,Polaczenie: 0'' nic nie znaczy.
    """
    values: dict[str, str] = {key: "0" for key, _ in STAT_ENTRIES}
    values["elapsed"] = i18n.format_duration(0)
    values["connection"] = i18n.STAT_NONE
    values["temp"] = i18n.format_bytes(0)
    return values


class IndexingView(QWidget):
    """Sterowanie indeksowaniem i podglad postepu."""

    status_message = Signal(str)
    index_changed = Signal()

    def __init__(self, context: AppContext) -> None:
        super().__init__()
        self.context = context
        self.bridge = ProgressBridge()
        self.bridge.progress.connect(self._on_progress)
        self.bridge.completed.connect(self._on_completed)
        self._last_state: JobState | None = None

        root = page_layout(self)

        self.header = PageHeader(i18n.INDEXING_TITLE, meta=i18n.INDEXING_IDLE)
        root.addWidget(self.header)

        root.addLayout(self._build_buttons())
        root.addWidget(self._build_last_run())
        root.addWidget(self._build_progress())
        root.addWidget(self._build_stats())
        root.addWidget(self._build_tables(), stretch=1)

        # Karty postepu i statystyk opisuja biezace zadanie, wiec przed jego
        # uruchomieniem sa ukryte. W ich miejscu jest ostatni przebieg.
        self.progress_box.setVisible(False)
        self.stats_box.setVisible(False)
        self._refresh_last_run()
        self._refresh_buttons()

    # --- budowa -----------------------------------------------------------

    def _build_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(SPACE_SM)

        self.start_button = QPushButton(i18n.INDEXING_SCAN)
        self.start_button.setObjectName("Primary")
        self.start_button.setIcon(accent_icon("play"))
        self.start_button.setToolTip(i18n.INDEXING_SCAN_HINT)
        self.start_button.clicked.connect(self.start_scan)
        row.addWidget(self.start_button)

        # Jeden przycisk na wstrzymanie i wznowienie: w danej chwili tylko jedna
        # z tych akcji ma sens, wiec druga bylaby wylacznie szarym napisem.
        self.pause_button = QPushButton(i18n.INDEXING_PAUSE)
        self.pause_button.setIcon(theme_icon("pause"))
        self.pause_button.clicked.connect(self.toggle_pause)
        row.addWidget(self.pause_button)

        self.cancel_button = QPushButton(i18n.INDEXING_CANCEL)
        self.cancel_button.setIcon(theme_icon("cross"))
        self.cancel_button.setToolTip(i18n.INDEXING_CANCEL_HINT)
        self.cancel_button.clicked.connect(self.cancel_job)
        row.addWidget(self.cancel_button)

        self.full_button = QPushButton(i18n.INDEXING_FULL)
        self.full_button.setIcon(theme_icon("database"))
        self.full_button.setToolTip(i18n.INDEXING_FULL_HINT)
        self.full_button.clicked.connect(self.start_full_reindex)
        row.addWidget(self.full_button)

        row.addStretch(1)

        self.export_button = QPushButton(i18n.INDEXING_EXPORT)
        self.export_button.setIcon(theme_icon("export"))
        self.export_button.clicked.connect(self.export_report)
        row.addWidget(self.export_button)
        return row

    def _build_last_run(self) -> QWidget:
        """Podsumowanie ostatniego zakonczonego przebiegu, widoczne w spoczynku."""
        box = QGroupBox(i18n.INDEXING_LAST_RUN)
        layout = QVBoxLayout(box)
        layout.setSpacing(SPACE_SM)
        self.last_run_label = QLabel("")
        self.last_run_label.setWordWrap(True)
        layout.addWidget(self.last_run_label)
        self.last_run_box = box
        return box

    def _refresh_last_run(self) -> None:
        """Wypelnia podsumowanie z historii zadan. Bez historii karta znika."""
        finished_states = {
            JobState.COMPLETED.value,
            JobState.FAILED.value,
            JobState.CANCELLED.value,
        }
        row = None
        index = self.context.index
        if index is not None:
            try:
                rows = index.repository.recent_jobs(limit=20)
            except Exception as exc:
                log.warning("gui.last_run_failed", error_type=type(exc).__name__)
                rows = []
            row = next((r for r in rows if str(r["state"]) in finished_states), None)
        if row is None:
            self.last_run_box.setVisible(False)
            return
        try:
            progress = json.loads(str(row["progress"] or "{}"))
        except ValueError:
            progress = {}
        kind = str(row["kind"] or "")
        kind_label = i18n.JOB_KIND_LABELS.get(kind, kind)
        state_label = i18n.JOB_STATE_LABELS.get(JobState(str(row["state"])), str(row["state"]))
        stamp = format_stamp(str(row["finished_at"] or row["created_at"] or ""))
        summary = i18n.INDEXING_LAST_RUN_SUMMARY.format(
            processed=progress.get("processed", 0),
            failed=progress.get("failed", 0),
            skipped=progress.get("skipped", 0),
            elapsed=i18n.format_duration(float(progress.get("elapsed_seconds", 0.0))),
        )
        self.last_run_label.setText(f"{kind_label}, {stamp}: {state_label}.\n{summary}")
        self.last_run_box.setVisible(True)

    def _build_progress(self) -> QWidget:
        box = QGroupBox(i18n.STAGE_LABEL)
        layout = QVBoxLayout(box)
        layout.setSpacing(SPACE_SM)

        self.stage_label = QLabel(i18n.INDEXING_IDLE)
        layout.addWidget(self.stage_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")
        layout.addWidget(self.progress_bar)

        # Podpowiedz o postepie i nazwa pliku maja sens tylko w trakcie pracy.
        # Przed uruchomieniem sa ukryte, zeby karta nie klamala o stanie zadania.
        self.progress_hint = QLabel("")
        self.progress_hint.setObjectName("Hint")
        self.progress_hint.setVisible(False)
        layout.addWidget(self.progress_hint)

        self.current_file_label = QLabel("")
        self.current_file_label.setObjectName("Hint")
        self.current_file_label.setWordWrap(True)
        self.current_file_label.setVisible(False)
        layout.addWidget(self.current_file_label)
        self.progress_box = box
        return box

    def _build_stats(self) -> QWidget:
        box = QGroupBox("Statystyki")
        layout = QVBoxLayout(box)
        self.stats = StatGrid(STAT_ENTRIES, columns=4)
        self.stats.set_values(idle_stats())
        # Testy i kod widoku siegaja po etykiety wartosci po kluczu.
        self._stat_labels = self.stats.labels
        # Liczba bledow wieksza od zera to jedyna liczba wymagajaca reakcji,
        # wiec jest klikalna i prowadzi do listy plikow poza indeksem, czyli
        # tam, gdzie z tymi plikami mozna cos zrobic.
        failed = self.stats.labels["failed"]
        failed.setCursor(Qt.CursorShape.PointingHandCursor)
        failed.setToolTip(i18n.STAT_FAILED_HINT)
        failed.installEventFilter(self)
        layout.addWidget(self.stats)
        self.stats_box = box
        return box

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            watched is self.stats.labels.get("failed")
            and event.type() is QEvent.Type.MouseButtonRelease
        ):
            self._tabs.setCurrentIndex(0)
            return True
        return super().eventFilter(watched, event)

    def _build_tables(self) -> QWidget:
        self.problems_table = self._make_table(
            ["Plik", "Lokalizacja", "Powód", "Szczegóły", "Ostatnia próba"], stretch=(0, 1, 3)
        )
        self.error_table = self._make_table(
            ["Plik", "Etap", "Kod", "Komunikat", "Czas"], stretch=(0, 3)
        )
        # Filtr po prawej stronie paska zakladek zaweza obie tabele do wierszy
        # zawierajacych wpisany tekst. Liczby w nazwach zakladek zostaja pelne.
        self.table_filter = QLineEdit()
        self.table_filter.setPlaceholderText(i18n.TABLE_FILTER_PLACEHOLDER)
        self.table_filter.setAccessibleName(i18n.TABLE_FILTER_PLACEHOLDER)
        self.table_filter.setClearButtonEnabled(True)
        self.table_filter.setFixedWidth(220)
        self.table_filter.textChanged.connect(lambda _text: self._apply_table_filter())

        self.retry_button = QPushButton(i18n.INDEXING_RETRY)
        self.retry_button.setIcon(theme_icon("refresh"))
        self.retry_button.setToolTip(i18n.INDEXING_RETRY_HINT)
        self.retry_button.clicked.connect(self.retry_selected)

        self.delete_errors_button = QPushButton(i18n.INDEXING_ERRORS_DELETE)
        self.delete_errors_button.setIcon(theme_icon("trash"))
        self.delete_errors_button.setToolTip(i18n.INDEXING_ERRORS_DELETE_HINT)
        self.delete_errors_button.clicked.connect(self.delete_selected_errors)

        self.clear_errors_button = QPushButton(i18n.INDEXING_ERRORS_CLEAR)
        self.clear_errors_button.clicked.connect(self.clear_error_log)

        self.problems_hint = QLabel(i18n.INDEXING_PROBLEMS_HINT)
        self.errors_hint = QLabel(i18n.INDEXING_ERRORS_HINT)

        tabs = TabPanel(side_widget=self.table_filter)
        tabs.addTab(
            self._table_page(self.problems_hint, self.problems_table, (self.retry_button,)),
            i18n.INDEXING_TAB_PROBLEMS,
        )
        tabs.addTab(
            self._table_page(
                self.errors_hint,
                self.error_table,
                (self.delete_errors_button, self.clear_errors_button),
            ),
            i18n.INDEXING_TAB_ERRORS,
        )
        tabs.currentChanged.connect(lambda _index: self.refresh_tables())
        self._tabs = tabs
        return tabs

    def _table_page(
        self, hint: QLabel, table: QTableWidget, buttons: tuple[QPushButton, ...]
    ) -> QWidget:
        """Strona zakladki: zdanie o tym, co jest na liscie, tabela i akcje.

        Sama tabela nie tlumaczy, czym rozni sie od sasiedniej ani co zrobic
        z wierszem. Zdanie nad nia odpowiada na oba pytania, a przyciski pod
        nia dzialaja na zaznaczeniu, wiec sa nieaktywne, dopoki nic nie wybrano.
        """
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_SM)
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addWidget(table, stretch=1)
        row = QHBoxLayout()
        row.setSpacing(SPACE_SM)
        for button in buttons:
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)
        return page

    def _apply_table_filter(self) -> None:
        for table in (self.problems_table, self.error_table):
            filter_table_rows(table, self.table_filter.text())

    def _make_table(self, headers: list[str], *, stretch: tuple[int, ...]) -> QTableWidget:
        """Tabela, w ktorej kolumny opisowe dostaja wolne miejsce, a krotkie tyle, ile trzeba."""
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        table.setAlternatingRowColors(False)
        table.verticalHeader().setVisible(False)
        table.itemSelectionChanged.connect(self._refresh_row_actions)
        configure_columns(table, stretch)
        return table

    # --- akcje ------------------------------------------------------------

    def start_scan(self) -> None:
        self._submit(JobOptions(kind=JobKind.RESCAN))

    def start_full_reindex(self) -> None:
        if not ask_yes_no(self, i18n.CONFIRM_FULL_REINDEX, i18n.CONFIRM_TITLE):
            return
        self._submit(JobOptions(kind=JobKind.FULL_INDEX, force_reindex=True))

    def resume_interrupted(self, job_id: str) -> None:
        self._submit(JobOptions(kind=JobKind.RESCAN, resume_job_id=job_id))

    def _submit(self, options: JobOptions) -> None:
        if not self.context.config.enabled_sources():
            show_warning(self, i18n.SOURCES_EMPTY)
            return
        runner = self.context.require_runner()
        if runner.is_running:
            show_info(self, "Indeksowanie już trwa. Poczekaj albo je anuluj.")
            return
        runner.on_progress(self.bridge.publish)
        runner.on_completed(self.bridge.publish_completion)
        runner.submit(options)
        self.status_message.emit("Uruchomiono indeksowanie.")
        self._refresh_buttons()

    # --- akcje na listach -------------------------------------------------

    def _selected_ids(self, table: QTableWidget) -> list[int]:
        """Identyfikatory rekordow z zaznaczonych, widocznych wierszy tabeli.

        Wiersze ukryte filtrem sa pomijane: dzialanie na czyms, czego nie widac,
        jest zaskoczeniem, a zaznaczenie przezywa wpisanie tekstu w filtr.
        """
        ids: list[int] = []
        for index in table.selectionModel().selectedRows():
            if table.isRowHidden(index.row()):
                continue
            item = table.item(index.row(), 0)
            value = None if item is None else item.data(ROW_ID_ROLE)
            if value is not None:
                ids.append(int(value))
        return ids

    def _busy(self) -> bool:
        """Czy trwa zadanie. W jego trakcie listy zmienia sam potok indeksowania."""
        runner = self.context.runner
        if runner is not None and runner.is_running:
            self.status_message.emit(i18n.INDEXING_LIST_BUSY)
            return True
        return False

    def retry_selected(self) -> None:
        """Oddaje zaznaczone pliki do ponownego przetworzenia i czysci ich wpisy."""
        doc_ids = self._selected_ids(self.problems_table)
        if not doc_ids or self._busy():
            return
        index = self.context.require_index()

        def work() -> int:
            with index.db.transaction():
                return index.repository.requeue_documents(doc_ids)

        self._run_list_task(work, "ponowne przetworzenie", self._after_retry)

    def _after_retry(self, count: int) -> None:
        self.refresh_tables()
        self.index_changed.emit()
        self.status_message.emit(i18n.INDEXING_RETRY_DONE.format(count=count))
        # Ponowne przetworzenie dzieje sie przy skanowaniu, wiec pytamy od razu.
        # Bez tego pytania trzeba wiedziec, ze samo zaznaczenie niczego nie
        # przetwarza, dopoki ktos nie kliknie ,,Skanuj zrodla''.
        running = self.context.runner is not None and self.context.runner.is_running
        if count and not running and ask_yes_no(self, i18n.INDEXING_RETRY_SCAN_PROMPT):
            self.start_scan()

    def delete_selected_errors(self) -> None:
        """Usuwa zaznaczone wpisy dziennika. Stan plikow zostaje bez zmian."""
        error_ids = self._selected_ids(self.error_table)
        if not error_ids or self._busy():
            return
        index = self.context.require_index()

        def work() -> int:
            return index.repository.delete_errors(error_ids)

        self._run_list_task(work, "usuwanie wpisów", self._after_errors_removed)

    def clear_error_log(self) -> None:
        """Czysci caly dziennik po potwierdzeniu."""
        if self._busy():
            return
        if not ask_yes_no(self, i18n.INDEXING_ERRORS_CLEAR_CONFIRM, i18n.CONFIRM_TITLE):
            return
        index = self.context.require_index()

        def work() -> int:
            return index.repository.clear_errors()

        self._run_list_task(work, "czyszczenie dziennika", self._after_errors_removed)

    def _after_errors_removed(self, count: int) -> None:
        self.refresh_tables()
        self.status_message.emit(i18n.INDEXING_ERRORS_CLEARED.format(count=count))

    def _run_list_task(
        self, work: Callable[[], int], label: str, done: Callable[[int], None]
    ) -> None:
        """Uruchamia krotka operacje na bazie poza watkiem interfejsu."""
        task = CallableTask(work, label=label)
        task.signals.finished.connect(lambda result: done(int(result) if result else 0))
        task.signals.failed.connect(
            lambda code, message: show_error(self, f"{message}\n\nKod: {code}")
        )
        thread_pool().start(task)

    def toggle_pause(self) -> None:
        """Wstrzymuje zadanie, a gdy jest wstrzymane, wznawia je."""
        runner = self.context.require_runner()
        if runner.is_paused:
            if runner.resume():
                self.status_message.emit("Indeksowanie wznowione.")
        elif runner.pause():
            self.status_message.emit("Indeksowanie wstrzymane.")
        self._refresh_buttons()

    def cancel_job(self) -> None:
        if self.context.require_runner().cancel():
            self.status_message.emit("Anulowanie indeksowania...")
        self._refresh_buttons()

    def export_report(self) -> None:
        path, selected = QFileDialog.getSaveFileName(
            self,
            i18n.INDEXING_EXPORT,
            str(self.context.paths.reports_dir / "raport-pokrycia.csv"),
            "Plik CSV (*.csv);;Plik JSON (*.json)",
        )
        if not path:
            return

        def work() -> str:
            from pathlib import Path

            from finddocs.diagnostics.coverage_report import build_coverage_report
            from finddocs.diagnostics.export import export_coverage_csv, export_coverage_json

            report = build_coverage_report(self.context.require_index())
            target = Path(path)
            if target.suffix.lower() == ".json" or "JSON" in selected:
                return str(export_coverage_json(report, target))
            return str(export_coverage_csv(report, target))

        task = CallableTask(work, label="eksport raportu")
        task.signals.finished.connect(
            lambda result: self.status_message.emit(f"Zapisano raport: {result}")
        )
        task.signals.failed.connect(
            lambda code, message: show_error(self, f"{message}\n\nKod: {code}")
        )
        thread_pool().start(task)

    # --- reakcje na postep ------------------------------------------------

    def _on_progress(self, snapshot: object) -> None:
        if not isinstance(snapshot, ProgressSnapshot):
            return
        # Pierwsza migawka zadania odsuwa podsumowanie ostatniego przebiegu
        # i pokazuje karty biezacego postepu.
        if self.progress_box.isHidden():
            self.progress_box.setVisible(True)
            self.stats_box.setVisible(True)
            self.last_run_box.setVisible(False)
        state_label = i18n.JOB_STATE_LABELS.get(snapshot.state, snapshot.state.value)
        self.stage_label.setText(f"{snapshot.stage_label} ({state_label})")
        self.header.set_meta(state_label)

        fraction = snapshot.progress_fraction
        self.progress_hint.setVisible(True)
        if fraction is None:
            self.progress_bar.setRange(0, 0)
            self.progress_hint.setText(i18n.PROGRESS_UNKNOWN)
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(int(fraction * 100))
            self.progress_hint.setText(
                i18n.PROGRESS_APPROXIMATE.format(value=f"{fraction * 100:.1f}%")
            )

        self.current_file_label.setVisible(bool(snapshot.current_file))
        self.current_file_label.setText(
            i18n.STAT_CURRENT + ": " + (snapshot.current_file or i18n.STAT_NONE)
        )
        self.stats.set_values(
            {
                "discovered": snapshot.discovered,
                "processed": snapshot.processed,
                "unchanged": snapshot.unchanged,
                "skipped": snapshot.skipped,
                "failed": snapshot.failed,
                "deleted": snapshot.deleted,
                "ocr_documents": snapshot.ocr_documents,
                "ocr_pages": snapshot.ocr_pages,
                "elapsed": i18n.format_duration(snapshot.elapsed_seconds),
                "connection": snapshot.connection_status or i18n.STAT_NONE,
                "temp": i18n.format_bytes(snapshot.temp_bytes_used),
            }
        )
        # Bledy to jedyna liczba wymagajaca reakcji, wiec dostaje kolor bledu.
        self.stats.set_value_role("failed", "danger" if snapshot.failed else "")
        self._last_state = snapshot.state
        self._refresh_buttons()

    def _on_completed(self, snapshot: object) -> None:
        if not isinstance(snapshot, ProgressSnapshot):
            return
        self._on_progress(snapshot)
        self.progress_bar.setRange(0, 100)
        if snapshot.state is JobState.COMPLETED:
            self.progress_bar.setValue(100)
            self.status_message.emit(
                f"Indeksowanie zakończone. Przetworzono {snapshot.processed} dokumentów."
            )
        elif snapshot.state is JobState.CANCELLED:
            self.status_message.emit("Indeksowanie anulowane. Można je wznowić później.")
        else:
            self.status_message.emit(snapshot.message or "Indeksowanie zakończone błędem.")
            show_error(
                self,
                snapshot.message or "Indeksowanie zakończyło się błędem.",
            )
        self.current_file_label.setVisible(False)
        self.refresh_tables()
        self.index_changed.emit()
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        runner = self.context.runner
        running = runner is not None and runner.is_running
        paused = runner is not None and runner.is_paused
        self.start_button.setEnabled(not running)
        self.full_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        self.pause_button.setEnabled(running)
        self.pause_button.setText(i18n.INDEXING_RESUME if paused else i18n.INDEXING_PAUSE)
        self.pause_button.setIcon(theme_icon("play" if paused else "pause"))
        self._refresh_row_actions()

    # --- tabele -----------------------------------------------------------

    def refresh_tables(self) -> None:
        index = self.context.index
        if index is None:
            return
        self._fill_problems(index)
        self._fill_errors(index)
        self._refresh_tab_labels()
        self._apply_table_filter()
        self._refresh_row_actions()

    def _fill_problems(self, index: IndexService) -> None:
        """Lista plikow, ktorych nie ma w wynikach, po jednym wierszu na plik.

        Dokumenty oczekujace w kolejce nie sa problemem do rozwiazania przez
        uzytkownika, wiec nie zajmuja miejsca na liscie.
        """
        try:
            documents = index.repository.non_searchable_documents(
                limit=ERROR_TABLE_LIMIT, include_pending=False
            )
        except Exception as exc:
            log.warning("gui.problems_refresh_failed", error_type=type(exc).__name__)
            documents = []
        with populate_rows(self.problems_table):
            self.problems_table.setRowCount(0)
            for document in documents:
                position = self.problems_table.rowCount()
                self.problems_table.insertRow(position)
                values = [
                    document.name,
                    document.logical_path,
                    i18n.status_label(document.status),
                    document.error_message or i18n.status_hint(document.status),
                    format_stamp(
                        document.last_attempt_at.isoformat() if document.last_attempt_at else ""
                    ),
                ]
                for column, value in enumerate(values):
                    item = text_item(value)
                    if column == 0:
                        item.setData(ROW_ID_ROLE, document.doc_id)
                    self.problems_table.setItem(position, column, item)
        self.problems_hint.setText(
            i18n.INDEXING_PROBLEMS_HINT if documents else i18n.INDEXING_PROBLEMS_EMPTY
        )

    def _fill_errors(self, index: IndexService) -> None:
        """Dziennik ostatnich prob: jeden wpis na plik plus bledy calego zrodla."""
        try:
            errors = index.repository.recent_errors(ERROR_TABLE_LIMIT)
        except Exception as exc:
            log.warning("gui.errors_refresh_failed", error_type=type(exc).__name__)
            errors = []
        with populate_rows(self.error_table):
            self.error_table.setRowCount(0)
            for row in errors:
                position = self.error_table.rowCount()
                self.error_table.insertRow(position)
                stage = str(row["stage"] or "")
                values = [
                    str(row["file_name"] or ""),
                    i18n.STAGE_LABELS.get(stage, stage),
                    str(row["code"] or ""),
                    str(row["message"] or ""),
                    format_stamp(str(row["created_at"] or "")),
                ]
                for column, value in enumerate(values):
                    item = text_item(value)
                    if column == 0:
                        item.setData(ROW_ID_ROLE, int(row["id"]))
                    self.error_table.setItem(position, column, item)
        self.errors_hint.setText(
            i18n.INDEXING_ERRORS_HINT if errors else i18n.INDEXING_ERRORS_EMPTY
        )

    def _refresh_tab_labels(self) -> None:
        """Nazwa zakladki niesie liczbe wierszy, wiec nie trzeba jej otwierac."""
        for position, (name, table) in enumerate(
            (
                (i18n.INDEXING_TAB_PROBLEMS, self.problems_table),
                (i18n.INDEXING_TAB_ERRORS, self.error_table),
            )
        ):
            count = table.rowCount()
            label = i18n.INDEXING_TAB_COUNT.format(name=name, count=count) if count else name
            self._tabs.setTabText(position, label)

    def _refresh_row_actions(self) -> None:
        """Akcje list dzialaja na zaznaczeniu, wiec bez niego sa nieaktywne."""
        running = self.context.runner is not None and self.context.runner.is_running
        self.retry_button.setEnabled(
            not running and bool(self.problems_table.selectionModel().selectedRows())
        )
        self.delete_errors_button.setEnabled(
            not running and bool(self.error_table.selectionModel().selectedRows())
        )
        self.clear_errors_button.setEnabled(not running and self.error_table.rowCount() > 0)


__all__ = ["ERROR_TABLE_LIMIT", "ROW_ID_ROLE", "STAT_ENTRIES", "IndexingView", "idle_stats"]

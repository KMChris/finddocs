"""Ekran indeksowania: postep, sterowanie, bledy i pliki pominiete.

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
"""

from __future__ import annotations

import json

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
from finddocs.gui.tables import configure_columns, filter_table_rows, format_stamp, text_item
from finddocs.gui.theme import SPACE_SM, accent_icon, theme_icon
from finddocs.gui.widgets.page import PageHeader, page_layout
from finddocs.gui.widgets.stat_grid import StatGrid
from finddocs.gui.widgets.tabs import TabPanel
from finddocs.gui.workers import CallableTask, ProgressBridge, thread_pool
from finddocs.jobs.indexing_job import JobOptions
from finddocs.logging_setup import get_logger
from finddocs.types import DocumentStatus, JobKind, JobState, ProgressSnapshot

log = get_logger(__name__)

ERROR_TABLE_LIMIT = 500

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
        # wiec jest klikalna i prowadzi do zakladki z lista bledow.
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
        self.error_table = self._make_table(
            ["Plik", "Etap", "Kod", "Komunikat", "Czas"], stretch=(0, 3)
        )
        self.skipped_table = self._make_table(
            ["Plik", "Lokalizacja", "Status", "Powód"], stretch=(0, 1, 3)
        )
        # Filtr po prawej stronie paska zakladek zaweza obie tabele do wierszy
        # zawierajacych wpisany tekst. Liczby w nazwach zakladek zostaja pelne.
        self.table_filter = QLineEdit()
        self.table_filter.setPlaceholderText(i18n.TABLE_FILTER_PLACEHOLDER)
        self.table_filter.setAccessibleName(i18n.TABLE_FILTER_PLACEHOLDER)
        self.table_filter.setClearButtonEnabled(True)
        self.table_filter.setFixedWidth(220)
        self.table_filter.textChanged.connect(lambda _text: self._apply_table_filter())
        tabs = TabPanel(side_widget=self.table_filter)
        tabs.addTab(self.error_table, i18n.INDEXING_TAB_ERRORS)
        tabs.addTab(self.skipped_table, i18n.INDEXING_TAB_SKIPPED)
        tabs.currentChanged.connect(lambda _index: self.refresh_tables())
        self._tabs = tabs
        return tabs

    def _apply_table_filter(self) -> None:
        for table in (self.error_table, self.skipped_table):
            filter_table_rows(table, self.table_filter.text())

    def _make_table(self, headers: list[str], *, stretch: tuple[int, ...]) -> QTableWidget:
        """Tabela, w ktorej kolumny opisowe dostaja wolne miejsce, a krotkie tyle, ile trzeba."""
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(False)
        table.verticalHeader().setVisible(False)
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

    # --- tabele -----------------------------------------------------------

    def refresh_tables(self) -> None:
        index = self.context.index
        if index is None:
            return
        try:
            errors = index.repository.recent_errors(ERROR_TABLE_LIMIT)
        except Exception as exc:
            log.warning("gui.errors_refresh_failed", error_type=type(exc).__name__)
            return
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
                self.error_table.setItem(position, column, text_item(value))

        self.skipped_table.setRowCount(0)
        try:
            documents = index.repository.non_searchable_documents(limit=ERROR_TABLE_LIMIT)
        except Exception as exc:
            log.warning("gui.skipped_refresh_failed", error_type=type(exc).__name__)
            self._refresh_tab_labels()
            return
        for document in documents:
            if document.status is DocumentStatus.PENDING:
                continue
            position = self.skipped_table.rowCount()
            self.skipped_table.insertRow(position)
            values = [
                document.name,
                document.logical_path,
                i18n.STATUS_LABELS.get(document.status, document.status.value),
                document.error_message or "",
            ]
            for column, value in enumerate(values):
                self.skipped_table.setItem(position, column, text_item(value))
        self._refresh_tab_labels()
        self._apply_table_filter()

    def _refresh_tab_labels(self) -> None:
        """Nazwa zakladki niesie liczbe wierszy, wiec nie trzeba jej otwierac."""
        for position, (name, table) in enumerate(
            (
                (i18n.INDEXING_TAB_ERRORS, self.error_table),
                (i18n.INDEXING_TAB_SKIPPED, self.skipped_table),
            )
        ):
            count = table.rowCount()
            label = i18n.INDEXING_TAB_COUNT.format(name=name, count=count) if count else name
            self._tabs.setTabText(position, label)


__all__ = ["ERROR_TABLE_LIMIT", "STAT_ENTRIES", "IndexingView", "idle_stats"]

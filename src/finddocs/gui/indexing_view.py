"""Ekran indeksowania: postep, sterowanie, bledy i pliki pominiete."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from finddocs.gui import i18n
from finddocs.gui.context import AppContext
from finddocs.gui.dialogs import ask_yes_no, show_error, show_info, show_warning
from finddocs.gui.tables import configure_columns, format_stamp
from finddocs.gui.workers import CallableTask, ProgressBridge, thread_pool
from finddocs.jobs.indexing_job import JobOptions
from finddocs.logging_setup import get_logger
from finddocs.types import DocumentStatus, JobKind, JobState, ProgressSnapshot

log = get_logger(__name__)

ERROR_TABLE_LIMIT = 500


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

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(12)

        title = QLabel(i18n.INDEXING_TITLE)
        title.setObjectName("PageTitle")
        root.addWidget(title)

        root.addLayout(self._build_buttons())
        root.addWidget(self._build_progress())
        root.addWidget(self._build_stats())
        root.addWidget(self._build_tables(), stretch=1)

        self._refresh_buttons()

    # --- budowa -----------------------------------------------------------

    def _build_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self.start_button = QPushButton(i18n.INDEXING_START)
        self.start_button.setObjectName("Primary")
        self.start_button.clicked.connect(self.start_scan)
        row.addWidget(self.start_button)

        self.pause_button = QPushButton(i18n.INDEXING_PAUSE)
        self.pause_button.clicked.connect(self.pause_job)
        row.addWidget(self.pause_button)

        self.resume_button = QPushButton(i18n.INDEXING_RESUME)
        self.resume_button.clicked.connect(self.resume_job)
        row.addWidget(self.resume_button)

        self.cancel_button = QPushButton(i18n.INDEXING_CANCEL)
        self.cancel_button.clicked.connect(self.cancel_job)
        row.addWidget(self.cancel_button)

        self.rescan_button = QPushButton(i18n.INDEXING_RESCAN)
        self.rescan_button.clicked.connect(self.start_scan)
        row.addWidget(self.rescan_button)

        self.full_button = QPushButton(i18n.INDEXING_FULL)
        self.full_button.clicked.connect(self.start_full_reindex)
        row.addWidget(self.full_button)

        row.addStretch(1)

        self.export_button = QPushButton(i18n.INDEXING_EXPORT)
        self.export_button.clicked.connect(self.export_report)
        row.addWidget(self.export_button)
        return row

    def _build_progress(self) -> QWidget:
        box = QGroupBox(i18n.STAGE_LABEL)
        layout = QVBoxLayout(box)
        layout.setSpacing(8)

        self.stage_label = QLabel("Gotowe do uruchomienia")
        layout.addWidget(self.stage_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")
        layout.addWidget(self.progress_bar)

        self.progress_hint = QLabel(i18n.PROGRESS_UNKNOWN)
        self.progress_hint.setObjectName("Muted")
        layout.addWidget(self.progress_hint)

        self.current_file_label = QLabel("")
        self.current_file_label.setObjectName("Muted")
        self.current_file_label.setWordWrap(True)
        layout.addWidget(self.current_file_label)
        return box

    def _build_stats(self) -> QWidget:
        box = QGroupBox("Statystyki")
        grid = QGridLayout(box)
        grid.setHorizontalSpacing(32)
        # Podpis przylega do swojej wartosci, a grupy rozdziela pusty wiersz.
        grid.setVerticalSpacing(2)

        self._stat_labels: dict[str, QLabel] = {}
        entries = [
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
        ]
        for index, (key, label_text) in enumerate(entries):
            column = index % 4
            row = index // 4
            caption = QLabel(label_text)
            caption.setObjectName("Muted")
            value = QLabel("0")
            value.setObjectName("StatValue")
            value.setAlignment(Qt.AlignmentFlag.AlignLeft)
            grid.addWidget(caption, row * 3, column)
            grid.addWidget(value, row * 3 + 1, column)
            self._stat_labels[key] = value
        rows = -(-len(entries) // 4)
        for row in range(rows - 1):
            grid.setRowMinimumHeight(row * 3 + 2, 12)
        return box

    def _build_tables(self) -> QWidget:
        tabs = QTabWidget()
        self.error_table = self._make_table(
            ["Plik", "Etap", "Kod", "Komunikat", "Czas"], stretch=(0, 3)
        )
        self.skipped_table = self._make_table(
            ["Plik", "Lokalizacja", "Status", "Powód"], stretch=(0, 1, 3)
        )
        tabs.addTab(self.error_table, i18n.INDEXING_SHOW_ERRORS)
        tabs.addTab(self.skipped_table, i18n.INDEXING_SHOW_SKIPPED)
        tabs.currentChanged.connect(lambda _index: self.refresh_tables())
        self._tabs = tabs
        return tabs

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

    def pause_job(self) -> None:
        if self.context.require_runner().pause():
            self.status_message.emit("Indeksowanie wstrzymane.")
        self._refresh_buttons()

    def resume_job(self) -> None:
        if self.context.require_runner().resume():
            self.status_message.emit("Indeksowanie wznowione.")
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
        state_label = i18n.JOB_STATE_LABELS.get(snapshot.state, snapshot.state.value)
        self.stage_label.setText(f"{snapshot.stage_label} ({state_label})")

        fraction = snapshot.progress_fraction
        if fraction is None:
            self.progress_bar.setRange(0, 0)
            self.progress_hint.setText(i18n.PROGRESS_UNKNOWN)
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(int(fraction * 100))
            self.progress_hint.setText(
                i18n.PROGRESS_APPROXIMATE.format(value=f"{fraction * 100:.1f}%")
            )

        self.current_file_label.setText(
            i18n.STAT_CURRENT + ": " + (snapshot.current_file or "brak")
        )
        self._stat_labels["discovered"].setText(str(snapshot.discovered))
        self._stat_labels["processed"].setText(str(snapshot.processed))
        self._stat_labels["unchanged"].setText(str(snapshot.unchanged))
        self._stat_labels["skipped"].setText(str(snapshot.skipped))
        self._stat_labels["failed"].setText(str(snapshot.failed))
        self._stat_labels["deleted"].setText(str(snapshot.deleted))
        self._stat_labels["ocr_documents"].setText(str(snapshot.ocr_documents))
        self._stat_labels["ocr_pages"].setText(str(snapshot.ocr_pages))
        self._stat_labels["elapsed"].setText(i18n.format_duration(snapshot.elapsed_seconds))
        self._stat_labels["connection"].setText(snapshot.connection_status)
        self._stat_labels["temp"].setText(i18n.format_bytes(snapshot.temp_bytes_used))
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
        self.refresh_tables()
        self.index_changed.emit()
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        runner = self.context.runner
        running = runner is not None and runner.is_running
        paused = runner is not None and runner.is_paused
        self.start_button.setEnabled(not running)
        self.rescan_button.setEnabled(not running)
        self.full_button.setEnabled(not running)
        self.pause_button.setEnabled(running and not paused)
        self.resume_button.setEnabled(running and paused)
        self.cancel_button.setEnabled(running)

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
            values = [
                str(row["file_name"] or ""),
                str(row["stage"] or ""),
                str(row["code"] or ""),
                str(row["message"] or ""),
                format_stamp(str(row["created_at"] or "")),
            ]
            for column, value in enumerate(values):
                self.error_table.setItem(position, column, QTableWidgetItem(value))

        self.skipped_table.setRowCount(0)
        try:
            documents = index.repository.non_searchable_documents(limit=ERROR_TABLE_LIMIT)
        except Exception as exc:
            log.warning("gui.skipped_refresh_failed", error_type=type(exc).__name__)
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
                self.skipped_table.setItem(position, column, QTableWidgetItem(value))


__all__ = ["ERROR_TABLE_LIMIT", "IndexingView"]

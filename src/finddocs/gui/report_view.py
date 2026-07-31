"""Ekran raportu pokrycia indeksu."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from finddocs.gui import i18n
from finddocs.gui.context import AppContext
from finddocs.gui.dialogs import show_error, show_info
from finddocs.gui.tables import configure_columns
from finddocs.gui.workers import CallableTask, thread_pool
from finddocs.logging_setup import get_logger
from finddocs.types import CoverageReport

log = get_logger(__name__)

NON_SEARCHABLE_LIMIT = 2000


class ReportView(QWidget):
    """Podglad i eksport raportu pokrycia."""

    status_message = Signal(str)

    def __init__(self, context: AppContext) -> None:
        super().__init__()
        self.context = context
        self._report: CoverageReport | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(12)

        title = QLabel(i18n.REPORT_TITLE)
        title.setObjectName("PageTitle")
        root.addWidget(title)

        buttons = QHBoxLayout()
        refresh = QPushButton(i18n.REPORT_REFRESH)
        refresh.setObjectName("Primary")
        refresh.clicked.connect(self.refresh)
        buttons.addWidget(refresh)

        export_json = QPushButton(i18n.REPORT_EXPORT_JSON)
        export_json.clicked.connect(lambda: self.export("json"))
        buttons.addWidget(export_json)

        export_csv = QPushButton(i18n.REPORT_EXPORT_CSV)
        export_csv.clicked.connect(lambda: self.export("csv"))
        buttons.addWidget(export_csv)
        buttons.addStretch(1)
        root.addLayout(buttons)

        self.completeness = QLabel("")
        self.completeness.setWordWrap(True)
        root.addWidget(self.completeness)

        self.summary_box = QGroupBox("Podsumowanie")
        self.summary_grid = QGridLayout(self.summary_box)
        self.summary_grid.setHorizontalSpacing(24)
        self.summary_grid.setVerticalSpacing(6)
        root.addWidget(self.summary_box)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Nazwa", "Lokalizacja", "Status", "Kod błędu", "Komunikat"]
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        configure_columns(self.table, (1, 4))

        table_title = QLabel(i18n.REPORT_NON_SEARCHABLE)
        table_title.setObjectName("SectionTitle")
        root.addWidget(table_title)
        root.addWidget(self.table, stretch=1)

    # --- dane -------------------------------------------------------------

    def refresh(self) -> None:
        self.status_message.emit("Przygotowywanie raportu...")

        def work() -> CoverageReport:
            from finddocs.diagnostics.coverage_report import build_coverage_report

            return build_coverage_report(self.context.require_index())

        task = CallableTask(work, label="raport pokrycia")
        task.signals.finished.connect(self._on_report)
        task.signals.failed.connect(
            lambda code, message: show_error(self, f"{message}\n\nKod: {code}")
        )
        thread_pool().start(task)

    def _on_report(self, report: object) -> None:
        if not isinstance(report, CoverageReport):
            return
        self._report = report
        self._render_summary(report)
        self._render_table(report)
        self.status_message.emit("Raport pokrycia zaktualizowany.")

    def _render_summary(self, report: CoverageReport) -> None:
        while self.summary_grid.count():
            item = self.summary_grid.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()

        entries = [
            ("Wykryte pliki", report.discovered),
            ("Zaindeksowane", report.indexed),
            ("Zaindeksowane częściowo", report.partial),
            ("Wymagające OCR", report.requiring_ocr),
            ("OCR udany", report.ocr_succeeded),
            ("OCR nieudany", report.ocr_failed),
            ("Pominięte", report.skipped),
            ("Nieobsługiwane", report.unsupported),
            ("Uszkodzone", report.corrupted),
            ("Zabezpieczone hasłem", report.password_protected),
            ("Bez treści", report.empty),
            ("Błędy pobierania", report.download_errors),
            ("Inne błędy", report.other_errors),
            ("Fragmenty", report.total_chunks),
            ("Wektory", report.total_vectors),
            ("Rozmiar indeksu", i18n.format_bytes(report.index_size_bytes)),
            ("Wersja schematu", report.schema_version),
            ("Wersja aplikacji", report.app_version),
            ("Model embeddingów", report.model_key or "brak"),
            ("Wymiar wektora", report.model_dimension or "brak"),
            ("Ostatnie skanowanie", report.last_scan_at or "brak"),
            ("Ostatnie pełne indeksowanie", report.last_full_index_at or "brak"),
        ]
        for position, (label_text, value) in enumerate(entries):
            column = position % 3
            row = position // 3
            caption = QLabel(str(label_text))
            caption.setObjectName("Muted")
            display = QLabel(str(value))
            display.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.summary_grid.addWidget(caption, row * 2, column)
            self.summary_grid.addWidget(display, row * 2 + 1, column)

        if report.non_searchable:
            self.completeness.setText(
                i18n.REPORT_INCOMPLETE.format(count=len(report.non_searchable))
            )
        elif report.discovered:
            self.completeness.setText(i18n.REPORT_COMPLETE)
        else:
            self.completeness.setText("Indeks jest pusty.")

    def _render_table(self, report: CoverageReport) -> None:
        self.table.setRowCount(0)
        for document in report.non_searchable[:NON_SEARCHABLE_LIMIT]:
            position = self.table.rowCount()
            self.table.insertRow(position)
            values = [
                document.name,
                document.logical_path,
                i18n.STATUS_LABELS.get(document.status, document.status.value),
                document.error_code or "",
                document.error_message or "",
            ]
            for column, value in enumerate(values):
                self.table.setItem(position, column, QTableWidgetItem(value))

    # --- eksport ----------------------------------------------------------

    def export(self, fmt: str) -> None:
        if self._report is None:
            show_info(self, "Najpierw odśwież raport przyciskiem Odśwież.")
            return
        suffix = "json" if fmt == "json" else "csv"
        default = self.context.paths.reports_dir / f"raport-pokrycia.{suffix}"
        path, _ = QFileDialog.getSaveFileName(
            self,
            i18n.REPORT_EXPORT_JSON if fmt == "json" else i18n.REPORT_EXPORT_CSV,
            str(default),
            f"Plik {suffix.upper()} (*.{suffix})",
        )
        if not path:
            return
        report = self._report

        def work() -> str:
            from finddocs.diagnostics.export import export_coverage_csv, export_coverage_json

            if fmt == "json":
                return str(export_coverage_json(report, Path(path)))
            return str(export_coverage_csv(report, Path(path)))

        task = CallableTask(work, label="eksport raportu")
        task.signals.finished.connect(
            lambda result: self.status_message.emit(f"Zapisano raport: {result}")
        )
        task.signals.failed.connect(
            lambda code, message: show_error(self, f"{message}\n\nKod: {code}")
        )
        thread_pool().start(task)


__all__ = ["NON_SEARCHABLE_LIMIT", "ReportView"]

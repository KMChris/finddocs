"""Ekran raportu pokrycia.

Ekran odpowiada na jedno pytanie: czy da sie wyszukac wszystko, co zostalo
wykryte. Odpowiedz jest w banerze na gorze, kolorem: zielony gdy zbior jest
kompletny, pomaranczowy gdy nie. Liczby sa nizej, dla osoby, ktora chce
wiedziec dokladnie, czego brakuje.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
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
from finddocs.gui.tables import configure_columns, format_stamp
from finddocs.gui.theme import SPACE_SM, accent_icon, theme_icon
from finddocs.gui.widgets.page import Banner, PageHeader, page_layout
from finddocs.gui.widgets.stat_grid import StatGrid
from finddocs.gui.workers import CallableTask, thread_pool
from finddocs.logging_setup import get_logger
from finddocs.types import CoverageReport

log = get_logger(__name__)

NON_SEARCHABLE_LIMIT = 2000

#: Pary (klucz, podpis) siatki podsumowania. Struktura jest stala, wiec
#: odswiezenie raportu podmienia same wartosci.
SUMMARY_ENTRIES: tuple[tuple[str, str], ...] = (
    ("discovered", "Wykryte pliki"),
    ("indexed", "Zaindeksowane"),
    ("partial", "Zaindeksowane częściowo"),
    ("requiring_ocr", "Wymagające OCR"),
    ("ocr_succeeded", "OCR udany"),
    ("ocr_failed", "OCR nieudany"),
    ("skipped", "Pominięte"),
    ("unsupported", "Nieobsługiwane"),
    ("corrupted", "Uszkodzone"),
    ("password_protected", "Zabezpieczone hasłem"),
    ("empty", "Bez treści"),
    ("download_errors", "Błędy pobierania"),
    ("other_errors", "Inne błędy"),
    ("total_chunks", "Fragmenty"),
    ("total_vectors", "Wektory"),
    ("index_size", "Rozmiar indeksu"),
    ("schema_version", "Wersja schematu"),
    ("app_version", "Wersja aplikacji"),
    ("model_key", "Model embeddingów"),
    ("model_dimension", "Wymiar wektora"),
    ("last_scan", "Ostatnie skanowanie"),
    ("last_full_index", "Ostatnie pełne indeksowanie"),
)


def summary_values(report: CoverageReport) -> dict[str, str]:
    """Wartosci siatki podsumowania odczytane z raportu."""
    return {
        "discovered": str(report.discovered),
        "indexed": str(report.indexed),
        "partial": str(report.partial),
        "requiring_ocr": str(report.requiring_ocr),
        "ocr_succeeded": str(report.ocr_succeeded),
        "ocr_failed": str(report.ocr_failed),
        "skipped": str(report.skipped),
        "unsupported": str(report.unsupported),
        "corrupted": str(report.corrupted),
        "password_protected": str(report.password_protected),
        "empty": str(report.empty),
        "download_errors": str(report.download_errors),
        "other_errors": str(report.other_errors),
        "total_chunks": str(report.total_chunks),
        "total_vectors": str(report.total_vectors),
        "index_size": i18n.format_bytes(report.index_size_bytes),
        "schema_version": str(report.schema_version),
        "app_version": str(report.app_version),
        "model_key": report.model_key or i18n.STAT_NONE,
        "model_dimension": str(report.model_dimension or i18n.STAT_NONE),
        "last_scan": format_stamp(str(report.last_scan_at or "")) or i18n.STAT_NONE,
        "last_full_index": format_stamp(str(report.last_full_index_at or "")) or i18n.STAT_NONE,
    }


class ReportView(QWidget):
    """Podglad i eksport raportu pokrycia."""

    status_message = Signal(str)

    def __init__(self, context: AppContext) -> None:
        super().__init__()
        self.context = context
        self._report: CoverageReport | None = None

        root = page_layout(self)

        self.header = PageHeader(i18n.REPORT_TITLE)
        root.addWidget(self.header)

        buttons = QHBoxLayout()
        buttons.setSpacing(SPACE_SM)
        refresh = QPushButton(i18n.REPORT_REFRESH)
        refresh.setObjectName("Primary")
        refresh.setIcon(accent_icon("refresh"))
        refresh.clicked.connect(self.refresh)
        buttons.addWidget(refresh)

        self.export_json_button = QPushButton(i18n.REPORT_EXPORT_JSON)
        self.export_json_button.setIcon(theme_icon("export"))
        self.export_json_button.clicked.connect(lambda: self.export("json"))
        buttons.addWidget(self.export_json_button)

        self.export_csv_button = QPushButton(i18n.REPORT_EXPORT_CSV)
        self.export_csv_button.setIcon(theme_icon("export"))
        self.export_csv_button.clicked.connect(lambda: self.export("csv"))
        buttons.addWidget(self.export_csv_button)
        buttons.addStretch(1)
        root.addLayout(buttons)

        # Eksport bez policzonego raportu konczyl sie oknem z pouczeniem.
        # Wylaczony przycisk mowi to samo, zanim ktos go kliknie.
        self._set_export_enabled(False)

        self.completeness = Banner()
        self.completeness.show_message(i18n.REPORT_NEEDS_REFRESH, "info")
        root.addWidget(self.completeness)

        self.summary_box = QGroupBox(i18n.REPORT_SUMMARY)
        summary_layout = QVBoxLayout(self.summary_box)
        self.summary = StatGrid(SUMMARY_ENTRIES, columns=3)
        self.summary.set_values({key: i18n.STAT_NONE for key, _ in SUMMARY_ENTRIES})
        summary_layout.addWidget(self.summary)
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
        self._set_export_enabled(True)
        self.summary.set_values(summary_values(report))
        self._render_completeness(report)
        self._render_table(report)
        self.status_message.emit("Raport pokrycia zaktualizowany.")

    def _set_export_enabled(self, enabled: bool) -> None:
        self.export_json_button.setEnabled(enabled)
        self.export_csv_button.setEnabled(enabled)

    def _render_completeness(self, report: CoverageReport) -> None:
        """Odpowiedz na pytanie o kompletnosc, wyrazona kolorem banera."""
        if report.non_searchable:
            self.completeness.show_message(
                i18n.REPORT_INCOMPLETE.format(
                    count=i18n.documents_count(len(report.non_searchable))
                ),
                "warning",
            )
            self.header.set_meta(
                i18n.documents_count(len(report.non_searchable)) + " bez możliwości wyszukania"
            )
        elif report.discovered:
            self.completeness.show_message(i18n.REPORT_COMPLETE, "success")
            self.header.set_meta(i18n.documents_count(report.indexed))
        else:
            self.completeness.show_message(i18n.REPORT_EMPTY, "info")
            self.header.set_meta("")

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


__all__ = ["NON_SEARCHABLE_LIMIT", "SUMMARY_ENTRIES", "ReportView", "summary_values"]

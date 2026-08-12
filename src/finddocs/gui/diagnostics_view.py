"""Panel diagnostyki: srodowisko, komponenty, spojnosc indeksu, eksport pakietu.

Panel jest osadzany jako zakladka ekranu Ustawienia, wiec nie ma wlasnego
naglowka ani marginesow strony. Odswieza sie sam przy kazdym pokazaniu,
tak jak wczesniej przy wejsciu na osobny ekran nawigacji.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from finddocs.gui import i18n
from finddocs.gui.context import AppContext
from finddocs.gui.dialogs import show_error, show_warning
from finddocs.gui.tables import configure_columns, filter_table_rows, populate_rows, text_item
from finddocs.gui.theme import SPACE_MD, SPACE_SM, accent_icon, theme_icon
from finddocs.gui.widgets.page import Banner
from finddocs.gui.widgets.tabs import TabPanel
from finddocs.gui.workers import CallableTask, thread_pool
from finddocs.logging_setup import get_logger

log = get_logger(__name__)


def _display_key(key: str) -> str:
    """Klucz techniczny w postaci czytelnej: bez podkreslen, z separatorem galezi."""
    return key.replace("_", " ").replace(".", " / ")


def _display_value(key: str, value: Any) -> str:
    """Wartosc w postaci czytelnej: tak/nie, brak, bajty w jednostkach."""
    if isinstance(value, bool):
        return "tak" if value else "nie"
    if value is None:
        return i18n.STAT_NONE
    last = key.rsplit(".", 1)[-1]
    if isinstance(value, int) and (last.endswith("bajty") or last.endswith("bytes")):
        return i18n.format_bytes(value)
    return str(value)


def _flatten(data: dict[str, Any], prefix: str = "") -> list[tuple[str, str]]:
    """Zamienia zagniezdzony slownik na czytelne pary klucz/wartosc do tabeli.

    Surowe klucze z podkresleniami i angielskie ``True``/``False`` wygladaly
    jak zrzut z debuggera, a interfejs ma byc po polsku.
    """
    rows: list[tuple[str, str]] = []
    for key, value in data.items():
        label = f"{prefix}{key}"
        if isinstance(value, dict):
            rows.extend(_flatten(value, prefix=f"{label}."))
        elif isinstance(value, list):
            if value and isinstance(value[0], dict):
                for index, item in enumerate(value):
                    rows.extend(_flatten(item, prefix=f"{label}[{index}]."))
            else:
                rows.append(
                    (_display_key(label), ", ".join(str(v) for v in value) or i18n.STAT_NONE)
                )
        else:
            rows.append((_display_key(label), _display_value(label, value)))
    return rows


class DiagnosticsView(QWidget):
    """Informacje diagnostyczne i narzedzia konserwacyjne."""

    status_message = Signal(str)

    def __init__(self, context: AppContext) -> None:
        super().__init__()
        self.context = context

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(SPACE_MD)

        root.addLayout(self._build_buttons())

        # Wyniki konserwacji laduja w banerze, nie w oknie modalnym: sukces
        # to nie decyzja, wiec nie ma czego potwierdzac. Okna zostaja dla
        # bledow i pytan.
        self.banner = Banner()
        root.addWidget(self.banner)

        self.environment_table = self._make_table()
        self.components_table = self._make_table()
        self.index_table = self._make_table()
        self.consistency_table = self._make_table()
        # Filtr po prawej stronie paska zakladek zaweza wszystkie tabele.
        self.table_filter = QLineEdit()
        self.table_filter.setPlaceholderText(i18n.TABLE_FILTER_PLACEHOLDER)
        self.table_filter.setAccessibleName(i18n.TABLE_FILTER_PLACEHOLDER)
        self.table_filter.setClearButtonEnabled(True)
        self.table_filter.setFixedWidth(220)
        self.table_filter.textChanged.connect(lambda _text: self._apply_table_filter())
        self.tabs = TabPanel(side_widget=self.table_filter)
        self.tabs.addTab(self.environment_table, i18n.DIAG_ENVIRONMENT)
        self.tabs.addTab(self.components_table, i18n.DIAG_COMPONENTS)
        self.tabs.addTab(self.index_table, i18n.DIAG_INDEX)
        self.tabs.addTab(self.consistency_table, i18n.DIAG_CONSISTENCY)
        root.addWidget(self.tabs, stretch=1)

        self.log_queries = QCheckBox(i18n.DIAG_LOG_QUERIES)
        self.log_queries.setChecked(self.context.config.diagnostics.log_queries)
        self.log_queries.toggled.connect(self._toggle_log_queries)
        root.addWidget(self.log_queries)

        hint = QLabel(i18n.DIAG_LOG_QUERIES_HINT)
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        root.addWidget(hint)

    def _build_buttons(self) -> QHBoxLayout:
        """Wiersz akcji: odswiezenie, konserwacja, eksport.

        Napisy sa krotkie, a pelne zdanie jest w podpowiedzi. Szesc przyciskow
        z peryfrazami nie zmiescilo sie w oknie o najmniejszym dozwolonym
        rozmiarze i Qt przycinalo im tekst.
        """
        row = QHBoxLayout()
        row.setSpacing(SPACE_SM)

        refresh = QPushButton(i18n.DIAG_REFRESH)
        refresh.setObjectName("Primary")
        refresh.setIcon(accent_icon("refresh"))
        refresh.clicked.connect(self.refresh)
        row.addWidget(refresh)

        check = QPushButton(i18n.DIAG_CHECK)
        check.setToolTip(i18n.DIAG_CHECK_HINT)
        check.clicked.connect(self.check_consistency)
        row.addWidget(check)

        compact = QPushButton(i18n.DIAG_COMPACT)
        compact.setToolTip(i18n.DIAG_COMPACT_HINT)
        compact.clicked.connect(self.compact_vectors)
        row.addWidget(compact)

        backup = QPushButton(i18n.DIAG_BACKUP)
        backup.setIcon(theme_icon("copy"))
        backup.setToolTip(i18n.DIAG_BACKUP_HINT)
        backup.clicked.connect(self.backup_index)
        row.addWidget(backup)

        clear_ocr = QPushButton(i18n.DIAG_CLEAR_OCR_CACHE)
        clear_ocr.setIcon(theme_icon("trash"))
        clear_ocr.setToolTip(i18n.DIAG_CLEAR_OCR_CACHE_HINT)
        clear_ocr.clicked.connect(self.clear_ocr_cache)
        row.addWidget(clear_ocr)

        bundle = QPushButton(i18n.DIAG_EXPORT_BUNDLE)
        bundle.setIcon(theme_icon("export"))
        bundle.setToolTip(i18n.DIAG_EXPORT_BUNDLE_HINT)
        bundle.clicked.connect(self.export_bundle)
        row.addWidget(bundle)

        logs = QPushButton(i18n.DIAG_OPEN_LOGS)
        logs.setIcon(theme_icon("folder"))
        logs.setToolTip(i18n.DIAG_OPEN_LOGS_HINT)
        logs.clicked.connect(lambda: self.context.open_path(self.context.paths.logs_dir))
        row.addWidget(logs)

        row.addStretch(1)
        return row

    def _make_table(self) -> QTableWidget:
        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(["Parametr", "Wartość"])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        configure_columns(table, (1,))
        return table

    def _fill(self, table: QTableWidget, data: dict[str, Any]) -> None:
        rows = _flatten(data)
        with populate_rows(table):
            table.setRowCount(0)
            for key, value in rows:
                position = table.rowCount()
                table.insertRow(position)
                table.setItem(position, 0, text_item(key))
                table.setItem(position, 1, text_item(value))
        filter_table_rows(table, self.table_filter.text())

    def _apply_table_filter(self) -> None:
        for table in (
            self.environment_table,
            self.components_table,
            self.index_table,
            self.consistency_table,
        ):
            filter_table_rows(table, self.table_filter.text())

    # --- akcje ------------------------------------------------------------

    def showEvent(self, event: QShowEvent) -> None:
        """Odswieza dane przy kazdym pokazaniu panelu.

        Wczesniej robilo to okno glowne przy wejsciu na osobny ekran
        diagnostyki. Po osadzeniu w Ustawieniach panel pilnuje tego sam.
        """
        super().showEvent(event)
        self.refresh()

    def refresh(self) -> None:
        def work() -> dict[str, Any]:
            from finddocs.diagnostics.stats import (
                collect_component_info,
                collect_environment_info,
                collect_index_stats,
            )

            return {
                "environment": collect_environment_info(),
                "components": collect_component_info(self.context.config),
                "index": collect_index_stats(self.context.require_index()),
            }

        task = CallableTask(work, label="diagnostyka")

        def done(result: object) -> None:
            if not isinstance(result, dict):
                return
            self._fill(self.environment_table, result.get("environment", {}))
            self._fill(self.components_table, result.get("components", {}))
            self._fill(self.index_table, result.get("index", {}))
            self.status_message.emit("Diagnostyka zaktualizowana.")

        task.signals.finished.connect(done)
        task.signals.failed.connect(self._show_error)
        thread_pool().start(task)

    def check_consistency(self) -> None:
        def work() -> dict[str, Any]:
            return self.context.require_index().consistency().to_dict()

        task = CallableTask(work, label="spójność indeksu")

        def done(result: object) -> None:
            if not isinstance(result, dict):
                return
            self._fill(self.consistency_table, result)
            self.tabs.setCurrentWidget(self.consistency_table)
            problems = result.get("problemy") or []
            if problems:
                show_warning(
                    self,
                    "Wykryto problemy ze spójnością indeksu:\n" + "\n".join(map(str, problems)),
                )
            else:
                self.banner.show_message("Indeks jest spójny.", "success")
                self.status_message.emit("Indeks jest spójny.")

        task.signals.finished.connect(done)
        task.signals.failed.connect(self._show_error)
        thread_pool().start(task)

    def compact_vectors(self) -> None:
        index = self.context.index
        if index is None or index.vector_store is None:
            self.banner.show_message("Indeks wektorowy nie jest dostępny.", "info")
            return

        def work() -> str:
            from finddocs.indexing.maintenance import compact_vectors as compact

            store = self.context.require_index().vector_store
            if store is None:
                return "Indeks wektorowy nie jest dostępny."
            count = compact(self.context.require_index().repository, store)
            self.context.require_index().db.optimize()
            return f"Skompaktowano indeks wektorowy. Aktywnych wektorów: {count}."

        self.status_message.emit("Kompaktowanie indeksu wektorowego...")
        task = CallableTask(work, label="kompaktacja")
        task.signals.finished.connect(
            lambda message: self.banner.show_message(str(message), "success")
        )
        task.signals.failed.connect(self._show_error)
        thread_pool().start(task)

    def clear_ocr_cache(self) -> None:
        """Usuwa zapamietane wyniki OCR, np. obciete starym limitem stron."""

        def work() -> str:
            count = self.context.require_index().repository.clear_ocr_cache()
            return (
                f"Usunięto {count} wpisów pamięci podręcznej OCR. "
                "Pełne indeksowanie rozpozna skany od nowa."
            )

        self.status_message.emit("Czyszczenie pamięci podręcznej OCR...")
        task = CallableTask(work, label="czyszczenie pamięci OCR")
        task.signals.finished.connect(
            lambda message: self.banner.show_message(str(message), "success")
        )
        task.signals.failed.connect(self._show_error)
        thread_pool().start(task)

    def backup_index(self) -> None:
        def work() -> str:
            from finddocs.indexing.maintenance import backup_index as backup

            self.context.require_index().flush()
            target = backup(self.context.paths)
            return f"Kopia indeksu zapisana w: {target}"

        self.status_message.emit("Tworzenie kopii indeksu...")
        task = CallableTask(work, label="kopia indeksu")
        task.signals.finished.connect(
            lambda message: self.banner.show_message(str(message), "success")
        )
        task.signals.failed.connect(self._show_error)
        thread_pool().start(task)

    def export_bundle(self) -> None:
        def work() -> str:
            from finddocs.diagnostics.export import export_diagnostics_bundle

            target = export_diagnostics_bundle(self.context.require_index(), self.context.paths)
            return str(target)

        self.status_message.emit("Przygotowywanie pakietu diagnostycznego...")
        task = CallableTask(work, label="pakiet diagnostyczny")
        task.signals.finished.connect(
            lambda result: self.banner.show_message(
                f"Pakiet diagnostyczny zapisano w: {result}. Pakiet nie zawiera treści dokumentów.",
                "success",
            )
        )
        task.signals.failed.connect(self._show_error)
        thread_pool().start(task)

    def _toggle_log_queries(self, enabled: bool) -> None:
        self.context.config.diagnostics.log_queries = enabled
        self.context.save()
        self.status_message.emit(
            "Zapisywanie zapytań w logu włączone."
            if enabled
            else "Zapisywanie zapytań w logu wyłączone."
        )

    def _show_error(self, code: str, message: str) -> None:
        show_error(self, f"{message}\n\nKod: {code}")


__all__ = ["DiagnosticsView"]

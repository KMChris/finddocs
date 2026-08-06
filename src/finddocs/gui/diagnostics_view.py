"""Ekran diagnostyki: srodowisko, komponenty, spojnosc indeksu, eksport pakietu."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from finddocs.gui import i18n
from finddocs.gui.context import AppContext
from finddocs.gui.dialogs import show_error, show_info, show_warning
from finddocs.gui.tables import configure_columns
from finddocs.gui.theme import accent_icon, theme_icon
from finddocs.gui.workers import CallableTask, thread_pool
from finddocs.logging_setup import get_logger

log = get_logger(__name__)


def _flatten(data: dict[str, Any], prefix: str = "") -> list[tuple[str, str]]:
    """Zamienia zagniezdzony slownik na pary klucz/wartosc do tabeli."""
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
                rows.append((label, ", ".join(str(v) for v in value) or "brak"))
        else:
            rows.append((label, str(value)))
    return rows


class DiagnosticsView(QWidget):
    """Informacje diagnostyczne i narzedzia konserwacyjne."""

    status_message = Signal(str)

    def __init__(self, context: AppContext) -> None:
        super().__init__()
        self.context = context

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(12)

        title = QLabel(i18n.DIAG_TITLE)
        title.setObjectName("PageTitle")
        root.addWidget(title)

        root.addLayout(self._build_buttons())

        self.tabs = QTabWidget()
        self.environment_table = self._make_table()
        self.components_table = self._make_table()
        self.index_table = self._make_table()
        self.consistency_table = self._make_table()
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
        row = QHBoxLayout()
        row.setSpacing(8)

        refresh = QPushButton("Odśwież")
        refresh.setObjectName("Primary")
        refresh.setIcon(accent_icon("refresh"))
        refresh.clicked.connect(self.refresh)
        row.addWidget(refresh)

        check = QPushButton(i18n.DIAG_CHECK)
        check.clicked.connect(self.check_consistency)
        row.addWidget(check)

        compact = QPushButton(i18n.DIAG_COMPACT)
        compact.clicked.connect(self.compact_vectors)
        row.addWidget(compact)

        backup = QPushButton(i18n.DIAG_BACKUP)
        backup.setIcon(theme_icon("copy"))
        backup.clicked.connect(self.backup_index)
        row.addWidget(backup)

        bundle = QPushButton(i18n.DIAG_EXPORT_BUNDLE)
        bundle.setIcon(theme_icon("export"))
        bundle.clicked.connect(self.export_bundle)
        row.addWidget(bundle)

        logs = QPushButton(i18n.DIAG_OPEN_LOGS)
        logs.setIcon(theme_icon("folder"))
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
        table.setRowCount(0)
        for key, value in rows:
            position = table.rowCount()
            table.insertRow(position)
            table.setItem(position, 0, QTableWidgetItem(key))
            table.setItem(position, 1, QTableWidgetItem(value))

    # --- akcje ------------------------------------------------------------

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
                self.status_message.emit("Indeks jest spójny.")

        task.signals.finished.connect(done)
        task.signals.failed.connect(self._show_error)
        thread_pool().start(task)

    def compact_vectors(self) -> None:
        index = self.context.index
        if index is None or index.vector_store is None:
            show_info(self, "Indeks wektorowy nie jest dostępny.")
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
        task.signals.finished.connect(lambda message: show_info(self, str(message)))
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
        task.signals.finished.connect(lambda message: show_info(self, str(message)))
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
            lambda result: show_info(
                self,
                f"Pakiet diagnostyczny zapisano w:\n{result}\n\n"
                "Pakiet nie zawiera treści dokumentów.",
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

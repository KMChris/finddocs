"""Ekran zrodel i konfiguracji: SharePoint, katalogi lokalne, model, przechowywanie."""

from __future__ import annotations

import uuid
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from finddocs.config import (
    LocalDirSourceSettings,
    SharePointSourceSettings,
    SourceConfig,
)
from finddocs.connectors.base import SourceConnector
from finddocs.gui import i18n
from finddocs.gui.context import AppContext
from finddocs.gui.dialogs import ask_yes_no, show_error, show_info, show_warning
from finddocs.gui.workers import CallableTask, thread_pool
from finddocs.logging_setup import get_logger
from finddocs.providers.model_manifest import describe_models
from finddocs.types import SourceKind

log = get_logger(__name__)


class SharePointDialog(QDialog):
    """Formularz dodania zrodla SharePoint."""

    def __init__(self, parent: QWidget | None = None, existing: SourceConfig | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(i18n.SOURCES_ADD_SHAREPOINT)
        self.setMinimumWidth(560)
        settings = existing.sharepoint if existing else SharePointSourceSettings()

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(8)

        self.label_edit = QLineEdit(existing.label if existing else "SharePoint")
        self.site_edit = QLineEdit(settings.site_url)
        self.site_edit.setPlaceholderText("https://firma.sharepoint.com/sites/Finanse")
        self.library_edit = QLineEdit(settings.drive_name)
        self.library_edit.setPlaceholderText("Dokumenty")
        self.folder_edit = QLineEdit(settings.folder_path)
        self.folder_edit.setPlaceholderText("opcjonalnie, np. Procedury/2024")
        self.tenant_edit = QLineEdit(settings.tenant_id)
        self.tenant_edit.setPlaceholderText("identyfikator dzierzawy Entra ID")
        self.client_edit = QLineEdit(settings.client_id)
        self.client_edit.setPlaceholderText("identyfikator aplikacji zarejestrowanej w Entra ID")
        self.flow_combo = QComboBox()
        self.flow_combo.addItem("Logowanie w oknie przegladarki", "interactive")
        self.flow_combo.addItem("Kod urzadzenia", "device_code")
        position = self.flow_combo.findData(settings.auth_flow)
        self.flow_combo.setCurrentIndex(max(0, position))
        self.recursive_check = QCheckBox("Przeszukuj podkatalogi")
        self.recursive_check.setChecked(settings.recursive)

        form.addRow("Nazwa zrodla", self.label_edit)
        form.addRow("Adres witryny", self.site_edit)
        form.addRow("Biblioteka dokumentow", self.library_edit)
        form.addRow("Katalog startowy", self.folder_edit)
        form.addRow("Dzierzawa (tenant)", self.tenant_edit)
        form.addRow("Aplikacja (client id)", self.client_edit)
        form.addRow("Sposob logowania", self.flow_combo)
        form.addRow("", self.recursive_check)
        layout.addLayout(form)

        hint = QLabel(
            "Aplikacja laczy sie z SharePoint przez Microsoft Graph. Administrator musi "
            "zarejestrowac aplikacje w Entra ID i nadac uprawnienia delegowane "
            "Files.Read.All oraz Sites.Read.All. Tokeny sa przechowywane w Menedzerze "
            "poswiadczen Windows i nie trafiaja do plikow konfiguracyjnych."
        )
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(i18n.BUTTON_SAVE)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(i18n.BUTTON_CANCEL)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._existing = existing

    def _validate_and_accept(self) -> None:
        missing = []
        if not self.site_edit.text().strip():
            missing.append("adres witryny")
        if not self.library_edit.text().strip():
            missing.append("nazwa biblioteki")
        if not self.tenant_edit.text().strip():
            missing.append("identyfikator dzierzawy")
        if not self.client_edit.text().strip():
            missing.append("identyfikator aplikacji")
        if missing:
            show_warning(
                self,
                "Uzupelnij pola: " + ", ".join(missing) + ".",
            )
            return
        self.accept()

    def to_source(self) -> SourceConfig:
        source_id = self._existing.source_id if self._existing else f"sp-{uuid.uuid4().hex[:8]}"
        return SourceConfig(
            source_id=source_id,
            kind=SourceKind.SHAREPOINT,
            label=self.label_edit.text().strip() or "SharePoint",
            sharepoint=SharePointSourceSettings(
                tenant_id=self.tenant_edit.text().strip(),
                client_id=self.client_edit.text().strip(),
                site_url=self.site_edit.text().strip(),
                drive_name=self.library_edit.text().strip(),
                folder_path=self.folder_edit.text().strip(),
                auth_flow=str(self.flow_combo.currentData()),
                recursive=self.recursive_check.isChecked(),
            ),
        )


class SourcesView(QWidget):
    """Lista zrodel, ustawienia modelu i przechowywania."""

    status_message = Signal(str)
    sources_changed = Signal()

    def __init__(self, context: AppContext) -> None:
        super().__init__()
        self.context = context

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(12)

        title = QLabel(i18n.NAV_SOURCES)
        title.setObjectName("PageTitle")
        root.addWidget(title)

        root.addWidget(self._build_sources_box(), stretch=1)
        row = QHBoxLayout()
        row.addWidget(self._build_storage_box(), stretch=1)
        row.addWidget(self._build_model_box(), stretch=1)
        root.addLayout(row)

        self.refresh()

    # --- budowa -----------------------------------------------------------

    def _build_sources_box(self) -> QWidget:
        box = QGroupBox(i18n.SOURCES_TITLE)
        layout = QVBoxLayout(box)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Nazwa", "Rodzaj", "Lokalizacja", "Aktywne", "Identyfikator"]
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        buttons = QHBoxLayout()
        add_local = QPushButton(i18n.SOURCES_ADD_LOCAL)
        add_local.clicked.connect(self.add_local_source)
        buttons.addWidget(add_local)

        add_sp = QPushButton(i18n.SOURCES_ADD_SHAREPOINT)
        add_sp.clicked.connect(self.add_sharepoint_source)
        buttons.addWidget(add_sp)

        demo = QPushButton(i18n.SOURCES_DEMO)
        demo.clicked.connect(self.generate_demo)
        buttons.addWidget(demo)

        buttons.addStretch(1)

        test = QPushButton(i18n.SOURCES_TEST)
        test.clicked.connect(self.test_selected)
        buttons.addWidget(test)

        toggle = QPushButton(i18n.SOURCES_TOGGLE)
        toggle.clicked.connect(self.toggle_selected)
        buttons.addWidget(toggle)

        remove = QPushButton(i18n.SOURCES_REMOVE)
        remove.setObjectName("Danger")
        remove.clicked.connect(self.remove_selected)
        buttons.addWidget(remove)
        layout.addLayout(buttons)
        return box

    def _build_storage_box(self) -> QWidget:
        box = QGroupBox(i18n.STORAGE_TITLE)
        layout = QVBoxLayout(box)

        self.path_label = QLabel("")
        self.path_label.setWordWrap(True)
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.path_label)

        self.free_label = QLabel("")
        self.free_label.setObjectName("Muted")
        layout.addWidget(self.free_label)

        self.size_label = QLabel("")
        self.size_label.setObjectName("Muted")
        layout.addWidget(self.size_label)

        row = QHBoxLayout()
        change = QPushButton(i18n.STORAGE_CHANGE)
        change.clicked.connect(self.change_storage)
        row.addWidget(change)
        open_button = QPushButton("Otworz katalog")
        open_button.clicked.connect(lambda: self.context.open_path(self.context.paths.root))
        row.addWidget(open_button)
        row.addStretch(1)
        layout.addLayout(row)
        return box

    def _build_model_box(self) -> QWidget:
        box = QGroupBox(i18n.MODEL_TITLE)
        layout = QVBoxLayout(box)

        self.model_combo = QComboBox()
        layout.addWidget(self.model_combo)

        self.model_info = QLabel("")
        self.model_info.setObjectName("Muted")
        self.model_info.setWordWrap(True)
        layout.addWidget(self.model_info)

        self.quantized_check = QCheckBox("Uzyj wersji skwantyzowanej (szybsza, mniejszy plik)")
        self.quantized_check.setChecked(self.context.config.embedding.quantized)
        layout.addWidget(self.quantized_check)

        apply_button = QPushButton("Zastosuj ustawienia modelu")
        apply_button.clicked.connect(self.apply_model)
        layout.addWidget(apply_button)
        layout.addStretch(1)
        return box

    # --- odswiezanie ------------------------------------------------------

    def refresh(self) -> None:
        self.table.setRowCount(0)
        for source in self.context.config.sources:
            position = self.table.rowCount()
            self.table.insertRow(position)
            values = [
                source.label,
                "katalog lokalny" if source.kind is SourceKind.LOCAL_DIR else "SharePoint",
                source.describe_location(),
                "tak" if source.enabled else "nie",
                source.source_id,
            ]
            for column, value in enumerate(values):
                self.table.setItem(position, column, QTableWidgetItem(value))

        paths = self.context.paths
        self.path_label.setText(f"{i18n.STORAGE_PATH}: {paths.root}")
        self.free_label.setText(
            i18n.STORAGE_FREE.format(value=i18n.format_bytes(paths.free_space_bytes()))
        )
        self.size_label.setText(
            i18n.STORAGE_INDEX_SIZE.format(value=i18n.format_bytes(paths.index_size_bytes()))
        )

        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        installed_any = False
        for model in describe_models():
            suffix = " (zainstalowany)" if model["zainstalowany"] else " (brak plikow)"
            installed_any = installed_any or bool(model["zainstalowany"])
            self.model_combo.addItem(str(model["nazwa"]) + suffix, model["klucz"])
        position = self.model_combo.findData(self.context.config.embedding.model_key)
        self.model_combo.setCurrentIndex(max(0, position))
        self.model_combo.blockSignals(False)

        index = self.context.index
        if index is not None and index.provider is not None:
            info = index.provider.info
            self.model_info.setText(
                f"{i18n.MODEL_CURRENT.format(value=info.model_key)}\n"
                f"{i18n.MODEL_DIMENSION.format(value=info.dimension)}\n"
                f"Licencja: {info.license_name}, srodowisko: {info.runtime}"
            )
        else:
            self.model_info.setText(i18n.MODEL_MISSING)

    # --- akcje ------------------------------------------------------------

    def _selected_source(self) -> SourceConfig | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 4)
        if item is None:
            return None
        try:
            return self.context.config.source(item.text())
        except Exception:
            return None

    def add_local_source(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, i18n.SOURCES_ADD_LOCAL)
        if not directory:
            return
        root = Path(directory)
        source = SourceConfig(
            source_id=f"local-{uuid.uuid4().hex[:8]}",
            kind=SourceKind.LOCAL_DIR,
            label=root.name or str(root),
            local=LocalDirSourceSettings(root_path=str(root)),
        )
        self.context.config = self.context.config.with_source(source)
        self.context.save()
        self.refresh()
        self.sources_changed.emit()
        self.status_message.emit(f"Dodano zrodlo: {source.label}")

    def add_sharepoint_source(self) -> None:
        dialog = SharePointDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        source = dialog.to_source()
        self.context.config = self.context.config.with_source(source)
        self.context.save()
        self.refresh()
        self.sources_changed.emit()
        self.status_message.emit(
            "Dodano zrodlo SharePoint. Uzyj przycisku Testuj polaczenie, zeby sie zalogowac."
        )

    def test_selected(self) -> None:
        source = self._selected_source()
        if source is None:
            show_info(self, "Wybierz zrodlo z listy.")
            return

        def work() -> str:
            if source.kind is SourceKind.LOCAL_DIR:
                from finddocs.connectors.local_dir import LocalDirectoryConnector

                connector: SourceConnector = LocalDirectoryConnector.from_config(source)
            else:
                from finddocs.connectors.sharepoint import build_sharepoint_connector

                connector = build_sharepoint_connector(source, self.context.paths)
            try:
                status = connector.test_connection()
            finally:
                connector.close()
            prefix = "Polaczenie dziala. " if status.ok else "Polaczenie nie dziala. "
            return prefix + status.message

        self.status_message.emit("Sprawdzanie polaczenia...")
        task = CallableTask(work, label="test polaczenia")
        task.signals.finished.connect(lambda message: show_info(self, str(message)))
        task.signals.failed.connect(
            lambda code, message: show_error(self, f"{message}\n\nKod: {code}")
        )
        thread_pool().start(task)

    def toggle_selected(self) -> None:
        source = self._selected_source()
        if source is None:
            return
        source.enabled = not source.enabled
        self.context.config = self.context.config.with_source(source)
        self.context.save()
        self.refresh()
        self.sources_changed.emit()

    def remove_selected(self) -> None:
        source = self._selected_source()
        if source is None:
            return
        if not ask_yes_no(
            self, i18n.CONFIRM_REMOVE_SOURCE.format(label=source.label), i18n.CONFIRM_TITLE
        ):
            return
        index = self.context.require_index()
        with index.db.transaction():
            index.repository.delete_source(source.source_id)
        self.context.config.sources = [
            s for s in self.context.config.sources if s.source_id != source.source_id
        ]
        self.context.save()
        self.refresh()
        self.sources_changed.emit()
        self.status_message.emit(f"Usunieto zrodlo {source.label}.")

    def generate_demo(self) -> None:
        def work() -> str:
            from finddocs.demo import ensure_demo_corpus

            info = ensure_demo_corpus(self.context.paths.root, force=False)
            source = SourceConfig(
                source_id="demo",
                kind=SourceKind.LOCAL_DIR,
                label="Zbior demonstracyjny",
                local=LocalDirSourceSettings(root_path=str(info.root)),
                exclude_globs=["manifest.json"],
            )
            self.context.config = self.context.config.with_source(source)
            self.context.save()
            return f"Utworzono zbior demonstracyjny: {info.files} plikow w {info.root}"

        self.status_message.emit("Generowanie zbioru demonstracyjnego...")
        task = CallableTask(work, label="zbior demonstracyjny")

        def done(message: object) -> None:
            self.refresh()
            self.sources_changed.emit()
            show_info(self, str(message))

        task.signals.finished.connect(done)
        task.signals.failed.connect(
            lambda code, message: show_error(self, f"{message}\n\nKod: {code}")
        )
        thread_pool().start(task)

    def change_storage(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, i18n.STORAGE_CHANGE)
        if not directory:
            return
        show_info(
            self,
            "Katalog danych zostanie zmieniony po ponownym uruchomieniu aplikacji.\n"
            f"Nowy katalog: {directory}",
        )
        self.context.config.data_root = directory
        self.context.save()
        self.refresh()

    def apply_model(self) -> None:
        key = str(self.model_combo.currentData())
        quantized = self.quantized_check.isChecked()
        changed = (
            key != self.context.config.embedding.model_key
            or quantized != self.context.config.embedding.quantized
        )
        self.context.config.embedding.model_key = key
        self.context.config.embedding.quantized = quantized
        self.context.save()
        if changed:
            show_info(
                self,
                "Zmiana modelu wymaga przebudowy czesci semantycznej indeksu.\n"
                "Uruchom pelne przeindeksowanie na ekranie Indeksowanie.\n"
                "Do tego czasu wyszukiwanie dokladne dziala bez zmian.",
            )
        self.refresh()


__all__ = ["SharePointDialog", "SourcesView"]

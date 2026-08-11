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
from finddocs.gui.model_dialog import ModelSettingsDialog
from finddocs.gui.tables import configure_columns, text_item
from finddocs.gui.theme import SPACE_LG, SPACE_SM, accent_icon, theme_icon
from finddocs.gui.widgets.page import Banner, PageHeader, page_layout, repolish
from finddocs.gui.workers import CallableTask, thread_pool
from finddocs.logging_setup import get_logger
from finddocs.providers.model_manifest import describe_models, sync_embedding_settings
from finddocs.types import SourceKind

log = get_logger(__name__)

#: Rola danych wiersza, w ktorej trzymamy identyfikator zrodla.
SOURCE_ID_ROLE = Qt.ItemDataRole.UserRole

#: Widoczna wysokosc listy zrodel: od dwoch do szesciu wierszy. Ponizej tego
#: zakresu tabela wyglada na uszkodzona, powyzej jest pustym prostokatem.
TABLE_MIN_HEIGHT = 120
TABLE_MAX_HEIGHT = 260


class SharePointDialog(QDialog):
    """Formularz dodania zrodla SharePoint."""

    def __init__(self, parent: QWidget | None = None, existing: SourceConfig | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(i18n.SOURCES_ADD_SHAREPOINT)
        self.setMinimumWidth(560)
        settings = existing.sharepoint if existing else SharePointSourceSettings()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)
        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)

        self.label_edit = QLineEdit(existing.label if existing else "SharePoint")
        self.site_edit = QLineEdit(settings.site_url)
        self.site_edit.setPlaceholderText("https://firma.sharepoint.com/sites/Finanse")
        self.library_edit = QLineEdit(settings.drive_name)
        self.library_edit.setPlaceholderText("Dokumenty")
        self.folder_edit = QLineEdit(settings.folder_path)
        self.folder_edit.setPlaceholderText("opcjonalnie, np. Procedury/2024")
        self.tenant_edit = QLineEdit(settings.tenant_id)
        self.tenant_edit.setPlaceholderText("identyfikator dzierżawy Entra ID")
        self.client_edit = QLineEdit(settings.client_id)
        self.client_edit.setPlaceholderText("identyfikator aplikacji zarejestrowanej w Entra ID")
        self.flow_combo = QComboBox()
        self.flow_combo.addItem("Logowanie w oknie przeglądarki", "interactive")
        self.flow_combo.addItem("Kod urządzenia", "device_code")
        position = self.flow_combo.findData(settings.auth_flow)
        self.flow_combo.setCurrentIndex(max(0, position))
        self.recursive_check = QCheckBox("Przeszukuj podkatalogi")
        self.recursive_check.setChecked(settings.recursive)

        form.addRow("Nazwa źródła", self.label_edit)
        form.addRow("Adres witryny", self.site_edit)
        form.addRow("Biblioteka dokumentów", self.library_edit)
        form.addRow("Katalog startowy", self.folder_edit)
        form.addRow("Dzierżawa (tenant)", self.tenant_edit)
        form.addRow("Aplikacja (client id)", self.client_edit)
        form.addRow("Sposób logowania", self.flow_combo)
        form.addRow("", self.recursive_check)
        layout.addLayout(form)

        # Brakujace pola sa oznaczane na miejscu, bez osobnego okna z pouczeniem.
        self.error_label = QLabel("")
        self.error_label.setObjectName("FormError")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        self._required_fields: tuple[tuple[QLineEdit, str], ...] = (
            (self.site_edit, "adres witryny"),
            (self.library_edit, "nazwa biblioteki"),
            (self.tenant_edit, "identyfikator dzierżawy"),
            (self.client_edit, "identyfikator aplikacji"),
        )
        for edit, _name in self._required_fields:
            edit.textChanged.connect(lambda _text, field=edit: self._mark_invalid(field, False))

        hint = QLabel(
            "Aplikacja łączy się z SharePoint przez Microsoft Graph. Administrator musi "
            "zarejestrować aplikację w Entra ID i nadać uprawnienia delegowane "
            "Files.Read.All oraz Sites.Read.All. Tokeny są przechowywane w Menedżerze "
            "poświadczeń Windows i nie trafiają do plików konfiguracyjnych."
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

    def _mark_invalid(self, edit: QLineEdit, invalid: bool) -> None:
        """Oznacza pole jako brakujace. Edycja pola zdejmuje oznaczenie."""
        edit.setProperty("fieldInvalid", "true" if invalid else "")
        repolish(edit)

    def _validate_and_accept(self) -> None:
        missing: list[str] = []
        for edit, name in self._required_fields:
            empty = not edit.text().strip()
            self._mark_invalid(edit, empty)
            if empty:
                missing.append(name)
        if missing:
            self.error_label.setText("Uzupełnij pola: " + ", ".join(missing) + ".")
            self.error_label.setVisible(True)
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

        root = page_layout(self)

        self.header = PageHeader(i18n.NAV_SOURCES)
        root.addWidget(self.header)

        # Ekran ustawien czyta sie od gory. Rozciagniecie listy zrodel na cala
        # wysokosc dawalo pusta tabele na kilkaset pikseli, wiec karty maja
        # wysokosc wynikajaca z tresci, a wolne miejsce zostaje na dole.
        root.addWidget(self._build_sources_box())
        row = QHBoxLayout()
        row.setSpacing(SPACE_LG)
        row.addWidget(self._build_storage_box(), stretch=1)
        row.addWidget(self._build_model_box(), stretch=1)
        root.addLayout(row)
        root.addStretch(1)

        self.refresh()

    # --- budowa -----------------------------------------------------------

    def _build_sources_box(self) -> QWidget:
        box = QGroupBox(i18n.SOURCES_TITLE)
        layout = QVBoxLayout(box)
        layout.setSpacing(SPACE_SM + 2)

        self.empty_banner = Banner()
        layout.addWidget(self.empty_banner)

        # Identyfikator zrodla jest wartoscia techniczna. Trzymamy go w danych
        # wiersza, a nie w osobnej kolumnie, ktora nic nie mowi uzytkownikowi.
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Nazwa", "Rodzaj", "Lokalizacja", "Aktywne"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._refresh_buttons)
        # Wlaczenie zrodla to stan wiersza, wiec przelacza je pole wyboru
        # w kolumnie Aktywne. Osobny przycisk wymagal zaznaczenia wiersza
        # i drugiego klikniecia w innym miejscu ekranu.
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.setMinimumHeight(TABLE_MIN_HEIGHT)
        self.table.setMaximumHeight(TABLE_MAX_HEIGHT)
        configure_columns(self.table, (2,))
        layout.addWidget(self.table)

        buttons = QHBoxLayout()
        buttons.setSpacing(SPACE_SM)
        add_local = QPushButton(i18n.SOURCES_ADD_LOCAL)
        add_local.setObjectName("Primary")
        # Przycisk akcentowy potrzebuje glifu w kolorze tekstu na akcencie.
        # Glif w kolorze tekstu zwyklego przycisku jest w trybie ciemnym jasny,
        # a napis obok niego ciemny.
        add_local.setIcon(accent_icon("plus"))
        add_local.setToolTip(i18n.SOURCES_ADD_LOCAL_HINT)
        add_local.clicked.connect(self.add_local_source)
        buttons.addWidget(add_local)

        add_sp = QPushButton(i18n.SOURCES_ADD_SHAREPOINT)
        add_sp.setIcon(theme_icon("plus"))
        add_sp.setToolTip(i18n.SOURCES_ADD_SHAREPOINT_HINT)
        add_sp.clicked.connect(self.add_sharepoint_source)
        buttons.addWidget(add_sp)

        demo = QPushButton(i18n.SOURCES_DEMO)
        demo.setToolTip(i18n.SOURCES_DEMO_HINT)
        demo.clicked.connect(self.generate_demo)
        buttons.addWidget(demo)

        buttons.addStretch(1)

        # Akcje ponizej dzialaja na zaznaczonym wierszu, wiec bez zaznaczenia
        # sa wylaczone. Wczesniej klikniecie konczylo sie oknem z pouczeniem.
        self.test_button = QPushButton(i18n.SOURCES_TEST)
        self.test_button.setToolTip(i18n.SOURCES_TEST_HINT)
        self.test_button.clicked.connect(self.test_selected)
        buttons.addWidget(self.test_button)

        self.remove_button = QPushButton(i18n.SOURCES_REMOVE)
        self.remove_button.setObjectName("Danger")
        self.remove_button.setIcon(theme_icon("trash"))
        self.remove_button.setToolTip(i18n.SOURCES_REMOVE_HINT)
        self.remove_button.clicked.connect(self.remove_selected)
        buttons.addWidget(self.remove_button)
        layout.addLayout(buttons)
        return box

    def _refresh_buttons(self) -> None:
        """Akcje wymagajace zaznaczenia sa dostepne tylko wtedy, gdy jest wybor."""
        selected = self._selected_source() is not None
        for button in (self.test_button, self.remove_button):
            button.setEnabled(selected)

    def _build_storage_box(self) -> QWidget:
        box = QGroupBox(i18n.STORAGE_TITLE)
        layout = QVBoxLayout(box)
        layout.setSpacing(SPACE_SM)

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
        row.setSpacing(SPACE_SM)
        change = QPushButton(i18n.STORAGE_CHANGE)
        change.clicked.connect(self.change_storage)
        row.addWidget(change)
        open_button = QPushButton(i18n.STORAGE_OPEN)
        open_button.setIcon(theme_icon("folder"))
        open_button.clicked.connect(lambda: self.context.open_path(self.context.paths.root))
        row.addWidget(open_button)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)
        return box

    def _build_model_box(self) -> QWidget:
        box = QGroupBox(i18n.MODEL_TITLE)
        layout = QVBoxLayout(box)
        layout.setSpacing(SPACE_SM)

        combo_row = QHBoxLayout()
        combo_row.setSpacing(SPACE_SM)
        self.model_combo = QComboBox()
        combo_row.addWidget(self.model_combo, stretch=1)
        self.model_settings_button = QPushButton(i18n.MODEL_SETTINGS_BUTTON)
        self.model_settings_button.setIcon(theme_icon("settings"))
        self.model_settings_button.setToolTip(i18n.MODEL_SETTINGS_TITLE)
        self.model_settings_button.clicked.connect(self.open_model_settings)
        combo_row.addWidget(self.model_settings_button)
        layout.addLayout(combo_row)

        self.model_info = QLabel("")
        self.model_info.setObjectName("Muted")
        self.model_info.setWordWrap(True)
        layout.addWidget(self.model_info)

        self.quantized_check = QCheckBox("Użyj wersji skwantyzowanej (szybsza, mniejszy plik)")
        self.quantized_check.setChecked(self.context.config.embedding.quantized)
        layout.addWidget(self.quantized_check)

        apply_button = QPushButton("Zastosuj ustawienia modelu")
        apply_button.clicked.connect(self.apply_model)
        # Wyrownanie do prawej trzyma naturalna szerokosc przycisku. Bez niego
        # pionowy uklad rozciaga go na cala karte i wyglada jak pasek.
        layout.addWidget(apply_button, 0, Qt.AlignmentFlag.AlignRight)
        layout.addStretch(1)
        return box

    # --- odswiezanie ------------------------------------------------------

    def refresh(self) -> None:
        # Wypelnianie tabeli nie moze uruchamiac obslugi zmiany pola wyboru.
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for source in self.context.config.sources:
            position = self.table.rowCount()
            self.table.insertRow(position)
            values = [
                source.label,
                "katalog lokalny" if source.kind is SourceKind.LOCAL_DIR else "SharePoint",
                source.describe_location(),
            ]
            for column, value in enumerate(values):
                item = text_item(value)
                if column == 0:
                    item.setData(SOURCE_ID_ROLE, source.source_id)
                self.table.setItem(position, column, item)
            toggle = QTableWidgetItem("")
            toggle.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            toggle.setCheckState(
                Qt.CheckState.Checked if source.enabled else Qt.CheckState.Unchecked
            )
            toggle.setToolTip(i18n.SOURCES_ACTIVE_HINT)
            self.table.setItem(position, 3, toggle)
        self.table.blockSignals(False)
        if self.context.config.sources:
            self.empty_banner.hide_message()
        else:
            self.empty_banner.show_message(i18n.SOURCES_EMPTY_HINT, "info")
        self._refresh_buttons()

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
            suffix = " (zainstalowany)" if model["zainstalowany"] else " (brak plików)"
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
                f"Licencja: {info.license_name}, środowisko: {info.runtime}"
            )
        elif not self.context.config.embedding.semantic_enabled:
            self.model_info.setText(i18n.MODEL_SEMANTIC_DISABLED)
        else:
            self.model_info.setText(i18n.MODEL_MISSING)

    # --- akcje ------------------------------------------------------------

    def _selected_source(self) -> SourceConfig | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        if item is None:
            return None
        try:
            return self.context.config.source(str(item.data(SOURCE_ID_ROLE)))
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
        self.status_message.emit(f"Dodano źródło: {source.label}")

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
            "Dodano źródło SharePoint. Użyj przycisku Testuj połączenie, żeby się zalogować."
        )

    def test_selected(self) -> None:
        source = self._selected_source()
        if source is None:
            show_info(self, i18n.SOURCES_SELECT_FIRST)
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
            prefix = "Połączenie działa. " if status.ok else "Połączenie nie działa. "
            return prefix + status.message

        self.status_message.emit("Sprawdzanie połączenia...")
        task = CallableTask(work, label="test połączenia")
        task.signals.finished.connect(lambda message: show_info(self, str(message)))
        task.signals.failed.connect(
            lambda code, message: show_error(self, f"{message}\n\nKod: {code}")
        )
        thread_pool().start(task)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        """Pole wyboru w kolumnie Aktywne wlacza i wylacza zrodlo."""
        if item.column() != 3:
            return
        id_item = self.table.item(item.row(), 0)
        if id_item is None:
            return
        try:
            source = self.context.config.source(str(id_item.data(SOURCE_ID_ROLE)))
        except Exception:
            return
        enabled = item.checkState() is Qt.CheckState.Checked
        if source.enabled == enabled:
            return
        source.enabled = enabled
        self.context.config = self.context.config.with_source(source)
        self.context.save()
        self.sources_changed.emit()
        template = i18n.SOURCES_ENABLED_ON if enabled else i18n.SOURCES_ENABLED_OFF
        self.status_message.emit(template.format(label=source.label))

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
        self.status_message.emit(f"Usunięto źródło {source.label}.")

    def generate_demo(self) -> None:
        def work() -> str:
            from finddocs.demo import ensure_demo_corpus

            info = ensure_demo_corpus(self.context.paths.root, force=False)
            source = SourceConfig(
                source_id="demo",
                kind=SourceKind.LOCAL_DIR,
                label="Zbiór demonstracyjny",
                local=LocalDirSourceSettings(root_path=str(info.root)),
                exclude_globs=["manifest.json"],
            )
            self.context.config = self.context.config.with_source(source)
            self.context.save()
            return f"Utworzono zbiór demonstracyjny: {info.files} plików w {info.root}"

        self.status_message.emit("Generowanie zbioru demonstracyjnego...")
        task = CallableTask(work, label="zbiór demonstracyjny")

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
        embedding = self.context.config.embedding
        key = str(self.model_combo.currentData())
        quantized = self.quantized_check.isChecked()
        changed = key != embedding.model_key or quantized != embedding.quantized
        if key != embedding.model_key:
            # Przedrostki i dlugosc sekwencji ida za nowym modelem, tak jak
            # w poleceniu finddocs model use. Bez tego skrot zgodnosci czesci
            # wektorowej liczylby sie z parametrow poprzedniego modelu.
            extra = Path(embedding.model_path) if embedding.model_path else None
            sync_embedding_settings(embedding, key, extra=extra)
        embedding.quantized = quantized
        self.context.save()
        if changed:
            show_info(self, i18n.MODEL_REBUILD_REQUIRED)
            self._reload_index_in_background()
        self.refresh()

    def open_model_settings(self) -> None:
        key = str(self.model_combo.currentData() or self.context.config.embedding.model_key)
        dialog = ModelSettingsDialog(self.context, self, model_key=key)
        dialog.models_changed.connect(self.refresh)
        dialog.config_applied.connect(self._after_model_settings)
        dialog.exec()

    def _after_model_settings(self, reload_needed: bool) -> None:
        self.refresh()
        if reload_needed:
            self._reload_index_in_background()
        else:
            self.sources_changed.emit()

    def _reload_index_in_background(self) -> None:
        """Zamyka i otwiera indeks, zeby nowy model albo flaga semantyki zadzialaly."""
        runner = self.context.runner
        if runner is not None and runner.is_running:
            show_warning(self, i18n.MODEL_RELOAD_WHILE_INDEXING)
            return
        self.status_message.emit("Ponowne otwieranie indeksu...")
        task = CallableTask(self.context.reload_index, label="ponowne otwarcie indeksu")

        def done(_result: object) -> None:
            self.refresh()
            self.sources_changed.emit()
            self.status_message.emit("Indeks został otwarty ponownie.")

        task.signals.finished.connect(done)
        task.signals.failed.connect(
            lambda code, message: show_error(self, f"{message}\n\nKod: {code}")
        )
        thread_pool().start(task)


__all__ = ["SharePointDialog", "SourcesView"]

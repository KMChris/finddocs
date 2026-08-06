"""Okno ustawien modelu embeddingow.

Pozwala zaimportowac wlasny model z dysku, pobrac model z Hugging Face,
zmienic przedrostki zapytania i tresci oraz wylaczyc indeksowanie semantyczne.
Import i pobieranie ida do puli watkow, a postep wraca do okna sygnalem Qt.

Przedrostki aktywnego modelu zyja w dwoch miejscach: manifest modelu czyta
dostawca lokalny, a kopia w konfiguracji wchodzi do skrotu zgodnosci czesci
wektorowej. Okno zapisuje oba, zeby zmiana byla widoczna i w liczeniu
embeddingow, i w wykrywaniu niezgodnosci indeksu.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Signal
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
    QVBoxLayout,
    QWidget,
)

from finddocs.errors import FindDocsError
from finddocs.gui import i18n
from finddocs.gui.context import AppContext
from finddocs.gui.dialogs import ask_yes_no, show_error, show_info, show_warning
from finddocs.gui.workers import CallableTask, thread_pool
from finddocs.logging_setup import get_logger
from finddocs.providers.model_manifest import (
    KNOWN_MODELS,
    LocalModelManifest,
    find_model_dir,
    sync_embedding_settings,
    update_manifest_prefixes,
)
from finddocs.providers.model_store import (
    ImportedModel,
    ImportOptions,
    looks_like_repo_id,
    sanitize_model_key,
)

log = get_logger(__name__)

#: Tryby poolingu do wyboru przy imporcie. Pusta wartosc oznacza wykrycie.
_POOLING_CHOICES: tuple[tuple[str, str], ...] = (
    ("wykryj automatycznie", ""),
    ("CLS (pierwszy token)", "cls"),
    ("uśrednianie (mean)", "mean"),
    ("brak (model zwraca gotowy wektor)", "none"),
)


class _ProgressRelay(QObject):
    """Przenosi komunikaty postepu z watku roboczego do watku interfejsu."""

    message = Signal(str)

    def publish(self, text: str) -> None:
        self.message.emit(text)


class ModelImportDialog(QDialog):
    """Parametry importu modelu: zrodlo, nazwa, pooling, kwantyzacja, przedrostki."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        source_label: str = "",
        repo_mode: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(i18n.MODEL_IMPORT_TITLE)
        self.setMinimumWidth(520)
        self._repo_mode = repo_mode

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)
        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)

        self.repo_edit = QLineEdit()
        self.repo_edit.setPlaceholderText("sdadas/mmlw-retrieval-roberta-base")
        if repo_mode:
            form.addRow(i18n.MODEL_IMPORT_REPO, self.repo_edit)
        else:
            source = QLabel(source_label)
            source.setWordWrap(True)
            form.addRow(i18n.MODEL_IMPORT_SOURCE, source)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(i18n.MODEL_IMPORT_NAME_HINT)
        form.addRow(i18n.MODEL_IMPORT_NAME, self.name_edit)

        self.pooling_combo = QComboBox()
        for label, value in _POOLING_CHOICES:
            self.pooling_combo.addItem(label, value)
        form.addRow(i18n.MODEL_IMPORT_POOLING, self.pooling_combo)

        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText(i18n.MODEL_IMPORT_PREFIX_HINT)
        form.addRow(i18n.MODEL_QUERY_PREFIX, self.query_edit)

        self.passage_edit = QLineEdit()
        self.passage_edit.setPlaceholderText(i18n.MODEL_IMPORT_PREFIX_HINT)
        form.addRow(i18n.MODEL_PASSAGE_PREFIX, self.passage_edit)

        self.quantize_check = QCheckBox(i18n.MODEL_IMPORT_QUANTIZE)
        self.quantize_check.setChecked(True)
        form.addRow("", self.quantize_check)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(i18n.MODEL_IMPORT_TITLE)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(i18n.BUTTON_CANCEL)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _validate_and_accept(self) -> None:
        if self._repo_mode and not looks_like_repo_id(self.repo_id()):
            show_warning(self, i18n.MODEL_IMPORT_REPO_INVALID)
            return
        self.accept()

    def repo_id(self) -> str:
        return self.repo_edit.text().strip()

    def to_options(self) -> ImportOptions:
        query = self.query_edit.text()
        passage = self.passage_edit.text()
        return ImportOptions(
            name=self.name_edit.text().strip(),
            quantize=self.quantize_check.isChecked(),
            pooling=str(self.pooling_combo.currentData()),
            query_prefix=query if query else None,
            passage_prefix=passage if passage else None,
        )


class ModelSettingsDialog(QDialog):
    """Ustawienia modelu: przedrostki, semantyka, import i pobieranie."""

    models_changed = Signal()
    config_applied = Signal(bool)
    """Argument mowi, czy indeks wymaga ponownego otwarcia."""

    def __init__(
        self,
        context: AppContext,
        parent: QWidget | None = None,
        *,
        model_key: str = "",
    ) -> None:
        super().__init__(parent)
        self.context = context
        self._model_key = model_key or context.config.embedding.model_key
        self._busy = False
        self._relay = _ProgressRelay()
        self._relay.message.connect(self._on_progress_message)

        self.setWindowTitle(i18n.MODEL_SETTINGS_TITLE)
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)

        layout.addWidget(self._build_prefix_box())
        layout.addWidget(self._build_semantic_box())
        layout.addWidget(self._build_import_box())

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText(i18n.BUTTON_SAVE)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(i18n.BUTTON_CANCEL)
        self.buttons.accepted.connect(self.apply_settings)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    # --- budowa -----------------------------------------------------------

    def _build_prefix_box(self) -> QWidget:
        box = QGroupBox(self._model_display_name())
        form = QFormLayout(box)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)

        self._initial_prefixes = self._read_prefixes()
        self.query_edit = QLineEdit(self._initial_prefixes[0])
        self.passage_edit = QLineEdit(self._initial_prefixes[1])
        form.addRow(i18n.MODEL_QUERY_PREFIX, self.query_edit)
        form.addRow(i18n.MODEL_PASSAGE_PREFIX, self.passage_edit)

        hint = QLabel(i18n.MODEL_PREFIX_HINT)
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        form.addRow(hint)
        return box

    def _build_semantic_box(self) -> QWidget:
        box = QGroupBox(i18n.MODEL_TITLE)
        layout = QVBoxLayout(box)
        layout.setSpacing(8)

        self.semantic_check = QCheckBox(i18n.MODEL_SEMANTIC_TOGGLE)
        self.semantic_check.setChecked(self.context.config.embedding.semantic_enabled)
        layout.addWidget(self.semantic_check)

        hint = QLabel(i18n.MODEL_SEMANTIC_HINT)
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return box

    def _build_import_box(self) -> QWidget:
        box = QGroupBox(i18n.MODEL_IMPORT_TITLE)
        layout = QVBoxLayout(box)
        layout.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.import_disk_button = QPushButton(i18n.MODEL_IMPORT_DISK)
        self.import_disk_button.clicked.connect(self.import_from_disk)
        row.addWidget(self.import_disk_button)
        self.import_repo_button = QPushButton(i18n.MODEL_IMPORT_HF)
        self.import_repo_button.clicked.connect(self.import_from_repo)
        row.addWidget(self.import_repo_button)
        row.addStretch(1)
        layout.addLayout(row)

        self.progress_label = QLabel("")
        self.progress_label.setObjectName("Muted")
        self.progress_label.setWordWrap(True)
        layout.addWidget(self.progress_label)
        return box

    # --- dane modelu ------------------------------------------------------

    def _model_dir(self) -> Path | None:
        embedding = self.context.config.embedding
        extra = Path(embedding.model_path) if embedding.model_path else None
        return find_model_dir(self._model_key, extra)

    def _model_display_name(self) -> str:
        descriptor = KNOWN_MODELS.get(self._model_key)
        if descriptor is not None:
            return descriptor.display_name
        directory = self._model_dir()
        if directory is not None:
            try:
                manifest = LocalModelManifest.load(directory)
            except FindDocsError:
                return self._model_key
            return manifest.display_name or self._model_key
        return self._model_key

    def _read_prefixes(self) -> tuple[str, str]:
        """Obowiazujace przedrostki wybranego modelu: manifest, rejestr, konfiguracja."""
        directory = self._model_dir()
        if directory is not None:
            try:
                manifest = LocalModelManifest.load(directory)
            except FindDocsError:
                manifest = None
            if manifest is not None:
                return manifest.query_prefix, manifest.passage_prefix
        descriptor = KNOWN_MODELS.get(self._model_key)
        if descriptor is not None:
            return descriptor.query_prefix, descriptor.passage_prefix
        embedding = self.context.config.embedding
        if self._model_key == embedding.model_key:
            return embedding.query_prefix, embedding.passage_prefix
        return "", ""

    # --- zapis ------------------------------------------------------------

    def apply_settings(self) -> None:
        """Zapisuje przedrostki i przelacznik semantyki, po czym zamyka okno."""
        if self._busy:
            return
        config = self.context.config
        reload_needed = False
        notes: list[str] = []

        semantic = self.semantic_check.isChecked()
        if semantic != config.embedding.semantic_enabled:
            config.embedding.semantic_enabled = semantic
            reload_needed = True

        prefixes = (self.query_edit.text(), self.passage_edit.text())
        if prefixes != self._initial_prefixes:
            directory = self._model_dir()
            is_active = self._model_key == config.embedding.model_key
            if directory is None and not is_active:
                show_warning(self, i18n.MODEL_PREFIX_NOT_INSTALLED)
                return
            if directory is not None:
                try:
                    update_manifest_prefixes(
                        directory, query_prefix=prefixes[0], passage_prefix=prefixes[1]
                    )
                except (OSError, ValueError, FindDocsError) as exc:
                    message = getattr(exc, "user_message", None) or (
                        "Nie udało się zapisać manifestu modelu."
                    )
                    show_error(self, message)
                    return
            if is_active:
                config.embedding.query_prefix = prefixes[0]
                config.embedding.passage_prefix = prefixes[1]
                reload_needed = True
                notes.append(i18n.MODEL_REBUILD_REQUIRED)

        self.context.save()
        if notes:
            show_info(self, "\n\n".join(notes))
        self.config_applied.emit(reload_needed)
        self.accept()

    def reject(self) -> None:
        if self._busy:
            return
        super().reject()

    # --- import -----------------------------------------------------------

    def import_from_disk(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, i18n.MODEL_IMPORT_DISK)
        if not directory:
            return
        dialog = ModelImportDialog(self, source_label=directory)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        options = dialog.to_options()
        source = Path(directory)
        if not self._confirm_overwrite(options, default_name=source.name):
            return

        def work() -> ImportedModel:
            from finddocs.providers.model_store import import_local_model

            return import_local_model(
                source, options, paths=self.context.paths, progress=self._relay.publish
            )

        self._start_import(work)

    def import_from_repo(self) -> None:
        dialog = ModelImportDialog(self, repo_mode=True)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        repo = dialog.repo_id()
        options = dialog.to_options()
        if not self._confirm_overwrite(options, default_name=repo.split("/")[-1]):
            return
        if not self.context.config.allow_model_download and not self._confirm_download():
            return

        def work() -> ImportedModel:
            from finddocs.providers.model_store import import_from_repo
            from finddocs.security.network import EgressCategory, NetworkPolicy

            policy = NetworkPolicy(enabled_categories={EgressCategory.MODEL_DOWNLOAD})
            return import_from_repo(
                repo, options, paths=self.context.paths, policy=policy, progress=self._relay.publish
            )

        self._start_import(work)

    def _confirm_overwrite(self, options: ImportOptions, *, default_name: str) -> bool:
        try:
            key = sanitize_model_key(options.name or default_name)
        except FindDocsError:
            # Nazwe zweryfikuje wlasciwy import i pokaze pelny komunikat.
            return True
        if not (self.context.paths.models_dir / key).exists():
            return True
        if not ask_yes_no(self, i18n.MODEL_IMPORT_OVERWRITE.format(name=key)):
            return False
        options.force = True
        return True

    def _confirm_download(self) -> bool:
        from finddocs.security.network import DEFAULT_ALLOWLIST, EgressCategory

        hosts = ", ".join(sorted(DEFAULT_ALLOWLIST[EgressCategory.MODEL_DOWNLOAD]))
        return ask_yes_no(self, i18n.MODEL_DOWNLOAD_CONSENT.format(hosts=hosts))

    def _start_import(self, work: Callable[[], ImportedModel]) -> None:
        self._set_busy(True)
        self.progress_label.setText(i18n.MODEL_IMPORT_RUNNING)
        task = CallableTask(work, label="import modelu")
        task.signals.finished.connect(self._on_import_finished)
        task.signals.failed.connect(self._on_import_failed)
        thread_pool().start(task)

    def _on_progress_message(self, text: str) -> None:
        self.progress_label.setText(text)

    def _on_import_finished(self, result: object) -> None:
        self._set_busy(False)
        self.progress_label.setText("")
        if not isinstance(result, ImportedModel):
            return
        self.models_changed.emit()
        details = [
            i18n.MODEL_IMPORT_DONE.format(name=result.key),
            f"Wymiar wektora: {result.dimension}, pooling: {result.pooling}",
        ]
        if result.query_prefix or result.passage_prefix:
            details.append(
                f"Przedrostki: zapytanie „{result.query_prefix}”, treść „{result.passage_prefix}”"
            )
        details.extend(result.notes)
        show_info(self, "\n".join(details))
        if ask_yes_no(self, i18n.MODEL_ACTIVATE_PROMPT.format(name=result.key)):
            self.activate_model(result.key)

    def _on_import_failed(self, code: str, message: str) -> None:
        self._set_busy(False)
        self.progress_label.setText("")
        show_error(self, f"{message}\n\nKod błędu: {code}")

    def activate_model(self, key: str) -> None:
        """Ustawia zaimportowany model jako aktywny, tak jak finddocs model use."""
        embedding = self.context.config.embedding
        extra = Path(embedding.model_path) if embedding.model_path else None
        try:
            manifest = sync_embedding_settings(embedding, key, extra=extra)
        except FindDocsError as exc:
            show_error(self, exc.user_message)
            return
        if manifest is not None:
            embedding.quantized = bool(manifest.quantized)
        self.context.save()
        self._model_key = key
        self._initial_prefixes = (embedding.query_prefix, embedding.passage_prefix)
        self.query_edit.setText(self._initial_prefixes[0])
        self.passage_edit.setText(self._initial_prefixes[1])
        show_info(self, i18n.MODEL_REBUILD_REQUIRED)
        self.config_applied.emit(True)

    # --- pomocnicze -------------------------------------------------------

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.import_disk_button.setEnabled(not busy)
        self.import_repo_button.setEnabled(not busy)
        self.buttons.setEnabled(not busy)


__all__ = ["ModelImportDialog", "ModelSettingsDialog"]

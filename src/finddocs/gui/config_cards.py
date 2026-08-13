"""Karty konfiguracji wyszukiwania semantycznego i magazynu wektorow.

Dawne okno ustawien modelu mieszalo w jednym przewijanym formularzu szesc
grup: przedrostki, semantyke, obliczenia, zdalne API, magazyn wektorow
i import. Tutaj kazdy temat ma osobna karte osadzona wprost na ekranie
Zrodla i konfiguracja: wlacznik semantyki ze stanem dostawcy, profile
dostawcy, model z przedrostkami i importem, obliczenia (dostawca lokalny
albo zdalne API) oraz magazyn wektorow. Panele dostawcy zdalnego i bazy
pgvector sa widoczne tylko wtedy, gdy ten wariant jest wybrany, wiec
domyslna konfiguracja lokalna nie pokazuje ani jednego pola sieciowego.
Karta modelu lokalnego jest ukrywana przez widok zrodel, gdy aktywnym
dostawca jest zdalne API: oba warianty wykluczaja sie, wiec lista modeli
lokalnych nie moze sugerowac rownoleglego wyboru.

Zmiany kosztowne (model, dostawca, magazyn) zapisuje przycisk Zastosuj
danej karty; sam wlacznik semantyki dziala od razu. Karta zglasza sygnalem
``applied``, czy indeks wymaga ponownego otwarcia, a widok zrodel wykonuje
je w tle.

Przedrostki aktywnego modelu zyja w dwoch miejscach: manifest modelu czyta
dostawca lokalny, a kopia w konfiguracji wchodzi do skrotu zgodnosci czesci
wektorowej. Karta modelu zapisuje oba, zeby zmiana byla widoczna i w liczeniu
embeddingow, i w wykrywaniu niezgodnosci indeksu.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import fields as dataclass_fields
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from finddocs.config import (
    EmbeddingProfile,
    VectorStoreSettings,
    apply_profile,
    default_profile_name,
    ensure_profiles,
    save_profile,
    update_active_profile_marker,
)
from finddocs.errors import FindDocsError
from finddocs.gui import i18n
from finddocs.gui.context import AppContext
from finddocs.gui.dialogs import ask_yes_no, show_error, show_info, show_warning
from finddocs.gui.model_dialog import ModelImportDialog
from finddocs.gui.widgets.segmented import SegmentedControl
from finddocs.gui.workers import CallableTask, thread_pool
from finddocs.logging_setup import get_logger
from finddocs.providers.model_manifest import (
    KNOWN_MODELS,
    LocalModelManifest,
    describe_models,
    find_model_dir,
    sync_embedding_settings,
    update_manifest_prefixes,
)
from finddocs.providers.model_store import (
    ImportedModel,
    ImportOptions,
    sanitize_model_key,
)
from finddocs.providers.onnx_local import DEVICE_LABELS, available_devices

if TYPE_CHECKING:
    from finddocs.security.credentials import CredentialStore

log = get_logger(__name__)

#: Szerokosc list rozwijanych i pol liczbowych. Ta sama wartosc co na ekranie
#: Ustawien: kontrolka przy etykiecie, a nie rozciagnieta na cala karte.
CONTROL_WIDTH = 360

#: Urzadzenia obliczen lokalnego modelu w kolejnosci pokazywanej na karcie.
_DEVICE_CHOICES: tuple[tuple[str, str], ...] = (
    ("cpu", i18n.MODEL_DEVICE_CPU),
    ("auto", i18n.MODEL_DEVICE_AUTO),
    ("dml", i18n.MODEL_DEVICE_DML),
    ("cuda", i18n.MODEL_DEVICE_CUDA),
)

#: Kontrakty zdalnego API w kolejnosci pokazywanej na karcie. OpenAI pierwszy,
#: bo jest kontraktem domyslnym.
_PROTOCOL_CHOICES: tuple[tuple[str, str], ...] = (
    ("openai", i18n.MODEL_REMOTE_PROTOCOL_OPENAI),
    ("finddocs", i18n.MODEL_REMOTE_PROTOCOL_FINDDOCS),
)

#: Magazyny wektorow w kolejnosci pokazywanej na karcie.
_VECTOR_BACKEND_CHOICES: tuple[tuple[str, str], ...] = (
    ("faiss", i18n.MODEL_VECTOR_BACKEND_FAISS),
    ("pgvector", i18n.MODEL_VECTOR_BACKEND_PGVECTOR),
)

#: Tryby sslmode do wyboru. Wartosc disable dziala wylacznie dla localhost.
_SSLMODE_CHOICES: tuple[tuple[str, str], ...] = (
    ("require", i18n.MODEL_VECTOR_SSL_REQUIRE),
    ("verify-ca", i18n.MODEL_VECTOR_SSL_VERIFY_CA),
    ("verify-full", i18n.MODEL_VECTOR_SSL_VERIFY_FULL),
    ("disable", i18n.MODEL_VECTOR_SSL_DISABLE),
)


def _credential_store(context: AppContext) -> CredentialStore:
    from finddocs.security.credentials import create_credential_store

    return create_credential_store(context.paths.config_dir)


def _hint_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Hint")
    label.setWordWrap(True)
    return label


def _muted_label(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("Muted")
    label.setWordWrap(True)
    return label


class _ProgressRelay(QObject):
    """Przenosi komunikaty postepu z watku roboczego do watku interfejsu."""

    message = Signal(str)

    def publish(self, text: str) -> None:
        self.message.emit(text)


class ConfigCard(QGroupBox):
    """Wspolna podstawa kart konfiguracji: kontekst, sygnaly i zapis."""

    status_message = Signal(str)
    applied = Signal(bool)
    """Argument mowi, czy indeks wymaga ponownego otwarcia."""

    def __init__(self, title: str, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self.context = context

    def _apply_row(self, handler: Callable[[], None]) -> QHBoxLayout:
        """Wiersz z przyciskiem Zastosuj wyrownanym do prawej krawedzi karty."""
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)
        self.apply_button = QPushButton(i18n.BUTTON_APPLY)
        self.apply_button.clicked.connect(handler)
        row.addWidget(self.apply_button)
        return row

    def _finish_apply(self, notes: list[str], reload_needed: bool) -> None:
        """Zapisuje konfiguracje, pokazuje uwagi i zglasza wynik widokowi.

        Profil to migawka zmieniana wylacznie jawnie, wiec zapis ustawien
        nigdy jej nie nadpisuje. Gdy edycja rozjedzie ustawienia z aktywnym
        profilem, znika samo wskazanie profilu, a jego zawartosc zostaje.
        """
        update_active_profile_marker(self.context.config.embedding)
        self.context.save()
        unique_notes = list(dict.fromkeys(notes))
        if unique_notes:
            show_info(self, "\n\n".join(unique_notes))
        else:
            self.status_message.emit(i18n.SETTINGS_SAVED)
        self.applied.emit(reload_needed)


class SemanticCard(ConfigCard):
    """Wlacznik indeksowania semantycznego i stan aktywnego dostawcy."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(i18n.MODEL_SEMANTIC_BOX, context, parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        self.semantic_check = QCheckBox(i18n.MODEL_SEMANTIC_TOGGLE)
        self.semantic_check.setChecked(context.config.embedding.semantic_enabled)
        self.semantic_check.toggled.connect(self._on_toggled)
        layout.addWidget(self.semantic_check)

        self.status_label = _muted_label()
        layout.addWidget(self.status_label)
        layout.addWidget(_hint_label(i18n.MODEL_SEMANTIC_HINT))

        self.context_check = QCheckBox(i18n.MODEL_CONTEXT_TOGGLE)
        self.context_check.setChecked(context.config.embedding.enrich_context)
        self.context_check.toggled.connect(self._on_context_toggled)
        layout.addWidget(self.context_check)
        layout.addWidget(_hint_label(i18n.MODEL_CONTEXT_HINT))
        self.refresh()

    def refresh(self) -> None:
        """Uzgadnia wlaczniki i opis stanu z konfiguracja oraz otwartym indeksem."""
        self.semantic_check.blockSignals(True)
        self.semantic_check.setChecked(self.context.config.embedding.semantic_enabled)
        self.semantic_check.blockSignals(False)
        self.context_check.blockSignals(True)
        self.context_check.setChecked(self.context.config.embedding.enrich_context)
        self.context_check.blockSignals(False)

        index = self.context.index
        if index is not None and index.provider is not None:
            info = index.provider.info
            self.status_label.setText(
                f"{i18n.MODEL_CURRENT.format(value=info.model_key)}\n"
                f"{i18n.MODEL_DIMENSION.format(value=info.dimension)}\n"
                f"Licencja: {info.license_name}, środowisko: {info.runtime}"
            )
        elif not self.context.config.embedding.semantic_enabled:
            self.status_label.setText(i18n.MODEL_SEMANTIC_DISABLED)
        else:
            self.status_label.setText(i18n.MODEL_MISSING)

    def _on_toggled(self, checked: bool) -> None:
        """Wlacznik dziala od razu: jedna decyzja nie potrzebuje przycisku Zastosuj."""
        embedding = self.context.config.embedding
        if bool(checked) == embedding.semantic_enabled:
            return
        embedding.semantic_enabled = bool(checked)
        self.context.save()
        self.applied.emit(True)

    def _on_context_toggled(self, checked: bool) -> None:
        """Przelacza wzbogacenie o nazwe pliku i sciezke. Zmiana uniewaznia wektory."""
        embedding = self.context.config.embedding
        if bool(checked) == embedding.enrich_context:
            return
        embedding.enrich_context = bool(checked)
        self._finish_apply([i18n.MODEL_REBUILD_REQUIRED], reload_needed=True)


class ProfileCard(ConfigCard):
    """Nazwane profile dostawcy embeddingow i przelaczanie miedzy nimi.

    Profil przenosi komplet ustawien dostawcy: model lokalny z urzadzeniem
    obliczen albo zdalne API z adresem, kontraktem i wymiarem. Aktywacja
    kopiuje profil do biezacej konfiguracji i otwiera indeks ponownie,
    a zapis na pozostalych kartach odswieza migawke aktywnego profilu
    (patrz ``ConfigCard._finish_apply``).
    """

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(i18n.MODEL_PROFILE_BOX, context, parent)
        ensure_profiles(context.config.embedding)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        # Opisy profili bywaja dlugie (nazwa plus model albo adres), wiec lista
        # rozciaga sie na szerokosc formularza, tak jak lista modeli.
        self.profile_combo = QComboBox()
        form.addRow(i18n.MODEL_PROFILE_LABEL, self.profile_combo)
        layout.addLayout(form)

        self.active_label = _muted_label()
        layout.addWidget(self.active_label)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.activate_button = QPushButton(i18n.MODEL_PROFILE_ACTIVATE)
        self.activate_button.setObjectName("Primary")
        self.activate_button.clicked.connect(self.activate_selected)
        buttons.addWidget(self.activate_button)
        self.save_as_button = QPushButton(i18n.MODEL_PROFILE_SAVE_AS)
        self.save_as_button.clicked.connect(self.save_current_as)
        buttons.addWidget(self.save_as_button)
        self.remove_button = QPushButton(i18n.MODEL_PROFILE_REMOVE)
        self.remove_button.clicked.connect(self.remove_selected)
        buttons.addWidget(self.remove_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        layout.addWidget(_hint_label(i18n.MODEL_PROFILE_HINT))
        self.refresh()
        self.profile_combo.currentIndexChanged.connect(lambda _index: self._refresh_buttons())

    # --- dane ---------------------------------------------------------------

    def selected_name(self) -> str:
        return str(self.profile_combo.currentData() or "")

    def _describe(self, profile: EmbeddingProfile) -> str:
        if profile.provider == "internal_api":
            target = profile.internal_api_model or profile.internal_api_url or "?"
            kind = i18n.MODEL_PROFILE_TYPE_REMOTE.format(value=target)
        else:
            kind = i18n.MODEL_PROFILE_TYPE_LOCAL.format(value=profile.model_key)
        return f"{profile.name} ({kind})"

    def refresh(self) -> None:
        """Wypelnia liste profili, zachowujac wybor, i pokazuje profil aktywny."""
        embedding = self.context.config.embedding
        ensure_profiles(embedding)
        combo = self.profile_combo
        combo.blockSignals(True)
        selected = self.selected_name() or embedding.active_profile
        combo.clear()
        for profile in embedding.profiles:
            combo.addItem(self._describe(profile), profile.name)
        position = combo.findData(selected)
        if position < 0:
            position = combo.findData(embedding.active_profile)
        combo.setCurrentIndex(max(0, position))
        combo.blockSignals(False)
        self.active_label.setText(
            i18n.MODEL_PROFILE_ACTIVE.format(
                value=embedding.active_profile or i18n.MODEL_PROFILE_NONE
            )
        )
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        """Aktywacja i usuwanie dotycza profilu innego niz aktywny."""
        active = self.context.config.embedding.active_profile
        name = self.selected_name()
        self.activate_button.setEnabled(bool(name) and name != active)
        self.remove_button.setEnabled(bool(name) and name != active)

    # --- akcje --------------------------------------------------------------

    def activate_selected(self) -> None:
        """Przelacza konfiguracje na wybrany profil i otwiera indeks ponownie."""
        config = self.context.config
        embedding = config.embedding
        name = self.selected_name()
        profile = next((p for p in embedding.profiles if p.name == name), None)
        if profile is None:
            return
        if name == embedding.active_profile:
            self.status_message.emit(i18n.MODEL_PROFILE_ALREADY_ACTIVE.format(name=name))
            return

        # Aktywacja pracuje na kopii: nieudane wczytanie manifestu modelu
        # lokalnego nie zostawia konfiguracji w stanie posrednim. Wynik jest
        # przepisywany do obiektu biezacego, a nie podmieniany, zeby wszystkie
        # trzymane referencje do config.embedding pozostaly aktualne.
        candidate = replace(embedding)
        apply_profile(candidate, profile)
        if profile.provider == "local_onnx":
            extra = Path(profile.model_path) if profile.model_path else None
            try:
                sync_embedding_settings(candidate, profile.model_key, extra=extra)
            except FindDocsError as exc:
                show_error(self, exc.user_message)
                return

        before = config.vector_compat_hash()
        for spec in dataclass_fields(candidate):
            setattr(embedding, spec.name, getattr(candidate, spec.name))
        # Synchronizacja z manifestem mogla odswiezyc przedrostki, wiec migawka
        # profilu jest zapisywana ponownie: aktywacja to jawne dzialanie na nim.
        save_profile(embedding, name)
        notes = [i18n.MODEL_REBUILD_REQUIRED] if config.vector_compat_hash() != before else []
        self.status_message.emit(i18n.MODEL_PROFILE_ACTIVATED.format(name=name))
        self._finish_apply(notes, reload_needed=True)

    def save_current_as(self) -> None:
        """Zapisuje biezace ustawienia dostawcy jako nazwany profil."""
        embedding = self.context.config.embedding
        name, accepted = QInputDialog.getText(
            self,
            i18n.MODEL_PROFILE_SAVE_AS,
            i18n.MODEL_PROFILE_NAME_PROMPT,
            text=default_profile_name(embedding),
        )
        if not accepted:
            return
        name = name.strip()
        if not name:
            show_warning(self, i18n.MODEL_PROFILE_NAME_EMPTY)
            return
        existing = {profile.name for profile in embedding.profiles}
        if name in existing and not ask_yes_no(
            self, i18n.MODEL_PROFILE_OVERWRITE.format(name=name)
        ):
            return
        save_profile(embedding, name)
        self.context.save()
        self.refresh()
        self.status_message.emit(i18n.MODEL_PROFILE_SAVED.format(name=name))

    def remove_selected(self) -> None:
        """Usuwa wybrany profil. Profil aktywny nie moze zostac usuniety."""
        embedding = self.context.config.embedding
        name = self.selected_name()
        if not name:
            return
        if name == embedding.active_profile:
            show_warning(self, i18n.MODEL_PROFILE_REMOVE_ACTIVE)
            return
        if not ask_yes_no(self, i18n.MODEL_PROFILE_REMOVE_CONFIRM.format(name=name)):
            return
        embedding.profiles = [p for p in embedding.profiles if p.name != name]
        self.context.save()
        self.refresh()
        self.status_message.emit(i18n.MODEL_PROFILE_REMOVED.format(name=name))


class ModelCard(ConfigCard):
    """Wybor aktywnego modelu, jego przedrostki oraz import nowych modeli."""

    models_changed = Signal()

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(i18n.MODEL_BOX, context, parent)
        self._busy = False
        self._prefix_key = ""
        self._initial_prefixes: tuple[str, str] = ("", "")
        self._relay = _ProgressRelay()
        self._relay.message.connect(self._on_progress_message)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)

        self.model_combo = QComboBox()
        self.model_combo.currentIndexChanged.connect(self._on_model_selected)
        form.addRow(i18n.MODEL_COMBO_LABEL, self.model_combo)

        self.quantized_check = QCheckBox(i18n.MODEL_QUANTIZED)
        self.quantized_check.setChecked(context.config.embedding.quantized)
        form.addRow("", self.quantized_check)

        self.query_edit = QLineEdit()
        form.addRow(i18n.MODEL_QUERY_PREFIX, self.query_edit)
        self.passage_edit = QLineEdit()
        form.addRow(i18n.MODEL_PASSAGE_PREFIX, self.passage_edit)
        form.addRow(_hint_label(i18n.MODEL_PREFIX_HINT))
        layout.addLayout(form)
        layout.addLayout(self._apply_row(self.apply_settings))

        import_caption = QLabel(i18n.MODEL_IMPORT_TITLE)
        import_caption.setObjectName("StatCaption")
        layout.addWidget(import_caption)

        import_row = QHBoxLayout()
        import_row.setSpacing(8)
        self.import_disk_button = QPushButton(i18n.MODEL_IMPORT_DISK)
        self.import_disk_button.clicked.connect(self.import_from_disk)
        import_row.addWidget(self.import_disk_button)
        self.import_repo_button = QPushButton(i18n.MODEL_IMPORT_HF)
        self.import_repo_button.clicked.connect(self.import_from_repo)
        import_row.addWidget(self.import_repo_button)
        import_row.addStretch(1)
        layout.addLayout(import_row)

        self.progress_label = _muted_label()
        layout.addWidget(self.progress_label)

        self.refresh_models()

    # --- dane modelu ------------------------------------------------------

    def selected_key(self) -> str:
        return str(self.model_combo.currentData() or "")

    def _model_dir(self, key: str) -> Path | None:
        embedding = self.context.config.embedding
        extra = Path(embedding.model_path) if embedding.model_path else None
        return find_model_dir(key, extra)

    def _read_prefixes(self, key: str) -> tuple[str, str]:
        """Obowiazujace przedrostki modelu: manifest, rejestr, konfiguracja."""
        directory = self._model_dir(key)
        if directory is not None:
            try:
                manifest = LocalModelManifest.load(directory)
            except FindDocsError:
                manifest = None
            if manifest is not None:
                return manifest.query_prefix, manifest.passage_prefix
        descriptor = KNOWN_MODELS.get(key)
        if descriptor is not None:
            return descriptor.query_prefix, descriptor.passage_prefix
        embedding = self.context.config.embedding
        if key == embedding.model_key:
            return embedding.query_prefix, embedding.passage_prefix
        return "", ""

    def _load_prefixes(self, key: str) -> None:
        self._prefix_key = key
        self._initial_prefixes = self._read_prefixes(key)
        self.query_edit.setText(self._initial_prefixes[0])
        self.passage_edit.setText(self._initial_prefixes[1])

    def refresh_models(self) -> None:
        """Wypelnia liste modeli, zachowujac biezacy wybor uzytkownika."""
        combo = self.model_combo
        combo.blockSignals(True)
        selected = self.selected_key() or self.context.config.embedding.model_key
        combo.clear()
        for model in describe_models():
            suffix = " (zainstalowany)" if model["zainstalowany"] else " (brak plików)"
            combo.addItem(str(model["nazwa"]) + suffix, model["klucz"])
        position = combo.findData(selected)
        if position < 0:
            position = combo.findData(self.context.config.embedding.model_key)
        combo.setCurrentIndex(max(0, position))
        combo.blockSignals(False)
        key = self.selected_key()
        if key != self._prefix_key:
            self._load_prefixes(key)

    def _on_model_selected(self, _index: int) -> None:
        """Zmiana wyboru pokazuje przedrostki i wariant modelu jeszcze przed zapisem."""
        key = self.selected_key()
        if not key or key == self._prefix_key:
            return
        self._load_prefixes(key)
        directory = self._model_dir(key)
        if directory is None:
            return
        try:
            manifest = LocalModelManifest.load(directory)
        except FindDocsError:
            return
        self.quantized_check.setChecked(bool(manifest.quantized))

    # --- zapis --------------------------------------------------------------

    def apply_settings(self) -> None:
        """Ustawia wybrany model jako aktywny i zapisuje wariant oraz przedrostki."""
        if self._busy:
            return
        embedding = self.context.config.embedding
        key = self.selected_key()
        if not key:
            return
        reload_needed = False
        notes: list[str] = []

        if key != embedding.model_key:
            # Przedrostki i dlugosc sekwencji ida za nowym modelem, tak jak
            # w poleceniu finddocs model use. Bez tego skrot zgodnosci czesci
            # wektorowej liczylby sie z parametrow poprzedniego modelu.
            extra = Path(embedding.model_path) if embedding.model_path else None
            try:
                sync_embedding_settings(embedding, key, extra=extra)
            except FindDocsError as exc:
                show_error(self, exc.user_message)
                return
            reload_needed = True
            notes.append(i18n.MODEL_REBUILD_REQUIRED)

        quantized = self.quantized_check.isChecked()
        if quantized != embedding.quantized:
            embedding.quantized = quantized
            reload_needed = True
            notes.append(i18n.MODEL_REBUILD_REQUIRED)

        prefixes = (self.query_edit.text(), self.passage_edit.text())
        if prefixes != (embedding.query_prefix, embedding.passage_prefix):
            directory = self._model_dir(key)
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
            embedding.query_prefix = prefixes[0]
            embedding.passage_prefix = prefixes[1]
            reload_needed = True
            notes.append(i18n.MODEL_REBUILD_REQUIRED)

        self._prefix_key = key
        self._initial_prefixes = prefixes
        self._finish_apply(notes, reload_needed)

    def refresh_after_profile(self) -> None:
        """Uzgadnia karte z konfiguracja po aktywacji profilu."""
        embedding = self.context.config.embedding
        self.refresh_models()
        position = self.model_combo.findData(embedding.model_key)
        self.model_combo.blockSignals(True)
        self.model_combo.setCurrentIndex(max(0, position))
        self.model_combo.blockSignals(False)
        self.quantized_check.setChecked(embedding.quantized)
        self._load_prefixes(embedding.model_key)

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
        self.refresh_models()
        position = self.model_combo.findData(key)
        self.model_combo.blockSignals(True)
        self.model_combo.setCurrentIndex(max(0, position))
        self.model_combo.blockSignals(False)
        self.quantized_check.setChecked(embedding.quantized)
        self._load_prefixes(key)
        show_info(self, i18n.MODEL_REBUILD_REQUIRED)
        self.applied.emit(True)

    # --- import -------------------------------------------------------------

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
        self.refresh_models()
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

    # --- pomocnicze ---------------------------------------------------------

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.import_disk_button.setEnabled(not busy)
        self.import_repo_button.setEnabled(not busy)
        self.apply_button.setEnabled(not busy)


class ComputeCard(ConfigCard):
    """Dostawca embeddingow: obliczenia lokalne albo zdalne API organizacji."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(i18n.MODEL_COMPUTE_BOX, context, parent)
        embedding = context.config.embedding
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        caption = QLabel(i18n.MODEL_PROVIDER_LABEL)
        caption.setObjectName("StatCaption")
        layout.addWidget(caption)

        remote_active = embedding.provider == "internal_api" and embedding.internal_api_enabled
        self.provider_switch = SegmentedControl(
            [i18n.MODEL_PROVIDER_LOCAL, i18n.MODEL_PROVIDER_REMOTE],
            hints=[i18n.MODEL_PROVIDER_LOCAL_HINT, i18n.MODEL_PROVIDER_REMOTE_HINT],
            checked=1 if remote_active else 0,
        )
        self.provider_switch.changed.connect(self._on_provider_changed)
        switch_row = QHBoxLayout()
        switch_row.addWidget(self.provider_switch)
        switch_row.addStretch(1)
        layout.addLayout(switch_row)

        self.local_panel = self._build_local_panel()
        layout.addWidget(self.local_panel)
        self.remote_panel = self._build_remote_panel()
        layout.addWidget(self.remote_panel)
        layout.addLayout(self._apply_row(self.apply_settings))
        self._show_provider_panels()

    # --- budowa -------------------------------------------------------------

    def _build_local_panel(self) -> QWidget:
        panel = QWidget()
        form = QFormLayout(panel)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        embedding = self.context.config.embedding

        self.device_combo = QComboBox()
        for value, label in _DEVICE_CHOICES:
            self.device_combo.addItem(label, value)
        position = self.device_combo.findData(embedding.device)
        self.device_combo.setCurrentIndex(max(0, position))
        self.device_combo.setFixedWidth(CONTROL_WIDTH)
        form.addRow(i18n.MODEL_DEVICE_LABEL, self.device_combo)

        devices = available_devices()
        detected = ", ".join(DEVICE_LABELS[d] for d, ok in devices.items() if ok) or "brak"
        form.addRow("", _muted_label(i18n.MODEL_DEVICE_AVAILABLE.format(value=detected)))

        self.batch_spin = QSpinBox()
        self.batch_spin.setRange(1, 512)
        self.batch_spin.setValue(embedding.batch_size)
        self.batch_spin.setFixedWidth(CONTROL_WIDTH)
        form.addRow(i18n.MODEL_BATCH_LABEL, self.batch_spin)

        self.batch_docs_spin = QSpinBox()
        self.batch_docs_spin.setRange(1, 64)
        self.batch_docs_spin.setValue(self.context.config.indexing.embed_batch_documents)
        self.batch_docs_spin.setToolTip(i18n.MODEL_BATCH_DOCS_HINT)
        self.batch_docs_spin.setFixedWidth(CONTROL_WIDTH)
        form.addRow(i18n.MODEL_BATCH_DOCS_LABEL, self.batch_docs_spin)

        form.addRow(_hint_label(i18n.MODEL_DEVICE_HINT))
        return panel

    def _build_remote_panel(self) -> QWidget:
        panel = QWidget()
        form = QFormLayout(panel)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        embedding = self.context.config.embedding

        self.remote_url_edit = QLineEdit(embedding.internal_api_url)
        self.remote_url_edit.setPlaceholderText(i18n.MODEL_REMOTE_URL_PLACEHOLDER)
        form.addRow(i18n.MODEL_REMOTE_URL, self.remote_url_edit)

        self.remote_allow_http_check = QCheckBox(i18n.MODEL_REMOTE_ALLOW_HTTP)
        self.remote_allow_http_check.setChecked(self.context.config.allow_plain_http_localhost)
        self.remote_allow_http_check.setToolTip(i18n.MODEL_REMOTE_ALLOW_HTTP_HINT)
        form.addRow("", self.remote_allow_http_check)
        form.addRow(_hint_label(i18n.MODEL_REMOTE_ALLOW_HTTP_HINT))

        self.remote_protocol_combo = QComboBox()
        for value, label in _PROTOCOL_CHOICES:
            self.remote_protocol_combo.addItem(label, value)
        position = self.remote_protocol_combo.findData(embedding.internal_api_protocol)
        self.remote_protocol_combo.setCurrentIndex(max(0, position))
        self.remote_protocol_combo.setFixedWidth(CONTROL_WIDTH)
        form.addRow(i18n.MODEL_REMOTE_PROTOCOL, self.remote_protocol_combo)

        self.remote_model_edit = QLineEdit(embedding.internal_api_model)
        form.addRow(i18n.MODEL_REMOTE_MODEL, self.remote_model_edit)

        self.remote_dimension_spin = QSpinBox()
        self.remote_dimension_spin.setRange(16, 8192)
        self.remote_dimension_spin.setValue(embedding.internal_api_dimension)
        self.remote_dimension_spin.setFixedWidth(CONTROL_WIDTH)
        form.addRow(i18n.MODEL_REMOTE_DIMENSION, self.remote_dimension_spin)

        self.remote_batch_spin = QSpinBox()
        self.remote_batch_spin.setRange(1, 1024)
        self.remote_batch_spin.setValue(embedding.internal_api_batch_size)
        self.remote_batch_spin.setFixedWidth(CONTROL_WIDTH)
        form.addRow(i18n.MODEL_REMOTE_BATCH, self.remote_batch_spin)

        self.remote_query_prefix_edit = QLineEdit(embedding.query_prefix)
        form.addRow(i18n.MODEL_QUERY_PREFIX, self.remote_query_prefix_edit)
        self.remote_passage_prefix_edit = QLineEdit(embedding.passage_prefix)
        form.addRow(i18n.MODEL_PASSAGE_PREFIX, self.remote_passage_prefix_edit)
        form.addRow(_hint_label(i18n.MODEL_REMOTE_PREFIX_HINT))

        self.remote_key_edit = QLineEdit()
        self.remote_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.remote_key_edit.setPlaceholderText(i18n.MODEL_REMOTE_KEY_PLACEHOLDER)
        key_row = QHBoxLayout()
        key_row.setSpacing(8)
        key_row.addWidget(self.remote_key_edit, stretch=1)
        self.remote_key_save_button = QPushButton(i18n.MODEL_REMOTE_KEY_SAVE)
        self.remote_key_save_button.clicked.connect(self.save_api_key)
        key_row.addWidget(self.remote_key_save_button)
        self.remote_key_clear_button = QPushButton(i18n.MODEL_REMOTE_KEY_CLEAR)
        self.remote_key_clear_button.clicked.connect(self.clear_api_key)
        key_row.addWidget(self.remote_key_clear_button)
        form.addRow(i18n.MODEL_REMOTE_KEY, key_row)

        self.remote_key_status = _muted_label()
        form.addRow("", self.remote_key_status)
        self._update_key_status()

        form.addRow(_hint_label(i18n.MODEL_REMOTE_HINT))
        return panel

    # --- przelaczanie dostawcy ----------------------------------------------

    def remote_selected(self) -> bool:
        return self.provider_switch.checked_index() == 1

    def set_provider(self, remote: bool) -> None:
        """Przelacza dostawce w kontrolce; zapis wykonuje dopiero Zastosuj."""
        self.provider_switch.set_checked_index(1 if remote else 0)
        self._show_provider_panels()

    def _on_provider_changed(self, _index: int) -> None:
        self._show_provider_panels()

    def _show_provider_panels(self) -> None:
        remote = self.remote_selected()
        self.local_panel.setVisible(not remote)
        self.remote_panel.setVisible(remote)

    def refresh_from_config(self) -> None:
        """Uzgadnia pola karty z konfiguracja, np. po aktywacji profilu."""
        embedding = self.context.config.embedding
        remote_active = embedding.provider == "internal_api" and embedding.internal_api_enabled
        self.provider_switch.set_checked_index(1 if remote_active else 0)
        position = self.device_combo.findData(embedding.device)
        self.device_combo.setCurrentIndex(max(0, position))
        self.batch_spin.setValue(embedding.batch_size)
        self.batch_docs_spin.setValue(self.context.config.indexing.embed_batch_documents)
        self.remote_url_edit.setText(embedding.internal_api_url)
        self.remote_allow_http_check.setChecked(self.context.config.allow_plain_http_localhost)
        position = self.remote_protocol_combo.findData(embedding.internal_api_protocol)
        self.remote_protocol_combo.setCurrentIndex(max(0, position))
        self.remote_model_edit.setText(embedding.internal_api_model)
        self.remote_dimension_spin.setValue(embedding.internal_api_dimension)
        self.remote_batch_spin.setValue(embedding.internal_api_batch_size)
        self.remote_query_prefix_edit.setText(embedding.query_prefix)
        self.remote_passage_prefix_edit.setText(embedding.passage_prefix)
        self._show_provider_panels()

    # --- zapis ----------------------------------------------------------------

    def apply_settings(self) -> None:
        """Zapisuje dostawce, urzadzenie, paczki i parametry zdalnego API."""
        embedding = self.context.config.embedding
        remote = self.remote_selected()
        remote_url = self.remote_url_edit.text().strip()
        if remote and not remote_url:
            show_warning(self, i18n.MODEL_REMOTE_URL_REQUIRED)
            return
        reload_needed = False
        notes: list[str] = []

        target_provider = "internal_api" if remote else "local_onnx"
        provider_changed = target_provider != embedding.provider
        if provider_changed:
            embedding.provider = target_provider
            reload_needed = True

        device = str(self.device_combo.currentData())
        if device != embedding.device:
            embedding.device = device
            reload_needed = True

        batch = int(self.batch_spin.value())
        if batch != embedding.batch_size:
            embedding.batch_size = batch
            reload_needed = True

        batch_docs = int(self.batch_docs_spin.value())
        if batch_docs != self.context.config.indexing.embed_batch_documents:
            self.context.config.indexing.embed_batch_documents = batch_docs

        # Zgoda na http do localhost nie zmienia wektorow, wiec nie wchodzi do
        # tozsamosci przestrzeni; wymaga tylko ponownego otwarcia dostawcy,
        # bo polityka sieciowa powstaje na nowo przy zapisie konfiguracji.
        allow_http = self.remote_allow_http_check.isChecked()
        if allow_http != self.context.config.allow_plain_http_localhost:
            self.context.config.allow_plain_http_localhost = allow_http
            reload_needed = True

        remote_protocol = str(self.remote_protocol_combo.currentData())
        remote_model = self.remote_model_edit.text().strip()
        remote_dimension = int(self.remote_dimension_spin.value())
        remote_batch = int(self.remote_batch_spin.value())
        remote_identity_changed = (
            remote_protocol != embedding.internal_api_protocol
            or remote_model != embedding.internal_api_model
            or remote_dimension != embedding.internal_api_dimension
        )
        if remote:
            # Przedrostki dokleja aplikacja przed wysylka, wiec dla zdalnego
            # dostawcy sa czescia tozsamosci przestrzeni wektorow.
            remote_prefixes = (
                self.remote_query_prefix_edit.text(),
                self.remote_passage_prefix_edit.text(),
            )
            if remote_prefixes != (embedding.query_prefix, embedding.passage_prefix):
                embedding.query_prefix, embedding.passage_prefix = remote_prefixes
                remote_identity_changed = True
                reload_needed = True
        remote_changed = (
            remote != embedding.internal_api_enabled
            or remote_url != embedding.internal_api_url
            or remote_batch != embedding.internal_api_batch_size
            or remote_identity_changed
        )
        if remote_changed:
            embedding.internal_api_enabled = remote
            embedding.internal_api_url = remote_url
            embedding.internal_api_protocol = remote_protocol
            embedding.internal_api_model = remote_model
            embedding.internal_api_dimension = remote_dimension
            embedding.internal_api_batch_size = remote_batch
            reload_needed = True

        if provider_changed or (target_provider == "internal_api" and remote_identity_changed):
            notes.append(i18n.MODEL_REBUILD_REQUIRED)
        self._finish_apply(notes, reload_needed)

    # --- klucz API zdalnego dostawcy ------------------------------------------

    def _update_key_status(self) -> None:
        from finddocs.security.credentials import EMBEDDING_API_KEY_NAME

        try:
            store = _credential_store(self.context)
            present = store.get_secret(EMBEDDING_API_KEY_NAME) is not None
        except Exception as exc:
            log.warning("gui.api_key_status_failed", error_type=type(exc).__name__)
            present = False
        self.remote_key_status.setText(
            i18n.MODEL_REMOTE_KEY_PRESENT if present else i18n.MODEL_REMOTE_KEY_MISSING
        )
        self.remote_key_clear_button.setEnabled(present)

    def save_api_key(self) -> None:
        """Zapisuje klucz API w magazynie poswiadczen. Klucz nie trafia do pliku."""
        key = self.remote_key_edit.text().strip()
        if not key:
            show_warning(self, i18n.MODEL_REMOTE_KEY_EMPTY)
            return
        from finddocs.security.credentials import EMBEDDING_API_KEY_NAME

        try:
            _credential_store(self.context).set_secret(EMBEDDING_API_KEY_NAME, key)
        except FindDocsError as exc:
            show_error(self, exc.user_message)
            return
        self.remote_key_edit.clear()
        self._update_key_status()
        show_info(self, i18n.MODEL_REMOTE_KEY_SAVED)

    def clear_api_key(self) -> None:
        from finddocs.security.credentials import EMBEDDING_API_KEY_NAME

        try:
            _credential_store(self.context).delete_secret(EMBEDDING_API_KEY_NAME)
        except FindDocsError as exc:
            show_error(self, exc.user_message)
            return
        self._update_key_status()
        show_info(self, i18n.MODEL_REMOTE_KEY_CLEARED)


class VectorStoreCard(ConfigCard):
    """Magazyn wektorow: plik lokalny FAISS albo baza PostgreSQL z pgvector."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(i18n.MODEL_VECTOR_BOX, context, parent)
        self._busy = False
        vector = context.config.vector_store
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        self.vector_backend_combo = QComboBox()
        for value, label in _VECTOR_BACKEND_CHOICES:
            self.vector_backend_combo.addItem(label, value)
        position = self.vector_backend_combo.findData(vector.backend)
        self.vector_backend_combo.setCurrentIndex(max(0, position))
        self.vector_backend_combo.setFixedWidth(CONTROL_WIDTH)
        self.vector_backend_combo.currentIndexChanged.connect(self._on_backend_changed)
        form.addRow(i18n.MODEL_VECTOR_BACKEND, self.vector_backend_combo)
        layout.addLayout(form)

        self.pgvector_panel = self._build_pgvector_panel()
        layout.addWidget(self.pgvector_panel)
        layout.addWidget(_hint_label(i18n.MODEL_VECTOR_HINT))
        layout.addLayout(self._apply_row(self.apply_settings))
        self._show_backend_panel()

    # --- budowa ---------------------------------------------------------------

    def _build_pgvector_panel(self) -> QWidget:
        panel = QWidget()
        form = QFormLayout(panel)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        vector = self.context.config.vector_store

        self.vector_host_edit = QLineEdit(vector.pgvector_host)
        self.vector_host_edit.setPlaceholderText(i18n.MODEL_VECTOR_HOST_PLACEHOLDER)
        form.addRow(i18n.MODEL_VECTOR_HOST, self.vector_host_edit)

        self.vector_port_spin = QSpinBox()
        self.vector_port_spin.setRange(1, 65535)
        self.vector_port_spin.setValue(vector.pgvector_port)
        self.vector_port_spin.setFixedWidth(CONTROL_WIDTH)
        form.addRow(i18n.MODEL_VECTOR_PORT, self.vector_port_spin)

        self.vector_database_edit = QLineEdit(vector.pgvector_database)
        form.addRow(i18n.MODEL_VECTOR_DATABASE, self.vector_database_edit)

        self.vector_user_edit = QLineEdit(vector.pgvector_user)
        form.addRow(i18n.MODEL_VECTOR_USER, self.vector_user_edit)

        self.vector_schema_edit = QLineEdit(vector.pgvector_schema)
        form.addRow(i18n.MODEL_VECTOR_SCHEMA, self.vector_schema_edit)

        self.vector_table_edit = QLineEdit(vector.pgvector_table)
        form.addRow(i18n.MODEL_VECTOR_TABLE, self.vector_table_edit)

        self.vector_ssl_combo = QComboBox()
        for value, label in _SSLMODE_CHOICES:
            self.vector_ssl_combo.addItem(label, value)
        position = self.vector_ssl_combo.findData(vector.pgvector_sslmode)
        self.vector_ssl_combo.setCurrentIndex(max(0, position))
        self.vector_ssl_combo.setFixedWidth(CONTROL_WIDTH)
        form.addRow(i18n.MODEL_VECTOR_SSLMODE, self.vector_ssl_combo)

        self.vector_password_edit = QLineEdit()
        self.vector_password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.vector_password_edit.setPlaceholderText(i18n.MODEL_VECTOR_PASSWORD_PLACEHOLDER)
        password_row = QHBoxLayout()
        password_row.setSpacing(8)
        password_row.addWidget(self.vector_password_edit, stretch=1)
        self.vector_password_save_button = QPushButton(i18n.MODEL_VECTOR_PASSWORD_SAVE)
        self.vector_password_save_button.clicked.connect(self.save_vector_password)
        password_row.addWidget(self.vector_password_save_button)
        self.vector_password_clear_button = QPushButton(i18n.MODEL_VECTOR_PASSWORD_CLEAR)
        self.vector_password_clear_button.clicked.connect(self.clear_vector_password)
        password_row.addWidget(self.vector_password_clear_button)
        form.addRow(i18n.MODEL_VECTOR_PASSWORD, password_row)

        self.vector_password_status = _muted_label()
        form.addRow("", self.vector_password_status)
        self._update_vector_password_status()

        test_row = QHBoxLayout()
        test_row.setSpacing(8)
        self.vector_test_button = QPushButton(i18n.MODEL_VECTOR_TEST)
        self.vector_test_button.clicked.connect(self.test_vector_connection)
        test_row.addWidget(self.vector_test_button)
        test_row.addStretch(1)
        form.addRow("", test_row)

        self.vector_test_label = _muted_label()
        form.addRow("", self.vector_test_label)
        return panel

    # --- przelaczanie magazynu --------------------------------------------------

    def selected_backend(self) -> str:
        return str(self.vector_backend_combo.currentData())

    def _on_backend_changed(self, _index: int) -> None:
        self._show_backend_panel()

    def _show_backend_panel(self) -> None:
        self.pgvector_panel.setVisible(self.selected_backend() == "pgvector")

    # --- zapis --------------------------------------------------------------------

    def apply_settings(self) -> None:
        """Zapisuje rodzaj magazynu i parametry polaczenia z baza pgvector."""
        if self._busy:
            return
        vector = self.context.config.vector_store
        backend = self.selected_backend()
        host = self.vector_host_edit.text().strip()
        database = self.vector_database_edit.text().strip()
        user = self.vector_user_edit.text().strip()
        if backend == "pgvector" and not (host and database and user):
            show_warning(self, i18n.MODEL_VECTOR_FIELDS_REQUIRED)
            return
        reload_needed = False
        notes: list[str] = []

        port = int(self.vector_port_spin.value())
        schema = self.vector_schema_edit.text().strip() or "public"
        table = self.vector_table_edit.text().strip() or "finddocs_vectors"
        sslmode = str(self.vector_ssl_combo.currentData())
        identity_changed = (
            backend != vector.backend
            or host != vector.pgvector_host
            or port != vector.pgvector_port
            or database != vector.pgvector_database
            or schema != vector.pgvector_schema
            or table != vector.pgvector_table
        )
        changed = (
            identity_changed or user != vector.pgvector_user or sslmode != vector.pgvector_sslmode
        )
        if changed:
            vector.backend = backend
            vector.pgvector_host = host
            vector.pgvector_port = port
            vector.pgvector_database = database
            vector.pgvector_user = user
            vector.pgvector_schema = schema
            vector.pgvector_table = table
            vector.pgvector_sslmode = sslmode
            reload_needed = True
        if backend != "faiss" and identity_changed:
            notes.append(i18n.MODEL_REBUILD_REQUIRED)
        self._finish_apply(notes, reload_needed)

    # --- haslo i test polaczenia -----------------------------------------------

    def _update_vector_password_status(self) -> None:
        from finddocs.security.credentials import PGVECTOR_PASSWORD_NAME

        try:
            store = _credential_store(self.context)
            present = store.get_secret(PGVECTOR_PASSWORD_NAME) is not None
        except Exception as exc:
            log.warning("gui.vector_password_status_failed", error_type=type(exc).__name__)
            present = False
        self.vector_password_status.setText(
            i18n.MODEL_VECTOR_PASSWORD_PRESENT if present else i18n.MODEL_VECTOR_PASSWORD_MISSING
        )
        self.vector_password_clear_button.setEnabled(present)

    def save_vector_password(self) -> None:
        """Zapisuje haslo bazy w magazynie poswiadczen. Haslo nie trafia do pliku."""
        password = self.vector_password_edit.text()
        if not password:
            show_warning(self, i18n.MODEL_VECTOR_PASSWORD_EMPTY)
            return
        from finddocs.security.credentials import PGVECTOR_PASSWORD_NAME

        try:
            _credential_store(self.context).set_secret(PGVECTOR_PASSWORD_NAME, password)
        except FindDocsError as exc:
            show_error(self, exc.user_message)
            return
        self.vector_password_edit.clear()
        self._update_vector_password_status()
        show_info(self, i18n.MODEL_VECTOR_PASSWORD_SAVED)

    def clear_vector_password(self) -> None:
        from finddocs.security.credentials import PGVECTOR_PASSWORD_NAME

        try:
            _credential_store(self.context).delete_secret(PGVECTOR_PASSWORD_NAME)
        except FindDocsError as exc:
            show_error(self, exc.user_message)
            return
        self._update_vector_password_status()
        show_info(self, i18n.MODEL_VECTOR_PASSWORD_CLEARED)

    def _vector_settings_from_fields(self) -> VectorStoreSettings:
        """Buduje ustawienia magazynu z biezacych pol karty, bez zapisywania ich."""
        return VectorStoreSettings(
            backend="pgvector",
            pgvector_host=self.vector_host_edit.text().strip(),
            pgvector_port=int(self.vector_port_spin.value()),
            pgvector_database=self.vector_database_edit.text().strip(),
            pgvector_user=self.vector_user_edit.text().strip(),
            pgvector_schema=self.vector_schema_edit.text().strip() or "public",
            pgvector_table=self.vector_table_edit.text().strip() or "finddocs_vectors",
            pgvector_sslmode=str(self.vector_ssl_combo.currentData()),
            pgvector_connect_timeout_seconds=(
                self.context.config.vector_store.pgvector_connect_timeout_seconds
            ),
            pgvector_statement_timeout_seconds=(
                self.context.config.vector_store.pgvector_statement_timeout_seconds
            ),
        )

    def test_vector_connection(self) -> None:
        """Probuje polaczyc sie z baza wektorowa na podstawie pol karty.

        Test dziala na wartosciach z formularza, takze przed ich zapisaniem.
        Polityka sieciowa dopuszcza na czas proby dokladnie ten jeden host.
        """
        settings = self._vector_settings_from_fields()
        host = settings.pgvector_host
        if not (host and settings.pgvector_database and settings.pgvector_user):
            show_warning(self, i18n.MODEL_VECTOR_FIELDS_REQUIRED)
            return
        self._set_busy(True)
        self.vector_test_label.setText(i18n.MODEL_VECTOR_TEST_RUNNING)
        config_dir = self.context.paths.config_dir

        def work() -> dict[str, object]:
            from finddocs.indexing.pgvector import PgVectorStore
            from finddocs.indexing.vector_factory import pgvector_password_provider
            from finddocs.security.network import EgressCategory, NetworkPolicy

            policy = NetworkPolicy(
                enabled_categories={EgressCategory.VECTOR_DB},
                extra_hosts={EgressCategory.VECTOR_DB: (host.lower(),)},
            )
            store = PgVectorStore(
                settings,
                password_provider=pgvector_password_provider(config_dir),
                policy=policy,
            )
            return store.ping()

        task = CallableTask(work, label="test bazy wektorowej")
        task.signals.finished.connect(self._on_vector_test_finished)
        task.signals.failed.connect(self._on_vector_test_failed)
        thread_pool().start(task)

    def _on_vector_test_finished(self, result: object) -> None:
        self._set_busy(False)
        if not isinstance(result, dict):
            self.vector_test_label.setText("")
            return
        extension = result.get("pgvector")
        if extension is None:
            self.vector_test_label.setText(i18n.MODEL_VECTOR_TEST_NO_EXTENSION)
            show_warning(self, i18n.MODEL_VECTOR_TEST_NO_EXTENSION)
            return
        message = i18n.MODEL_VECTOR_TEST_OK.format(
            version=result.get("wersja_serwera", "?"), extension=extension
        )
        self.vector_test_label.setText(message)
        show_info(self, message)

    def _on_vector_test_failed(self, code: str, message: str) -> None:
        self._set_busy(False)
        self.vector_test_label.setText(message)
        show_error(self, f"{message}\n\nKod błędu: {code}")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.vector_test_button.setEnabled(not busy)
        self.apply_button.setEnabled(not busy)


__all__ = [
    "CONTROL_WIDTH",
    "ComputeCard",
    "ConfigCard",
    "ModelCard",
    "ProfileCard",
    "SemanticCard",
    "VectorStoreCard",
]

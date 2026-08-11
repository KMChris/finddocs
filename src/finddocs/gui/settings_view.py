"""Ekran ustawien: zakladki Ogolne i Diagnostyka oraz okno O programie.

Uzytkownik koncowy nie dotyka terminala ani plikow konfiguracyjnych, wiec
kazde ustawienie interfejsu musi miec kontrolke. Zmiany dzialaja od razu
i zapisuja sie w chwili zmiany, bez osobnego przycisku Zastosuj: przycisk
mialby sens tylko przy zmianach kosztownych, a te ustawienia takie nie sa.

Diagnostyka jest zakladka tego ekranu, nie osobna pozycja nawigacji:
to narzedzie serwisowe, a nie codzienna praca z dokumentami.

Zmiana motywu wymaga przebudowy okna, bo ikony i palety kontrolek powstaja
z paleta w konstruktorach widokow. Widok zglasza wiec zadanie sygnalem,
a przebudowe robi warstwa uruchomieniowa aplikacji.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from finddocs.gui import i18n
from finddocs.gui.context import AppContext
from finddocs.gui.diagnostics_view import DiagnosticsView
from finddocs.gui.theme import SPACE_LG, SPACE_MD, SPACE_SM, mica_supported, theme_icon
from finddocs.gui.widgets.page import PageHeader, page_layout
from finddocs.gui.widgets.segmented import SegmentedControl
from finddocs.gui.widgets.tabs import TabPanel
from finddocs.logging_setup import get_logger
from finddocs.version import APP_NAME, APP_VERSION

log = get_logger(__name__)

#: Wartosci konfiguracji motywu w kolejnosci segmentow przelacznika.
THEME_VALUES: tuple[str, ...] = ("system", "light", "dark")

#: Zakres liczby wynikow na stronie. Dolna granica chroni przed pusta lista,
#: gorna przed strona, ktorej przewijanie zastepuje paginacje.
PAGE_SIZE_MIN = 5
PAGE_SIZE_MAX = 100


class AboutDialog(QDialog):
    """Okno O programie: wersja, katalogi danych i logow."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.setWindowTitle(i18n.ABOUT_TITLE)
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_LG + 4, SPACE_LG, SPACE_LG + 4, SPACE_LG)
        layout.setSpacing(SPACE_SM)

        title = QLabel(f"{APP_NAME} {APP_VERSION}")
        title.setObjectName("AppTitle")
        layout.addWidget(title)

        subtitle = QLabel(i18n.APP_SUBTITLE)
        subtitle.setObjectName("Muted")
        layout.addWidget(subtitle)
        layout.addSpacing(SPACE_MD)

        for caption, value in (
            (i18n.ABOUT_DATA_DIR, str(context.paths.root)),
            (i18n.ABOUT_LOGS_DIR, str(context.paths.logs_dir)),
        ):
            row_caption = QLabel(caption)
            row_caption.setObjectName("StatCaption")
            layout.addWidget(row_caption)
            row_value = QLabel(value)
            row_value.setWordWrap(True)
            row_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(row_value)

        layout.addSpacing(SPACE_MD)
        buttons = QHBoxLayout()
        buttons.setSpacing(SPACE_SM)
        open_data = QPushButton(i18n.ABOUT_OPEN_DATA)
        open_data.setIcon(theme_icon("folder"))
        open_data.clicked.connect(lambda: self.context.open_path(self.context.paths.root))
        buttons.addWidget(open_data)
        open_logs = QPushButton(i18n.ABOUT_OPEN_LOGS)
        open_logs.setIcon(theme_icon("folder"))
        open_logs.clicked.connect(lambda: self.context.open_path(self.context.paths.logs_dir))
        buttons.addWidget(open_logs)
        buttons.addStretch(1)
        close = QPushButton(i18n.BUTTON_CLOSE)
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)


class SettingsView(QWidget):
    """Ustawienia wygladu i zachowania interfejsu."""

    status_message = Signal(str)
    #: Zadanie zmiany motywu. Przebudowe okna robi warstwa uruchomieniowa.
    theme_change_requested = Signal(str)
    #: Zmiana ustawien wyszukiwania, ktore ekran wyszukiwania trzyma w polach.
    search_settings_changed = Signal()

    def __init__(self, context: AppContext) -> None:
        super().__init__()
        self.context = context

        root = page_layout(self)
        self.header = PageHeader(i18n.NAV_SETTINGS)
        root.addWidget(self.header)

        self.diagnostics = DiagnosticsView(context)
        self.diagnostics.status_message.connect(self.status_message)

        self.tabs = TabPanel()
        self.tabs.addTab(self._build_general_tab(), i18n.SETTINGS_TAB_GENERAL)
        self.tabs.addTab(self.diagnostics, i18n.DIAG_TITLE)
        root.addWidget(self.tabs, stretch=1)

    # --- budowa -----------------------------------------------------------

    def _build_general_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_MD)
        layout.addWidget(self._build_appearance_box())
        layout.addWidget(self._build_behavior_box())

        about_row = QHBoxLayout()
        self.about_button = QPushButton(i18n.ABOUT_TITLE)
        self.about_button.clicked.connect(self.show_about)
        about_row.addWidget(self.about_button)
        about_row.addStretch(1)
        layout.addLayout(about_row)
        layout.addStretch(1)
        return page

    def _build_appearance_box(self) -> QWidget:
        box = QGroupBox(i18n.SETTINGS_APPEARANCE)
        layout = QVBoxLayout(box)
        layout.setSpacing(SPACE_SM)

        caption = QLabel(i18n.SETTINGS_THEME)
        caption.setObjectName("StatCaption")
        layout.addWidget(caption)

        current = self.context.config.ui.theme
        checked = THEME_VALUES.index(current) if current in THEME_VALUES else 0
        self.theme_switch = SegmentedControl(
            [i18n.THEME_LABELS[value] for value in THEME_VALUES], checked=checked
        )
        self.theme_switch.changed.connect(self._on_theme_changed)
        row = QHBoxLayout()
        row.addWidget(self.theme_switch)
        row.addStretch(1)
        layout.addLayout(row)

        hint = QLabel(i18n.SETTINGS_THEME_HINT)
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # Przelacznik pokazuje sie tylko tam, gdzie Mica w ogole moze dzialac.
        self.mica_check = QCheckBox(i18n.SETTINGS_MICA)
        self.mica_check.setChecked(self.context.config.ui.mica)
        self.mica_check.setToolTip(i18n.SETTINGS_MICA_HINT)
        self.mica_check.toggled.connect(self._on_mica_toggled)
        self.mica_check.setVisible(mica_supported())
        layout.addWidget(self.mica_check)
        return box

    def _build_behavior_box(self) -> QWidget:
        box = QGroupBox(i18n.SETTINGS_BEHAVIOR)
        form = QFormLayout(box)
        form.setHorizontalSpacing(SPACE_LG)
        form.setVerticalSpacing(SPACE_SM + 2)

        self.open_with_combo = QComboBox()
        self.open_with_combo.addItem(i18n.SETTINGS_OPEN_WEB, "web_url")
        self.open_with_combo.addItem(i18n.SETTINGS_OPEN_LOCAL, "local_path")
        position = self.open_with_combo.findData(self.context.config.ui.open_documents_with)
        self.open_with_combo.setCurrentIndex(max(0, position))
        self.open_with_combo.currentIndexChanged.connect(self._on_open_with_changed)
        form.addRow(i18n.SETTINGS_OPEN_WITH, self.open_with_combo)

        self.page_size_spin = QSpinBox()
        self.page_size_spin.setRange(PAGE_SIZE_MIN, PAGE_SIZE_MAX)
        self.page_size_spin.setSingleStep(5)
        self.page_size_spin.setValue(self.context.config.search.page_size)
        self.page_size_spin.valueChanged.connect(self._on_page_size_changed)
        form.addRow(i18n.SETTINGS_PAGE_SIZE, self.page_size_spin)

        self.show_scores_check = QCheckBox(i18n.SETTINGS_SHOW_SCORES)
        self.show_scores_check.setChecked(self.context.config.ui.show_scores)
        self.show_scores_check.toggled.connect(self._on_show_scores_toggled)
        form.addRow("", self.show_scores_check)

        self.incremental_check = QCheckBox(i18n.SETTINGS_INCREMENTAL)
        self.incremental_check.setChecked(self.context.config.search.incremental)
        self.incremental_check.setToolTip(i18n.SETTINGS_INCREMENTAL_HINT)
        self.incremental_check.toggled.connect(self._on_incremental_toggled)
        form.addRow("", self.incremental_check)
        return box

    # --- reakcje ----------------------------------------------------------

    def _save(self) -> None:
        try:
            self.context.save()
        except Exception as exc:
            log.warning("gui.settings_save_failed", error_type=type(exc).__name__)
            return
        self.status_message.emit(i18n.SETTINGS_SAVED)

    def _on_theme_changed(self, index: int) -> None:
        value = THEME_VALUES[index] if 0 <= index < len(THEME_VALUES) else "system"
        if value == self.context.config.ui.theme:
            return
        self.context.config.ui.theme = value
        self._save()
        self.theme_change_requested.emit(value)

    def _on_mica_toggled(self, checked: bool) -> None:
        self.context.config.ui.mica = bool(checked)
        self._save()
        # Tlo okna to atrybut natywnego uchwytu, wiec okno trzeba zbudowac
        # od nowa. Uzywamy tej samej sciezki, co zmiana motywu.
        self.theme_change_requested.emit(self.context.config.ui.theme)

    def _on_open_with_changed(self, _index: int) -> None:
        self.context.config.ui.open_documents_with = str(self.open_with_combo.currentData())
        self._save()

    def _on_page_size_changed(self, value: int) -> None:
        self.context.config.search.page_size = int(value)
        self._save()
        self.search_settings_changed.emit()

    def _on_show_scores_toggled(self, checked: bool) -> None:
        self.context.config.ui.show_scores = bool(checked)
        self._save()

    def _on_incremental_toggled(self, checked: bool) -> None:
        self.context.config.search.incremental = bool(checked)
        self._save()
        self.search_settings_changed.emit()

    def show_about(self) -> None:
        dialog = AboutDialog(self.context, self)
        dialog.exec()


__all__ = [
    "PAGE_SIZE_MAX",
    "PAGE_SIZE_MIN",
    "THEME_VALUES",
    "AboutDialog",
    "SettingsView",
]

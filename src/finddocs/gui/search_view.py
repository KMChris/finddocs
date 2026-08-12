"""Ekran wyszukiwania.

Uklad ekranu jest podporzadkowany jednemu zadaniu: wpisac zapytanie i przejrzec
wyniki. Dlatego chrome nad lista jest tak niski, jak to mozliwe:

* liczba wynikow jest w wierszu tytulu, a nie w osobnym wierszu;
* baner nad lista dostaje wylacznie uwagi zalezne od zapytania (obcieta lista,
  brak indeksu semantycznego). Stala charakterystyka trybu jest w podpowiedzi
  pod przelacznikiem: ostrzezenie widoczne zawsze przestaje byc ostrzezeniem;
* wiersz stron pojawia sie tylko wtedy, gdy jest wiecej niz jedna strona.
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Callable
from functools import partial

from PySide6.QtCore import QDate, QSize, QStringListModel, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDateEdit,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from finddocs.gui import i18n
from finddocs.gui.context import AppContext
from finddocs.gui.theme import (
    QUERY_HEIGHT,
    SPACE_LG,
    SPACE_MD,
    SPACE_SM,
    SPACE_XS,
    Palette,
    accent_icon,
    muted_icon,
    theme_icon,
)
from finddocs.gui.widgets.motion import apply_soft_shadow, expand_vertically
from finddocs.gui.widgets.page import Banner, PageHeader, page_layout
from finddocs.gui.widgets.result_card import EmptyState, ResultCard
from finddocs.gui.widgets.segmented import SegmentedControl
from finddocs.gui.widgets.skeleton import SkeletonCard
from finddocs.gui.workers import CallableTask, CancellationFlag, SearchTask, thread_pool
from finddocs.logging_setup import get_logger
from finddocs.search.highlight import strip_highlight
from finddocs.search.service import HYBRID_NOTE, SEMANTIC_NOTE
from finddocs.types import (
    DateRange,
    DocumentHit,
    SearchFilters,
    SearchMode,
    SearchRequest,
    SearchResponse,
)

log = get_logger(__name__)

FILTER_ANY = i18n.FILTER_ANY

#: Data oznaczajaca brak ograniczenia w polu daty. Pole pokazuje wtedy napis
#: ``wszystkie`` zamiast liczby.
NO_DATE = QDate(1900, 1, 1)

#: Liczba kolumn panelu filtrow. Kolumny dziela szerokosc rowno, wiec pola
#: sasiadujacych wierszy sa wyrownane niezaleznie od dlugosci podpisow.
FILTER_COLUMNS = 4

#: Liczba zarysow kart pokazywanych w czasie wyszukiwania.
SKELETON_CARDS = 3


#: Uwagi opisujace nature trybu, niezalezne od zapytania. Ich tresc niesie
#: podpowiedz pod przelacznikiem trybow, wiec baner ich nie powtarza. Powtarzane
#: przy kazdym wyszukiwaniu ostrzezenie uczy pomijania banera i zaslania uwagi,
#: ktore naprawde dotycza biezacego zapytania.
EDUCATION_NOTES: frozenset[str] = frozenset({HYBRID_NOTE, SEMANTIC_NOTE})

#: Ile ostatnich zapytan podpowiada pole zapytania. Historia zyje wylacznie
#: w pamieci procesu: zapisanie jej na dysku byloby rejestrem zapytan, a tego
#: aplikacja unika (zapisywanie zapytan w logu jest osobna, jawna zgoda).
QUERY_HISTORY_LIMIT = 20

#: Opoznienie wyszukiwania przyrostowego od ostatniego wpisanego znaku.
INCREMENTAL_DELAY_MS = 300

#: Najkrotsze zapytanie uruchamiajace wyszukiwanie przyrostowe.
INCREMENTAL_MIN_CHARS = 2

#: Powyzej tylu dokumentow wyszukiwanie przyrostowe nie wlacza sie samo:
#: kazde nacisniecie klawisza to pelne zapytanie FTS z licznikiem trafien.
INCREMENTAL_MAX_DOCUMENTS = 50_000


class SearchView(QWidget):
    """Pole zapytania, tryby, filtry i lista wynikow."""

    status_message = Signal(str)
    #: Akcje ekranu powitalnego. Nawigacje i wykonanie robi okno glowne,
    #: bo widok wyszukiwania nie zna widoku zrodel.
    welcome_add_source = Signal()
    welcome_create_demo = Signal()

    def __init__(self, context: AppContext, palette: Palette) -> None:
        super().__init__()
        self.context = context
        self.palette_colors = palette
        self._task: SearchTask | None = None
        self._token: CancellationFlag | None = None
        self._response: SearchResponse | None = None
        self._busy = False
        self._page = 0
        self._page_size = context.config.search.page_size

        root = page_layout(self)

        self.header = PageHeader(i18n.NAV_SEARCH)
        root.addWidget(self.header)

        root.addWidget(self._build_query_row())
        root.addWidget(self._build_mode_row())

        self.mode_hint = QLabel(i18n.MODE_HINTS[self.current_mode()])
        self.mode_hint.setObjectName("Hint")
        self.mode_hint.setWordWrap(True)
        root.addWidget(self.mode_hint)

        # Chipy aktywnych filtrow: stan filtrow widac bez otwierania panelu,
        # a klikniecie chipa zdejmuje pojedynczy filtr. Licznik na przycisku
        # Filtry zostaje, bo mowi o zawezeniu takze przy zwinietym panelu.
        self._chips_row = QWidget()
        self._chips_layout = QHBoxLayout(self._chips_row)
        self._chips_layout.setContentsMargins(0, 0, 0, 0)
        self._chips_layout.setSpacing(SPACE_SM)
        self._chips_layout.addStretch(1)
        self._chips_row.setVisible(False)

        self._filters_panel = self._build_filters()
        root.addWidget(self._filters_panel)
        self._filters_panel.setVisible(False)

        # Wiersz chipow stoi pod panelem, nie nad nim. Nad panelem pierwszy
        # ustawiony filtr spychal caly panel w dol i kolejne pole uciekalo spod
        # kursora. Pod panelem chipy odsuwaja tylko wyniki, a przy zwinietym
        # panelu i tak wypadaja tuz pod paskiem trybow.
        root.addWidget(self._chips_row)

        self.notes_banner = Banner()
        root.addWidget(self.notes_banner)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._results_host = QWidget()
        self._results_layout = QVBoxLayout(self._results_host)
        self._results_layout.setContentsMargins(0, 0, SPACE_SM, 0)
        self._results_layout.setSpacing(SPACE_MD)
        self._results_layout.addStretch(1)
        self._scroll.setWidget(self._results_host)
        root.addWidget(self._scroll, stretch=1)

        self._pagination = self._build_pagination()
        root.addWidget(self._pagination)
        self._update_pagination()

        # Wyszukiwanie przyrostowe: tryb Dokladne liczy sie na zywo w trakcie
        # pisania, po krotkiej przerwie od ostatniego znaku. Tryby z modelem
        # czekaja na Enter, bo ich koszt jest nieporownywalnie wiekszy.
        self._incremental_allowed = False
        self._incremental_timer = QTimer(self)
        self._incremental_timer.setSingleShot(True)
        self._incremental_timer.setInterval(INCREMENTAL_DELAY_MS)
        self._incremental_timer.timeout.connect(self._run_incremental)
        self.query_edit.textChanged.connect(self._on_query_text_changed)

        self._build_shortcuts()
        self._update_filter_count()
        self._refresh_incremental_allowed()
        self.show_default_empty()

    # --- budowa interfejsu ------------------------------------------------

    def _build_query_row(self) -> QWidget:
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(SPACE_SM)

        self.query_edit = QLineEdit()
        self.query_edit.setObjectName("SearchBox")
        self.query_edit.setPlaceholderText(i18n.SEARCH_PLACEHOLDER)
        self.query_edit.setAccessibleName(i18n.A11Y_QUERY)
        self.query_edit.setClearButtonEnabled(True)
        self._restyle_clear_button()
        self.query_edit.returnPressed.connect(self.run_search)
        # Podpowiedzi ostatnich zapytan tej sesji. Patrz QUERY_HISTORY_LIMIT.
        self._history: list[str] = []
        self._history_model = QStringListModel(self)
        completer = QCompleter(self._history_model, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.query_edit.setCompleter(completer)
        # Pole zapytania jest bohaterem ekranu, wiec jako jedyne pole dostaje
        # miekki cien (tylko w motywie jasnym).
        apply_soft_shadow(self.query_edit, self.palette_colors)
        row.addWidget(self.query_edit, stretch=1)

        # Jeden kwadratowy przycisk: lupa uruchamia wyszukiwanie, a w trakcie
        # pracy zamienia sie w ikone zatrzymania z podpowiedzia Przerwij.
        self.search_button = QPushButton()
        self.search_button.setObjectName("PrimaryIcon")
        self.search_button.setIcon(accent_icon("search", self.palette_colors))
        self.search_button.setIconSize(QSize(18, 18))
        side = max(self.query_edit.sizeHint().height(), QUERY_HEIGHT)
        self.search_button.setFixedSize(QSize(side, side))
        self.search_button.setToolTip(i18n.SEARCH_BUTTON)
        self.search_button.setAccessibleName(i18n.SEARCH_BUTTON)
        self.search_button.clicked.connect(self._on_search_clicked)
        row.addWidget(self.search_button)
        return container

    def _restyle_clear_button(self) -> None:
        """Daje przyciskowi czyszczenia glif motywu zamiast znaku systemowego.

        Rozmiar rysunku bierze sie z metryki stylu (``SEARCH_ICON_METRIC``), bo
        Qt maluje ten przycisk w rozmiarze ``PM_SmallIconSize`` pola i nie patrzy
        na ``setIconSize``. Sam przycisk tworzy Qt, wiec docieramy do niego przez
        liste dzieci pola; gdyby Qt przestalo go tworzyc, petla nic nie zrobi.
        """
        for button in self.query_edit.findChildren(QToolButton):
            button.setIcon(muted_icon("clear", self.palette_colors))

    def _build_mode_row(self) -> QWidget:
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(SPACE_SM)

        modes = list(SearchMode)
        default_mode = SearchMode(self.context.config.search.default_mode)
        self.mode_switch = SegmentedControl(
            [i18n.MODE_LABELS[mode] for mode in modes],
            hints=[i18n.MODE_HINTS[mode] for mode in modes],
            checked=modes.index(default_mode),
        )
        self.mode_switch.changed.connect(lambda _index: self._update_mode_hint())
        # Testy i skroty klawiszowe siegaja po grupe przyciskow bezposrednio.
        self.mode_group = self.mode_switch.group
        row.addWidget(self.mode_switch)
        row.addStretch(1)

        # Porzadek wynikow. Tryby wektorowe zwracaja ranking podobienstwa,
        # wiec sortowanie po dacie istnieje tylko w trybie Dokladne. Poza nim
        # lista jest ukryta, nie wylaczona: szara lista ,,Trafnosc'' sugerowala,
        # ze wyniki da sie sortowac, tylko cos jest zepsute.
        self.sort_combo = QComboBox()
        self.sort_combo.addItem(i18n.SORT_RELEVANCE, "relevance")
        self.sort_combo.addItem(i18n.SORT_NEWEST, "modified_desc")
        self.sort_combo.setToolTip(i18n.SORT_HINT)
        self.sort_combo.setAccessibleName(i18n.A11Y_SORT)
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        row.addWidget(self.sort_combo)
        self.sort_combo.setVisible(self.current_mode() is SearchMode.EXACT)

        self.filters_toggle = QPushButton(i18n.SEARCH_FILTERS)
        self.filters_toggle.setIcon(theme_icon("filter", self.palette_colors))
        self.filters_toggle.setCheckable(True)
        self.filters_toggle.setToolTip(i18n.SEARCH_FILTERS_SHORTCUT)
        self.filters_toggle.toggled.connect(self._toggle_filters)
        row.addWidget(self.filters_toggle)
        return container

    def _build_filters(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Card")
        grid = QGridLayout(panel)
        grid.setContentsMargins(SPACE_LG, SPACE_LG - 2, SPACE_LG, SPACE_LG - 2)
        grid.setHorizontalSpacing(SPACE_LG)
        # Podpis przylega do swojego pola, a grupy pol rozdziela pusty wiersz.
        grid.setVerticalSpacing(SPACE_XS)
        for column in range(FILTER_COLUMNS):
            grid.setColumnStretch(column, 1)

        self.filter_extension = QComboBox()
        self.filter_source = QComboBox()
        self.filter_library = QComboBox()
        self.filter_author = QComboBox()
        for combo in (
            self.filter_extension,
            self.filter_source,
            self.filter_library,
            self.filter_author,
        ):
            combo.addItem(FILTER_ANY, "")
            combo.currentIndexChanged.connect(self._update_filter_count)
            # Pole wypelnia swoja kolumne siatki. Bez tego szerokosc listy idzie
            # za najdluzsza wartoscia z indeksu i pola maja przypadkowe
            # szerokosci: Autor na cala kolumne, Typ pliku waski.
            combo.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            combo.setMinimumContentsLength(8)
            combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.filter_path = QLineEdit()
        self.filter_path.setPlaceholderText("np. transakcje/klientA")
        self.filter_path.textChanged.connect(self._update_filter_count)
        self.filter_path.returnPressed.connect(self.run_search)

        self.filter_date_from = QDateEdit()
        self.filter_date_to = QDateEdit()
        for editor in (self.filter_date_from, self.filter_date_to):
            editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            editor.setCalendarPopup(True)
            editor.setDisplayFormat("dd.MM.yyyy")
            editor.setSpecialValueText(FILTER_ANY)
            editor.setMinimumDate(NO_DATE)
            editor.setDate(NO_DATE)
            editor.dateChanged.connect(self._update_filter_count)

        self.filter_ocr = QCheckBox(i18n.FILTER_OCR)
        self.filter_ocr.toggled.connect(self._update_filter_count)

        fields = [
            (i18n.FILTER_EXTENSION, self.filter_extension),
            (i18n.FILTER_SOURCE, self.filter_source),
            (i18n.FILTER_LIBRARY, self.filter_library),
            (i18n.FILTER_AUTHOR, self.filter_author),
            (i18n.FILTER_PATH, self.filter_path),
            (i18n.FILTER_DATE_FROM, self.filter_date_from),
            (i18n.FILTER_DATE_TO, self.filter_date_to),
        ]
        for index, (label_text, widget) in enumerate(fields):
            label = QLabel(label_text)
            label.setObjectName("StatCaption")
            base_row = index // FILTER_COLUMNS * 3
            grid.addWidget(label, base_row, index % FILTER_COLUMNS)
            grid.addWidget(widget, base_row + 1, index % FILTER_COLUMNS)
        rows = -(-len(fields) // FILTER_COLUMNS)
        for row in range(rows):
            grid.setRowMinimumHeight(row * 3 + 2, SPACE_MD)

        # Pole wyboru OCR trafia w wolne miejsce po prawej stronie wiersza dat,
        # a przycisk czyszczenia pod nie, w jednej pionowej linii z przyciskiem
        # Filtry nad panelem.
        grid.addWidget(self.filter_ocr, 4, FILTER_COLUMNS - 1)
        self.clear_filters_button = QPushButton(i18n.SEARCH_FILTERS_CLEAR)
        self.clear_filters_button.setIcon(theme_icon("cross", self.palette_colors))
        self.clear_filters_button.clicked.connect(self.clear_filters)
        grid.addWidget(
            self.clear_filters_button,
            6,
            FILTER_COLUMNS - 1,
            Qt.AlignmentFlag.AlignRight,
        )
        return panel

    def _build_pagination(self) -> QWidget:
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(SPACE_SM)
        self.previous_button = QPushButton(i18n.PAGINATION_PREVIOUS)
        self.previous_button.setIcon(theme_icon("chevron-left", self.palette_colors))
        self.previous_button.setToolTip(i18n.PAGINATION_PREVIOUS_HINT)
        self.previous_button.clicked.connect(lambda: self.change_page(-1))
        self.next_button = QPushButton(i18n.PAGINATION_NEXT)
        self.next_button.setIcon(theme_icon("chevron-right", self.palette_colors))
        self.next_button.setToolTip(i18n.PAGINATION_NEXT_HINT)
        # Odwrocony kierunek ukladu stawia ikone po prawej stronie napisu.
        self.next_button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.next_button.clicked.connect(lambda: self.change_page(1))
        self.page_label = QLabel("")
        self.page_label.setObjectName("Muted")
        row.addStretch(1)
        row.addWidget(self.previous_button)
        row.addWidget(self.page_label)
        row.addWidget(self.next_button)
        row.addStretch(1)
        return container

    def _build_shortcuts(self) -> None:
        """Skroty dzialajace na tym ekranie."""
        for keys, delta in (("Alt+Left", -1), ("Alt+Right", 1)):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.activated.connect(lambda step=delta: self.change_page(step))
        filters = QShortcut(QKeySequence("Ctrl+Shift+F"), self)
        filters.activated.connect(self.filters_toggle.toggle)

    # --- dane pomocnicze --------------------------------------------------

    def refresh_filter_values(self) -> None:
        """Uzupelnia listy filtrow wartosciami z indeksu."""
        index = self.context.index
        if index is None:
            return
        try:
            extensions = index.repository.distinct_values("extension")
            authors = index.repository.distinct_values("author", limit=200)
            libraries = index.repository.distinct_values("library", limit=200)
        except Exception as exc:
            log.warning("gui.filters_refresh_failed", error_type=type(exc).__name__)
            return

        sources = [(s.source_id, s.label) for s in self.context.config.sources]
        self._fill_combo(self.filter_extension, [(e, e) for e in extensions])
        self._fill_combo(self.filter_author, [(a, a) for a in authors])
        self._fill_combo(self.filter_library, [(lib, lib) for lib in libraries])
        self._fill_combo(self.filter_source, sources)
        # Wartosc, ktorej po przeindeksowaniu nie ma juz w indeksie, wraca do
        # ,,wszystkie''. Licznik na przycisku Filtry musi to zauwazyc.
        self._update_filter_count()

    def _fill_combo(self, combo: QComboBox, values: list[tuple[str, str]]) -> None:
        current = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(FILTER_ANY, "")
        for value, label in values:
            combo.addItem(label, value)
        position = combo.findData(current)
        combo.setCurrentIndex(position if position >= 0 else 0)
        combo.blockSignals(False)

    def current_mode(self) -> SearchMode:
        checked = self.mode_group.checkedId()
        modes = list(SearchMode)
        return modes[checked] if 0 <= checked < len(modes) else SearchMode.HYBRID

    def current_filters(self) -> SearchFilters:
        def combo_value(combo: QComboBox) -> list[str]:
            value = combo.currentData()
            return [str(value)] if value else []

        def date_value(editor: QDateEdit) -> _dt.date | None:
            qdate = editor.date()
            if qdate == NO_DATE:
                return None
            return _dt.date(qdate.year(), qdate.month(), qdate.day())

        return SearchFilters(
            sources=combo_value(self.filter_source),
            libraries=combo_value(self.filter_library),
            extensions=combo_value(self.filter_extension),
            authors=combo_value(self.filter_author),
            path_prefix=self.filter_path.text().strip() or None,
            modified=DateRange(
                start=date_value(self.filter_date_from), end=date_value(self.filter_date_to)
            ),
            ocr_only=True if self.filter_ocr.isChecked() else None,
        )

    def active_filter_count(self) -> int:
        """Ile filtrow zaweza wyniki. Liczba idzie na przycisk Filtry."""
        filters = self.current_filters()
        parts: list[object] = [
            filters.sources,
            filters.libraries,
            filters.extensions,
            filters.authors,
            filters.path_prefix,
            filters.modified.start,
            filters.modified.end,
            filters.ocr_only,
        ]
        return sum(1 for part in parts if part)

    def clear_filters(self) -> None:
        for combo in (
            self.filter_extension,
            self.filter_source,
            self.filter_library,
            self.filter_author,
        ):
            combo.setCurrentIndex(0)
        self.filter_path.clear()
        self.filter_date_from.setDate(NO_DATE)
        self.filter_date_to.setDate(NO_DATE)
        self.filter_ocr.setChecked(False)
        self._update_filter_count()

    def _toggle_filters(self, visible: bool) -> None:
        self._filters_panel.setVisible(visible)
        if visible:
            self.refresh_filter_values()
            # Panel rozwija sie plynnie. Chowanie jest natychmiastowe: ruch
            # przy znikaniu opoznialby dostep do wynikow pod panelem.
            expand_vertically(self._filters_panel)

    def _update_filter_count(self) -> None:
        """Napis na przycisku Filtry mowi, ile filtrow dziala.

        Bez tego zwiniety panel ukrywa fakt, ze wyniki sa zawezone, a uzytkownik
        widzi krotka liste i nie wie dlaczego.
        """
        count = self.active_filter_count()
        self.filters_toggle.setText(
            i18n.SEARCH_FILTERS_ACTIVE.format(count=count) if count else i18n.SEARCH_FILTERS
        )
        self.clear_filters_button.setEnabled(count > 0)
        self._rebuild_filter_chips()

    def _active_filter_entries(self) -> list[tuple[str, Callable[[], None]]]:
        """Pary (napis chipa, zdjecie filtra) dla aktywnych filtrow."""
        entries: list[tuple[str, Callable[[], None]]] = []
        combos = (
            (i18n.FILTER_EXTENSION, self.filter_extension),
            (i18n.FILTER_SOURCE, self.filter_source),
            (i18n.FILTER_LIBRARY, self.filter_library),
            (i18n.FILTER_AUTHOR, self.filter_author),
        )
        for caption, combo in combos:
            if combo.currentData():
                entries.append(
                    (f"{caption}: {combo.currentText()}", partial(combo.setCurrentIndex, 0))
                )
        if self.filter_path.text().strip():
            entries.append(
                (
                    f"{i18n.FILTER_PATH}: {self.filter_path.text().strip()}",
                    self.filter_path.clear,
                )
            )
        for template, editor in (
            (i18n.FILTER_DATE_FROM_CHIP, self.filter_date_from),
            (i18n.FILTER_DATE_TO_CHIP, self.filter_date_to),
        ):
            if editor.date() != NO_DATE:
                entries.append(
                    (
                        template.format(date=editor.date().toString("dd.MM.yyyy")),
                        partial(editor.setDate, NO_DATE),
                    )
                )
        if self.filter_ocr.isChecked():
            entries.append((i18n.FILTER_OCR, partial(self.filter_ocr.setChecked, False)))
        return entries

    def filter_chips(self) -> list[QPushButton]:
        """Chipy widoczne aktualnie w wierszu filtrow.

        Czytamy uklad, a nie liste dzieci: chip usuniety przez ``deleteLater``
        jest dzieckiem do najblizszego obiegu petli zdarzen, ale w ukladzie
        juz go nie ma.
        """
        chips: list[QPushButton] = []
        for position in range(self._chips_layout.count()):
            item = self._chips_layout.itemAt(position)
            widget = item.widget() if item is not None else None
            if isinstance(widget, QPushButton) and widget.objectName() == "FilterChip":
                chips.append(widget)
        return chips

    def _rebuild_filter_chips(self) -> None:
        while self._chips_layout.count() > 1:
            item = self._chips_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        entries = self._active_filter_entries()
        for position, (text, reset) in enumerate(entries):
            chip = QPushButton(text)
            chip.setObjectName("FilterChip")
            chip.setIcon(theme_icon("cross", self.palette_colors))
            chip.setIconSize(QSize(10, 10))
            # Odwrocony kierunek ukladu stawia krzyzyk po prawej stronie napisu.
            chip.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            chip.setToolTip(i18n.FILTER_CHIP_HINT)
            chip.clicked.connect(partial(self._remove_filter, reset))
            self._chips_layout.insertWidget(position, chip)
        self._chips_row.setVisible(bool(entries))

    def _remove_filter(self, reset: Callable[[], None]) -> None:
        """Zdejmuje jeden filtr i odswieza wyniki, jezeli jakies sa."""
        reset()
        if self._response is not None and self.query_edit.text().strip():
            self.run_search()

    def _update_mode_hint(self) -> None:
        self.mode_hint.setText(i18n.MODE_HINTS[self.current_mode()])
        self.sort_combo.setVisible(self.current_mode() is SearchMode.EXACT)

    def current_order(self) -> str:
        """Porzadek wynikow. Poza trybem dokladnym zawsze trafnosc."""
        if self.current_mode() is not SearchMode.EXACT:
            return "relevance"
        return str(self.sort_combo.currentData() or "relevance")

    def _on_sort_changed(self, _index: int) -> None:
        if self._response is not None and self.query_edit.text().strip():
            self.run_search()

    def _remember_query(self, query: str) -> None:
        """Dopisuje zapytanie do podrecznej historii podpowiedzi."""
        if not query:
            return
        self._history = [query] + [q for q in self._history if q != query]
        del self._history[QUERY_HISTORY_LIMIT:]
        self._history_model.setStringList(self._history)

    # --- wyszukiwanie -----------------------------------------------------

    def apply_config(self) -> None:
        """Przejmuje zmienione ustawienia wyszukiwania bez restartu aplikacji.

        Liczba wynikow na stronie jest trzymana w polu, bo wchodzi do wyliczen
        stron. Wracamy tez na pierwsza strone, zeby numeracja byla spojna.
        """
        self._page_size = self.context.config.search.page_size
        self._page = 0
        self._refresh_incremental_allowed()

    def _refresh_incremental_allowed(self) -> None:
        """Sprawdza, czy wyszukiwanie przyrostowe ma prawo dzialac.

        Odczyt stanu indeksu to zapytanie do bazy, wiec wynik jest trzymany
        w polu i odswiezany przy wejsciu na ekran oraz po zmianie indeksu.
        """
        allowed = bool(self.context.config.search.incremental)
        if allowed:
            index = self.context.index
            try:
                allowed = (
                    index is not None
                    and index.status().indexed_documents <= INCREMENTAL_MAX_DOCUMENTS
                )
            except Exception as exc:
                log.warning("gui.incremental_check_failed", error_type=type(exc).__name__)
                allowed = False
        self._incremental_allowed = allowed

    def _on_query_text_changed(self, text: str) -> None:
        stripped = text.strip()
        if not stripped:
            self._incremental_timer.stop()
            if self._response is not None:
                # Wyczyszczenie pola wraca do stanu poczatkowego. Stare wyniki
                # bez zapytania nad nimi wygladaja jak wyniki niczego.
                self.cancel_search()
                self._response = None
                self.show_default_empty()
                self._update_pagination()
            return
        if (
            self._incremental_allowed
            and self.current_mode() is SearchMode.EXACT
            and len(stripped) >= INCREMENTAL_MIN_CHARS
        ):
            self._incremental_timer.start()

    def _run_incremental(self) -> None:
        if self.query_edit.text().strip():
            self.run_search()

    def focus_query(self) -> None:
        self.query_edit.setFocus()
        self.query_edit.selectAll()

    def is_searching(self) -> bool:
        """Czy wyszukiwanie jest w toku (przycisk dziala wtedy jako Przerwij)."""
        return self._busy

    def _on_search_clicked(self) -> None:
        if self._busy:
            self.cancel_search()
        else:
            self.run_search()

    def show_default_empty(self) -> None:
        """Stan poczatkowy listy: powitanie bez zrodel, opis trybow ze zrodlami.

        Nowy uzytkownik nie musi odkrywac ekranu Zrodla: pierwsze kroki robi
        przyciskami wprost ze stanu pustego.
        """
        if self._response is not None:
            return
        if not self.context.config.sources:
            self._show_empty(
                i18n.WELCOME_TITLE,
                i18n.WELCOME_TEXT,
                glyph="folder",
                actions=[
                    (i18n.SOURCES_ADD_LOCAL, self.welcome_add_source.emit),
                    (i18n.SOURCES_DEMO, self.welcome_create_demo.emit),
                ],
            )
            return
        self._show_empty(i18n.SEARCH_EMPTY_TITLE, i18n.SEARCH_EMPTY_STATE)

    def run_search(self, *, reset_page: bool = True) -> None:
        self._incremental_timer.stop()
        query = self.query_edit.text().strip()
        if not query:
            self.show_default_empty()
            return
        index = self.context.index
        if index is not None and index.status().indexed_documents == 0:
            if not self.context.config.sources:
                self.show_default_empty()
                return
            self._show_empty(
                i18n.SEARCH_INDEX_EMPTY_TITLE, i18n.SEARCH_INDEX_EMPTY, glyph="database"
            )
            return
        if reset_page:
            self._page = 0

        self.cancel_search()
        request = SearchRequest(
            query=query,
            mode=self.current_mode(),
            filters=self.current_filters(),
            offset=self._page * self._page_size,
            limit=self._page_size,
            max_chunks_per_document=self.context.config.search.max_chunks_per_document,
            order_by=self.current_order(),
        )

        def work(req: SearchRequest, token: CancellationFlag) -> SearchResponse:
            return self.context.require_search().search(req, cancel=token)

        task = SearchTask(work, request)
        task.signals.finished.connect(self._on_results)
        task.signals.failed.connect(self._on_failed)
        task.signals.cancelled.connect(self._on_cancelled)
        self._task = task
        self._token = task.token
        self._set_busy(True)
        # Zarysy kart tylko wtedy, gdy nie ma czego zostawic na ekranie.
        # Przy zawezaniu zapytania stare wyniki zostaja do nadejscia nowych.
        if not self._has_result_cards():
            self._show_skeleton()
        self.status_message.emit(i18n.SEARCH_RUNNING)
        thread_pool().start(task)

    def cancel_search(self) -> None:
        if self._token is not None:
            self._token.cancel()
        self._token = None
        self._task = None
        self._set_busy(False)

    def change_page(self, delta: int) -> None:
        if self._response is None:
            return
        new_page = min(max(0, self._page + delta), self._page_count() - 1)
        if new_page == self._page:
            return
        self._page = new_page
        self.run_search(reset_page=False)

    def _page_count(self) -> int:
        if self._response is None:
            return 1
        return max(1, -(-self._response.total_documents // self._page_size))

    # --- reakcje na wynik -------------------------------------------------

    def _on_results(self, response: object) -> None:
        if not isinstance(response, SearchResponse):
            return
        self._set_busy(False)
        self._response = response
        self._remember_query(response.query_analysis.raw_query)
        self._render(response)

    def _on_failed(self, code: str, message: str) -> None:
        self._set_busy(False)
        self._show_empty(i18n.ERROR_TITLE, f"{message}\n\nKod błędu: {code}")
        self.status_message.emit(message)

    def _on_cancelled(self) -> None:
        self._set_busy(False)
        self.status_message.emit("Wyszukiwanie przerwane.")

    def _set_busy(self, busy: bool) -> None:
        """Przelacza przycisk lupy w Przerwij. Pole zapytania zostaje aktywne:
        Enter w trakcie pracy przerywa biezace wyszukiwanie i zleca nowe,
        a blokada pola zabierala fokus w polowie pisania."""
        self._busy = busy
        icon = accent_icon("stop" if busy else "search", self.palette_colors)
        label = i18n.SEARCH_CANCEL if busy else i18n.SEARCH_BUTTON
        self.search_button.setIcon(icon)
        self.search_button.setToolTip(label)
        self.search_button.setAccessibleName(label)

    def _count_text(self, response: SearchResponse) -> str:
        template = (
            i18n.RESULTS_COUNT_EXACT if response.total_is_exact else i18n.RESULTS_COUNT_APPROX
        )
        return template.format(count=i18n.documents_count(response.total_documents))

    def _render(self, response: SearchResponse) -> None:
        self._clear_results()
        # Liczba wynikow i czas w jednym miejscu, w wierszu tytulu. Wczesniej
        # pasek stanu powtarzal te sama liczbe drugi raz.
        self.header.set_meta(
            f"{self._count_text(response)}, {i18n.RESULTS_TOOK.format(ms=response.took_ms)}"
        )
        # Do banera ida tylko uwagi zalezne od zapytania. Sa ostrzezeniem
        # o niekompletnosci biezacej listy, wiec musza byc widoczne.
        dynamic_notes = [note for note in response.notes if note not in EDUCATION_NOTES]
        self.notes_banner.show_message(" ".join(dynamic_notes), "warning")

        if not response.hits:
            self._show_empty(i18n.SEARCH_NO_RESULTS_TITLE, i18n.SEARCH_NO_RESULTS, keep_meta=True)
            self._update_pagination()
            return

        for hit in response.hits:
            card = ResultCard(
                hit,
                self.palette_colors,
                show_score=self.context.config.ui.show_scores,
                show_match_kind=response.mode is SearchMode.HYBRID,
            )
            card.open_document.connect(self._open_document)
            card.open_location.connect(self._open_location)
            card.copy_link.connect(self._copy_link)
            card.context_requested.connect(self._load_context)
            apply_soft_shadow(card, self.palette_colors)
            self._results_layout.insertWidget(self._results_layout.count() - 1, card)
        self._scroll.verticalScrollBar().setValue(0)
        self._update_pagination()

    def _clear_results(self) -> None:
        while self._results_layout.count() > 1:
            item = self._results_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()

    def _has_result_cards(self) -> bool:
        for position in range(self._results_layout.count()):
            item = self._results_layout.itemAt(position)
            if item is not None and isinstance(item.widget(), ResultCard):
                return True
        return False

    def _show_skeleton(self) -> None:
        """Statyczne zarysy kart w miejscu pustej listy na czas wyszukiwania."""
        self._clear_results()
        for position in range(SKELETON_CARDS):
            self._results_layout.insertWidget(position, SkeletonCard())

    def _show_empty(
        self,
        title: str,
        message: str,
        *,
        glyph: str = "search",
        keep_meta: bool = False,
        actions: list[tuple[str, Callable[[], None]]] | None = None,
    ) -> None:
        self._clear_results()
        if not keep_meta:
            self.header.set_meta("")
            self.notes_banner.hide_message()
        placeholder = EmptyState(
            message,
            title=title,
            glyph=glyph,
            palette=self.palette_colors,
            actions=actions or (),
        )
        # Wspolczynnik rozciagania oddaje stanowi pustemu cala wolna wysokosc,
        # dzieki czemu komunikat jest wysrodkowany, a nie przyklejony do gory.
        self._results_layout.insertWidget(0, placeholder, 1)

    def _update_pagination(self) -> None:
        """Wiersz stron pojawia sie tylko wtedy, gdy jest co przewijac."""
        pages = self._page_count()
        has_results = self._response is not None and self._response.total_documents > 0
        self._pagination.setVisible(has_results and pages > 1)
        if not has_results:
            self.page_label.setText("")
            self.previous_button.setEnabled(False)
            self.next_button.setEnabled(False)
            return
        self.page_label.setText(i18n.PAGINATION_STATUS.format(page=self._page + 1, pages=pages))
        self.previous_button.setEnabled(self._page > 0)
        self.next_button.setEnabled(self._page + 1 < pages)

    # --- akcje na wyniku --------------------------------------------------

    def _open_document(self, hit: object) -> None:
        if not isinstance(hit, DocumentHit):
            return
        ok, message = self.context.open_document(web_url=hit.web_url, local_path=hit.local_path)
        self.status_message.emit("" if ok else message)

    def _open_location(self, hit: object) -> None:
        if not isinstance(hit, DocumentHit):
            return
        ok, message = self.context.open_location(
            parent_url=hit.parent_url, local_path=hit.local_path
        )
        self.status_message.emit("" if ok else message)

    def _load_context(self, hit: object) -> None:
        """Doczytuje sasiednie fragmenty z indeksu i dokleja je na karcie."""
        if not isinstance(hit, DocumentHit) or not hit.chunks:
            return
        card = self.sender()
        if not isinstance(card, ResultCard):
            return
        chunk = hit.chunks[0]

        def work() -> list[tuple[int, str]]:
            repository = self.context.require_index().repository
            rows = repository.chunk_context(hit.doc_id, chunk.ordinal, radius=1)
            return [(int(row["ordinal"]), str(row["text"])) for row in rows]

        def done(result: object, target: ResultCard = card) -> None:
            if not isinstance(result, list):
                return
            previous = " ".join(text for ordinal, text in result if ordinal < chunk.ordinal)
            following = " ".join(text for ordinal, text in result if ordinal > chunk.ordinal)
            try:
                target.show_context(previous, following)
            except RuntimeError:
                # Karta mogla zniknac (nowe wyszukiwanie) zanim odczyt sie skonczyl.
                return

        task = CallableTask(work, label="kontekst trafienia")
        task.signals.finished.connect(done)
        task.signals.failed.connect(lambda _code, message: self.status_message.emit(str(message)))
        thread_pool().start(task)

    def _copy_link(self, hit: object) -> None:
        if not isinstance(hit, DocumentHit):
            return
        target = hit.web_url or hit.local_path or hit.logical_path
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(target)
        self.status_message.emit("Skopiowano odnośnik do schowka.")

    def copy_visible_results(self) -> str:
        """Tekstowa wersja biezacej strony wynikow, uzywana przy kopiowaniu."""
        if self._response is None:
            return ""
        lines: list[str] = [self._count_text(self._response)]
        for position, hit in enumerate(self._response.hits, start=self._page * self._page_size + 1):
            lines.append(f"{position}. {hit.name} ({hit.logical_path})")
            for chunk in hit.chunks:
                lines.append(f"   {strip_highlight(chunk.highlighted)}")
        return "\n".join(lines)

    def keyPressEvent(self, event: object) -> None:
        key = getattr(event, "key", lambda: None)()
        if key == Qt.Key.Key_Escape:
            if self._busy:
                self.cancel_search()
                return
            if self.query_edit.text():
                self.query_edit.clear()
                self.query_edit.setFocus()
                return
        super().keyPressEvent(event)  # type: ignore[arg-type]


__all__ = ["EDUCATION_NOTES", "FILTER_COLUMNS", "NO_DATE", "SearchView"]

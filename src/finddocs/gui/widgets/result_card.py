"""Karta pojedynczego wyniku wyszukiwania.

Karta ma trzy poziomy waznosci i kazdy z nich ma inny stopien pisma:
nazwa dokumentu, potem plakietki i sciezka, na koncu fragmenty tresci.
Plakietki niosa krotki napis, a pelne zdanie jest w podpowiedzi. Wczesniej
cztery pelne zdania w jednym wierszu konkurowaly wzrokowo z trescia fragmentu,
czyli z jedyna rzecza, ktora czytelnik naprawde chce przeczytac.

Koszt przegladania listy to koszt glowny wyszukiwarki, dlatego karta jest
niska: najwyzej dwa fragmenty od razu, reszta po rozwinieciu odnosnikiem.
Tekst prozy jest sklejany z laman wierszy pochodzacych z ekstrakcji, bo te
lamania nie niosa tresci, a potrafia potroic wysokosc fragmentu. Fragmenty
tabel zachowuja uklad wierszy.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable, Sequence

from PySide6.QtCore import QEvent, QObject, QSize, Qt, Signal, SignalInstance
from PySide6.QtGui import QEnterEvent, QFocusEvent, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from finddocs.gui import i18n
from finddocs.gui.theme import (
    ICON_BUTTON_SIZE,
    SPACE_LG,
    SPACE_MD,
    SPACE_SM,
    SPACE_XL,
    SPACE_XS,
    Palette,
    highlight_css,
    muted_icon,
    theme_icon,
)
from finddocs.search.highlight import HIGHLIGHT_CLOSE, HIGHLIGHT_OPEN
from finddocs.types import DocumentHit, TextOrigin

MAX_PATH_CHARS = 110

#: Progi sily dopasowania: od nich zalezy kolor plakietki.
SCORE_HIGH = 0.75
SCORE_MID = 0.4

#: Rozmiar glifu w stanie pustym.
EMPTY_GLYPH_SIZE = 40

#: Liczba fragmentow widocznych bez rozwijania. Wieksza liczba robi karty
#: wyzsze niz okno i zamienia przeglad listy w przewijanie jednej karty.
VISIBLE_CHUNKS = 2

#: Bok glifu rodziny pliku przy tytule karty.
FILE_GLYPH_SIZE = 18

#: Krycie przyciskow akcji karty w spoczynku. Zero: akcje pokazuja sie przy
#: najechaniu i fokusie, a w spoczynku karta jest sama trescia.
ACTIONS_HIDDEN_OPACITY = 0.0

#: Ile znakow sasiedniego fragmentu dokleja podglad kontekstu z kazdej strony.
CONTEXT_NEIGHBOR_CHARS = 350


def snippet_to_html(text: str, palette: Palette) -> str:
    """Zamienia znaczniki trafien na bezpieczny HTML z wyroznieniem."""
    escaped = html.escape(text, quote=False)
    open_tag = f'<span style="{highlight_css(palette)}">'
    escaped = escaped.replace(html.escape(HIGHLIGHT_OPEN), open_tag)
    escaped = escaped.replace(html.escape(HIGHLIGHT_CLOSE), "</span>")
    return escaped.replace("\n", "<br>")


def flatten_snippet(text: str) -> str:
    """Skleja lamania wierszy i wielokrotne odstepy w pojedyncze spacje.

    Ekstrakcja PDF lamie zdania w miejscach lamania na stronie. W fragmencie
    o dlugosci 320 znakow te lamania nie niosa informacji, a kazde z nich
    dodaje wiersz do wysokosci karty. Znaczniki trafien nie zawieraja bialych
    znakow, wiec sklejanie ich nie narusza.
    """
    return re.sub(r"\s+", " ", text).strip()


def shorten_path(value: str, limit: int = MAX_PATH_CHARS) -> str:
    if len(value) <= limit:
        return value
    head = value[: limit // 3]
    tail = value[-(limit - limit // 3 - 3) :]
    return f"{head}...{tail}"


#: Separator okruszkow sciezki na karcie wyniku.
BREADCRUMB_SEPARATOR = " › "

#: Powyzej tylu segmentow srodek sciezki zwija sie do wielokropka.
BREADCRUMB_MAX_SEGMENTS = 6


def breadcrumb_path(logical_path: str, library: str | None, *, exclude_name: str = "") -> str:
    """Sciezka dokumentu jako okruszki: biblioteka i katalogi, bez nazwy pliku.

    Nazwa pliku jest juz w tytule karty, wiec okruszki jej nie powtarzaja.
    Dluga sciezke zwijamy w srodku: poczatek i koniec mowia najwiecej.
    """
    segments = [segment for segment in logical_path.split("/") if segment]
    if segments and exclude_name and segments[-1] == exclude_name:
        segments = segments[:-1]
    if library:
        segments.insert(0, library)
    if len(segments) > BREADCRUMB_MAX_SEGMENTS:
        segments = [*segments[:3], "...", *segments[-2:]]
    return shorten_path(BREADCRUMB_SEPARATOR.join(segments))


def score_role(score: float) -> str:
    """Rola koloru plakietki sily dopasowania."""
    if score >= SCORE_HIGH:
        return "score-high"
    if score >= SCORE_MID:
        return "score-mid"
    return "score-low"


#: Rodziny plikow dla glifu przy tytule karty. Rozszerzenia spoza slownika
#: dostaja kartke bez wnetrza. Zestaw odpowiada rozszerzeniom ekstraktorow.
FILE_GLYPH_FAMILIES: dict[str, frozenset[str]] = {
    "file-table": frozenset({"csv", "tsv", "xls", "xlt", "xlsx", "xlsm", "xltx"}),
    "file-image": frozenset({"png", "jpg", "jpeg", "tif", "tiff", "bmp", "gif", "webp"}),
    "file-mail": frozenset({"msg", "eml", "mht", "mhtml"}),
    "file-text": frozenset(
        {
            "pdf",
            "doc",
            "dot",
            "docx",
            "docm",
            "rtf",
            "txt",
            "log",
            "md",
            "html",
            "htm",
            "xhtml",
            "json",
            "xml",
            "ini",
            "cfg",
            "yaml",
            "yml",
        }
    ),
}


def file_glyph(extension: str) -> str:
    """Nazwa glifu rodziny pliku dla rozszerzenia dokumentu."""
    ext = extension.lower().lstrip(".")
    for glyph, extensions in FILE_GLYPH_FAMILIES.items():
        if ext in extensions:
            return glyph
    return "file-generic"


class ResultCard(QFrame):
    """Wynik na poziomie dokumentu wraz z najlepszymi fragmentami.

    Karta przyjmuje fokus z klawiatury: Tab przechodzi miedzy wynikami, Enter
    otwiera dokument. Dwuklik w dowolnym miejscu karty robi to samo, bo caly
    prostokat wyglada na klikalny i uzytkownicy tak go traktuja.
    """

    open_document = Signal(object)
    open_location = Signal(object)
    copy_link = Signal(object)
    #: Prosba o sasiednie fragmenty z indeksu. Odczyt robi widok wyszukiwania,
    #: bo karta nie ma dostepu do repozytorium i nie moze blokowac watku GUI.
    context_requested = Signal(object)

    def __init__(
        self,
        hit: DocumentHit,
        palette: Palette,
        *,
        show_score: bool = True,
        show_match_kind: bool = True,
    ) -> None:
        super().__init__()
        self.hit = hit
        self._show_match_kind = show_match_kind
        self._action_effects: list[QGraphicsOpacityEffect] = []
        self.setObjectName("ResultCard")
        self.setFrameShape(QFrame.Shape.NoFrame)
        # Pion musi byc ,,Preferred'', nie ,,Minimum''. Bez znacznika kurczenia
        # Qt liczy minimalna wysokosc karty jako jej ``sizeHint``, a ten dla
        # etykiet z zawijaniem powstaje przy zgadywanej szerokosci, wiec wychodzi
        # wyzszy niz karta naprawde potrzebuje. Obszar wynikow sumowal te zawyzone
        # wysokosci i pozwalal przewijac o kilkaset pikseli za ostatnia karte.
        # Rzeczywista wysokosc i tak bierze sie z ``heightForWidth``.
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(hit.name)
        self.setAccessibleDescription(hit.logical_path)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_LG, SPACE_LG - 2, SPACE_LG, SPACE_LG - 2)
        layout.setSpacing(SPACE_SM)

        layout.addLayout(self._build_header(hit, palette))

        location = QLabel(breadcrumb_path(hit.logical_path, hit.library, exclude_name=hit.name))
        location.setObjectName("ResultPath")
        location.setWordWrap(True)
        location.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        location.setVisible(bool(location.text()))
        self.location_label = location
        layout.addWidget(location)

        layout.addLayout(self._build_badges(hit, show_score))

        self._palette = palette
        self._hidden_snippets: list[QLabel] = []
        self._first_snippet: QLabel | None = None
        self._first_snippet_html = ""
        for position, chunk in enumerate(hit.chunks):
            snippet = QLabel()
            snippet.setObjectName("Snippet")
            snippet.setTextFormat(Qt.TextFormat.RichText)
            # Fragment tabeli zachowuje uklad wierszy, proza jest sklejana.
            text = chunk.highlighted
            if getattr(chunk, "sheet", None) is None:
                text = flatten_snippet(text)
            content = self._chunk_prefix(chunk, palette) + snippet_to_html(text, palette)
            snippet.setText(content)
            snippet.setWordWrap(True)
            snippet.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            if position == 0:
                self._first_snippet = snippet
                self._first_snippet_html = content
            if position >= VISIBLE_CHUNKS:
                snippet.setVisible(False)
                self._hidden_snippets.append(snippet)
            layout.addWidget(snippet)

        self.expand_button: QPushButton | None = None
        self.context_button: QPushButton | None = None
        self.more_hint: QLabel | None = None
        extra = hit.total_matching_chunks - len(hit.chunks)
        if extra > 0:
            more = QLabel(i18n.RESULT_MORE_CHUNKS.format(count=hit.total_matching_chunks))
            more.setObjectName("Hint")
            # Przed rozwinieciem informacje o liczbie fragmentow niesie odnosnik,
            # wiec podpis pod spodem bylby druga wersja tej samej liczby.
            more.setVisible(not self._hidden_snippets)
            self.more_hint = more

        footer = QHBoxLayout()
        footer.setSpacing(SPACE_MD)
        if hit.chunks:
            context = QPushButton(i18n.RESULT_CONTEXT)
            context.setObjectName("Link")
            context.setToolTip(i18n.RESULT_CONTEXT_HINT)
            context.clicked.connect(self._request_context)
            self.context_button = context
            footer.addWidget(context)
        if self._hidden_snippets:
            button = QPushButton(i18n.RESULT_SHOW_MORE.format(count=len(self._hidden_snippets)))
            button.setObjectName("Link")
            button.setToolTip(i18n.RESULT_SHOW_MORE_HINT)
            button.clicked.connect(self._show_hidden_snippets)
            self.expand_button = button
            footer.addWidget(button)
        footer.addStretch(1)
        if footer.count() > 1:
            layout.addLayout(footer)
        if self.more_hint is not None:
            layout.addWidget(self.more_hint)

    # --- czesci skladowe --------------------------------------------------

    def _build_header(self, hit: DocumentHit, palette: Palette) -> QHBoxLayout:
        """Nazwa pliku jako odnosnik oraz akcje dokumentu przy prawej krawedzi."""
        row = QHBoxLayout()
        row.setSpacing(SPACE_XS)

        # Glif rodziny pliku daje liscie kotwice wzrokowa: rodzaj dokumentu
        # widac przed przeczytaniem nazwy. Kolor wyciszony, zeby nie konkurowal
        # z tytulem.
        glyph = QLabel()
        glyph.setObjectName("FileGlyph")
        glyph.setPixmap(
            muted_icon(file_glyph(hit.extension), palette).pixmap(
                QSize(FILE_GLYPH_SIZE, FILE_GLYPH_SIZE)
            )
        )
        row.addWidget(glyph, 0, Qt.AlignmentFlag.AlignTop)

        title = QLabel(f'<a href="open" style="text-decoration: none;">{html.escape(hit.name)}</a>')
        title.setObjectName("ResultTitle")
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setWordWrap(True)
        title.setToolTip(i18n.RESULT_OPEN_HINT)
        title.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByKeyboard
        )
        title.linkActivated.connect(lambda _link: self.open_document.emit(self.hit))
        self.title_label = title
        row.addWidget(title, stretch=1)

        self.location_button = self._action_button(
            "folder", i18n.RESULT_OPEN_LOCATION, palette, self.open_location
        )
        row.addWidget(self.location_button, 0, Qt.AlignmentFlag.AlignTop)

        self.copy_button = self._action_button(
            "copy", i18n.RESULT_COPY_LINK, palette, self.copy_link
        )
        row.addWidget(self.copy_button, 0, Qt.AlignmentFlag.AlignTop)
        return row

    def _action_button(
        self, icon_name: str, label: str, palette: Palette, signal: SignalInstance
    ) -> QPushButton:
        """Kwadratowy przycisk ikonowy: napis wedruje do podpowiedzi.

        Akcje pokazuja sie przy najechaniu na karte i przy fokusie. Zamiast
        chowania kontrolek zmieniamy krycie: uklad karty nie drga, przyciski
        caly czas zajmuja swoje miejsce i pozostaja w kolejnosci Tab.
        """
        button = QPushButton()
        button.setObjectName("IconButton")
        button.setIcon(theme_icon(icon_name, palette))
        button.setIconSize(QSize(16, 16))
        button.setFixedSize(QSize(ICON_BUTTON_SIZE, ICON_BUTTON_SIZE))
        button.setToolTip(label)
        button.setAccessibleName(label)
        button.clicked.connect(lambda: signal.emit(self.hit))
        effect = QGraphicsOpacityEffect(button)
        effect.setOpacity(ACTIONS_HIDDEN_OPACITY)
        button.setGraphicsEffect(effect)
        button.installEventFilter(self)
        self._action_effects.append(effect)
        return button

    def _set_actions_revealed(self, revealed: bool) -> None:
        for effect in self._action_effects:
            effect.setOpacity(1.0 if revealed else ACTIONS_HIDDEN_OPACITY)

    def _should_stay_revealed(self) -> bool:
        return self.underMouse() or self.hasFocus()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        # Fokus klawiatury na przycisku akcji tez odslania akcje.
        if event.type() is QEvent.Type.FocusIn:
            self._set_actions_revealed(True)
        elif event.type() is QEvent.Type.FocusOut and not self._should_stay_revealed():
            self._set_actions_revealed(False)
        return False

    def enterEvent(self, event: QEnterEvent) -> None:
        self._set_actions_revealed(True)
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        if not self.hasFocus():
            self._set_actions_revealed(False)
        super().leaveEvent(event)

    def focusInEvent(self, event: QFocusEvent) -> None:
        self._set_actions_revealed(True)
        super().focusInEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        if not self._should_stay_revealed():
            self._set_actions_revealed(False)
        super().focusOutEvent(event)

    def _build_badges(self, hit: DocumentHit, show_score: bool) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(SPACE_SM)

        def badge(text: str, role: str, tooltip: str = "") -> QLabel:
            label = QLabel(text)
            label.setObjectName("Badge")
            label.setProperty("badgeRole", role)
            if tooltip:
                label.setToolTip(tooltip)
                label.setAccessibleDescription(tooltip)
            row.addWidget(label)
            return label

        # Rodzaj dopasowania ma sens tylko tam, gdzie rozni sie miedzy wynikami,
        # czyli w trybie hybrydowym. W pozostalych trybach powtarzalby nazwe
        # trybu na kazdej karcie.
        if self._show_match_kind:
            badge(
                i18n.MATCH_LABELS.get(hit.match_kind, hit.match_kind.value),
                "match",
                i18n.BADGE_MATCH_TOOLTIP,
            )
        if hit.extension:
            badge(hit.extension.lstrip(".").upper(), "type", i18n.BADGE_TYPE_TOOLTIP)
        if hit.modified_at:
            badge(
                hit.modified_at.strftime("%Y-%m-%d"),
                "date",
                i18n.BADGE_MODIFIED_TOOLTIP,
            )
        if hit.author:
            badge(hit.author, "author", i18n.BADGE_AUTHOR_TOOLTIP)
        if hit.used_ocr:
            text = i18n.RESULT_OCR_BADGE
            if hit.ocr_confidence is not None:
                text = f"{text} {hit.ocr_confidence * 100:.0f}%"
            badge(text, "ocr", i18n.BADGE_OCR_TOOLTIP)
        if show_score:
            badge(
                i18n.RESULT_SCORE_SHORT.format(value=f"{hit.score * 100:.0f}%"),
                score_role(hit.score),
                i18n.RESULT_SCORE_TOOLTIP,
            )
        row.addStretch(1)
        return row

    def _chunk_prefix(self, chunk: object, palette: Palette) -> str:
        """Polozenie fragmentu jako podbarwiona plakietka przed trescia.

        Nawiasy kwadratowe z wyszarzonym tekstem wygladaly jak pozostalosc
        debugowania. Podbarwienie odroznia metadane od tresci bez nawiasow.
        """
        parts: list[str] = []
        page = getattr(chunk, "page", None)
        sheet = getattr(chunk, "sheet", None)
        row_start = getattr(chunk, "row_start", None)
        origin = getattr(chunk, "origin", TextOrigin.NATIVE)
        if page:
            parts.append(f"strona {page}")
        if sheet:
            parts.append(f"arkusz {sheet}")
        if row_start:
            parts.append(f"wiersz {row_start}")
        if origin is TextOrigin.OCR:
            parts.append("tekst z OCR")
        if not parts:
            return ""
        return (
            f'<span style="background-color:{palette.border}; color:{palette.text_muted};">'
            f"&nbsp;{', '.join(parts)}&nbsp;</span> "
        )

    def _show_hidden_snippets(self) -> None:
        """Pokazuje zwiniete fragmenty i chowa odnosnik rozwijania."""
        for snippet in self._hidden_snippets:
            snippet.setVisible(True)
        self._hidden_snippets = []
        if self.expand_button is not None:
            self.expand_button.setVisible(False)
        if self.more_hint is not None:
            self.more_hint.setVisible(True)

    def _request_context(self) -> None:
        if self.context_button is not None:
            self.context_button.setEnabled(False)
        self.context_requested.emit(self.hit)

    def show_context(self, previous: str, following: str) -> None:
        """Dokleja sasiednie fragmenty wokol pierwszego trafienia.

        Sasiedzi sa wyciszeni kolorem, a trafienie zachowuje wyroznienie.
        Podglad odpowiada na pytanie ,,o czym jest to miejsce dokumentu''
        bez otwierania pliku.
        """
        if self._first_snippet is None:
            return
        muted = self._palette.text_muted
        parts: list[str] = []
        if previous:
            trimmed = flatten_snippet(previous)
            if len(trimmed) > CONTEXT_NEIGHBOR_CHARS:
                trimmed = "..." + trimmed[-CONTEXT_NEIGHBOR_CHARS:]
            parts.append(f'<span style="color:{muted}">{html.escape(trimmed)}</span>')
        parts.append(self._first_snippet_html)
        if following:
            trimmed = flatten_snippet(following)
            if len(trimmed) > CONTEXT_NEIGHBOR_CHARS:
                trimmed = trimmed[:CONTEXT_NEIGHBOR_CHARS] + "..."
            parts.append(f'<span style="color:{muted}">{html.escape(trimmed)}</span>')
        self._first_snippet.setText("<br>".join(parts))
        if self.context_button is not None:
            self.context_button.setVisible(False)

    # --- obsluga klawiatury i myszki --------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.open_document.emit(self.hit)
            event.accept()
            return
        super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        self.open_document.emit(self.hit)
        event.accept()


class EmptyState(QWidget):
    """Komunikat zastepczy: glif, naglowek i wyjasnienie, wysrodkowane.

    Stan pusty zajmuje cala wolna przestrzen listy wynikow. Komunikat przyklejony
    do gornej krawedzi duzego pustego prostokata wyglada jak bledny render.
    Opcjonalne akcje pozwalaja zaczac prace z tego miejsca (pierwsze
    uruchomienie), zamiast odsylac opisowo na inny ekran.
    """

    def __init__(
        self,
        message: str,
        *,
        title: str = "",
        glyph: str = "search",
        palette: Palette | None = None,
        actions: Sequence[tuple[str, Callable[[], None]]] = (),
    ) -> None:
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_XL, SPACE_XL, SPACE_XL, SPACE_XL)
        layout.setSpacing(SPACE_SM)
        layout.addStretch(1)

        self._glyph = QLabel()
        self._glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._glyph.setPixmap(
            muted_icon(glyph, palette).pixmap(QSize(EMPTY_GLYPH_SIZE, EMPTY_GLYPH_SIZE))
        )
        layout.addWidget(self._glyph)
        layout.addSpacing(SPACE_XS)

        self._title = QLabel(title)
        self._title.setObjectName("SectionTitle")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Kolejnosc jak w PageHeader: widocznosc dopiero po wstawieniu do ukladu.
        layout.addWidget(self._title)
        self._title.setVisible(bool(title))

        self._label = QLabel(message)
        self._label.setObjectName("Muted")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setWordWrap(True)
        layout.addWidget(self._label)

        self.action_buttons: list[QPushButton] = []
        if actions:
            layout.addSpacing(SPACE_SM)
            buttons = QHBoxLayout()
            buttons.setSpacing(SPACE_SM)
            buttons.addStretch(1)
            for position, (label, callback) in enumerate(actions):
                button = QPushButton(label)
                if position == 0:
                    button.setObjectName("Primary")
                button.clicked.connect(callback)
                buttons.addWidget(button)
                self.action_buttons.append(button)
            buttons.addStretch(1)
            layout.addLayout(buttons)

        layout.addSpacing(SPACE_MD)
        layout.addStretch(1)

    def message(self) -> str:
        """Tresc wyjasnienia, bez naglowka."""
        return self._label.text()

    def title(self) -> str:
        return self._title.text()

    def set_message(self, message: str) -> None:
        """Podmienia tresc komunikatu bez tworzenia nowej kontrolki."""
        self._label.setText(message)


__all__ = [
    "ACTIONS_HIDDEN_OPACITY",
    "BREADCRUMB_MAX_SEGMENTS",
    "BREADCRUMB_SEPARATOR",
    "EMPTY_GLYPH_SIZE",
    "FILE_GLYPH_FAMILIES",
    "FILE_GLYPH_SIZE",
    "MAX_PATH_CHARS",
    "SCORE_HIGH",
    "SCORE_MID",
    "VISIBLE_CHUNKS",
    "EmptyState",
    "ResultCard",
    "breadcrumb_path",
    "file_glyph",
    "flatten_snippet",
    "score_role",
    "shorten_path",
    "snippet_to_html",
]

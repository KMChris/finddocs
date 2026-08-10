"""Karta pojedynczego wyniku wyszukiwania.

Karta ma trzy poziomy waznosci i kazdy z nich ma inny stopien pisma:
nazwa dokumentu, potem plakietki i sciezka, na koncu fragmenty tresci.
Plakietki niosa krotki napis, a pelne zdanie jest w podpowiedzi. Wczesniej
cztery pelne zdania w jednym wierszu konkurowaly wzrokowo z trescia fragmentu,
czyli z jedyna rzecza, ktora czytelnik naprawde chce przeczytac.
"""

from __future__ import annotations

import html

from PySide6.QtCore import QSize, Qt, Signal, SignalInstance
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
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


def snippet_to_html(text: str, palette: Palette) -> str:
    """Zamienia znaczniki trafien na bezpieczny HTML z wyroznieniem."""
    escaped = html.escape(text, quote=False)
    open_tag = f'<span style="{highlight_css(palette)}">'
    escaped = escaped.replace(html.escape(HIGHLIGHT_OPEN), open_tag)
    escaped = escaped.replace(html.escape(HIGHLIGHT_CLOSE), "</span>")
    return escaped.replace("\n", "<br>")


def shorten_path(value: str, limit: int = MAX_PATH_CHARS) -> str:
    if len(value) <= limit:
        return value
    head = value[: limit // 3]
    tail = value[-(limit - limit // 3 - 3) :]
    return f"{head}...{tail}"


def score_role(score: float) -> str:
    """Rola koloru plakietki sily dopasowania."""
    if score >= SCORE_HIGH:
        return "score-high"
    if score >= SCORE_MID:
        return "score-mid"
    return "score-low"


class ResultCard(QFrame):
    """Wynik na poziomie dokumentu wraz z najlepszymi fragmentami.

    Karta przyjmuje fokus z klawiatury: Tab przechodzi miedzy wynikami, Enter
    otwiera dokument. Dwuklik w dowolnym miejscu karty robi to samo, bo caly
    prostokat wyglada na klikalny i uzytkownicy tak go traktuja.
    """

    open_document = Signal(object)
    open_location = Signal(object)
    copy_link = Signal(object)

    def __init__(self, hit: DocumentHit, palette: Palette, *, show_score: bool = True) -> None:
        super().__init__()
        self.hit = hit
        self.setObjectName("ResultCard")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(hit.name)
        self.setAccessibleDescription(hit.logical_path)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_LG, SPACE_LG - 2, SPACE_LG, SPACE_LG - 2)
        layout.setSpacing(SPACE_SM)

        layout.addLayout(self._build_header(hit, palette))

        location_parts = [shorten_path(hit.logical_path)]
        if hit.library:
            location_parts.insert(0, hit.library)
        location = QLabel(" / ".join(location_parts))
        location.setObjectName("ResultPath")
        location.setWordWrap(True)
        location.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(location)

        layout.addLayout(self._build_badges(hit, show_score))

        for chunk in hit.chunks:
            snippet = QLabel()
            snippet.setObjectName("Snippet")
            snippet.setTextFormat(Qt.TextFormat.RichText)
            prefix = self._chunk_prefix(chunk)
            snippet.setText(prefix + snippet_to_html(chunk.highlighted, palette))
            snippet.setWordWrap(True)
            snippet.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(snippet)

        extra = hit.total_matching_chunks - len(hit.chunks)
        if extra > 0:
            more = QLabel(i18n.RESULT_MORE_CHUNKS.format(count=hit.total_matching_chunks))
            more.setObjectName("Hint")
            layout.addWidget(more)

    # --- czesci skladowe --------------------------------------------------

    def _build_header(self, hit: DocumentHit, palette: Palette) -> QHBoxLayout:
        """Nazwa pliku jako odnosnik oraz akcje dokumentu przy prawej krawedzi."""
        row = QHBoxLayout()
        row.setSpacing(SPACE_XS)

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
        """Kwadratowy przycisk ikonowy: napis wedruje do podpowiedzi."""
        button = QPushButton()
        button.setObjectName("IconButton")
        button.setIcon(theme_icon(icon_name, palette))
        button.setIconSize(QSize(16, 16))
        button.setFixedSize(QSize(ICON_BUTTON_SIZE, ICON_BUTTON_SIZE))
        button.setToolTip(label)
        button.setAccessibleName(label)
        button.clicked.connect(lambda: signal.emit(self.hit))
        return button

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

        badge(i18n.MATCH_LABELS.get(hit.match_kind, hit.match_kind.value), "match")
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

    def _chunk_prefix(self, chunk: object) -> str:
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
        return f'<span style="opacity:0.6">[{", ".join(parts)}]</span> '

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
    """

    def __init__(self, message: str, *, title: str = "", glyph: str = "search") -> None:
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_XL, SPACE_XL, SPACE_XL, SPACE_XL)
        layout.setSpacing(SPACE_SM)
        layout.addStretch(1)

        self._glyph = QLabel()
        self._glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._glyph.setPixmap(muted_icon(glyph).pixmap(QSize(EMPTY_GLYPH_SIZE, EMPTY_GLYPH_SIZE)))
        layout.addWidget(self._glyph)
        layout.addSpacing(SPACE_XS)

        self._title = QLabel(title)
        self._title.setObjectName("SectionTitle")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setVisible(bool(title))
        layout.addWidget(self._title)

        self._label = QLabel(message)
        self._label.setObjectName("Muted")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setWordWrap(True)
        layout.addWidget(self._label)
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
    "EMPTY_GLYPH_SIZE",
    "MAX_PATH_CHARS",
    "SCORE_HIGH",
    "SCORE_MID",
    "EmptyState",
    "ResultCard",
    "score_role",
    "shorten_path",
    "snippet_to_html",
]

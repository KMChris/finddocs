"""Karta pojedynczego wyniku wyszukiwania."""

from __future__ import annotations

import html

from PySide6.QtCore import QSize, Qt, Signal, SignalInstance
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
from finddocs.gui.theme import Palette, highlight_css, theme_icon
from finddocs.search.highlight import HIGHLIGHT_CLOSE, HIGHLIGHT_OPEN
from finddocs.types import DocumentHit, TextOrigin

MAX_PATH_CHARS = 110

#: Progi sily dopasowania: od nich zalezy kolor plakietki.
SCORE_HIGH = 0.75
SCORE_MID = 0.4

#: Bok kwadratowego przycisku ikonowego w wierszu nazwy pliku.
ICON_BUTTON_SIZE = 30


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
    """Wynik na poziomie dokumentu wraz z najlepszymi fragmentami."""

    open_document = Signal(object)
    open_location = Signal(object)
    copy_link = Signal(object)

    def __init__(self, hit: DocumentHit, palette: Palette, *, show_score: bool = True) -> None:
        super().__init__()
        self.hit = hit
        self.setObjectName("ResultCard")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

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
            more.setObjectName("Muted")
            layout.addWidget(more)

    # --- czesci skladowe --------------------------------------------------

    def _build_header(self, hit: DocumentHit, palette: Palette) -> QHBoxLayout:
        """Nazwa pliku jako odnosnik oraz akcje dokumentu przy prawej krawedzi."""
        row = QHBoxLayout()
        row.setSpacing(4)

        title = QLabel(f'<a href="open" style="text-decoration: none;">{html.escape(hit.name)}</a>')
        title.setObjectName("ResultTitle")
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setWordWrap(True)
        title.setToolTip(i18n.RESULT_OPEN)
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
        row.setSpacing(8)

        def badge(text: str, role: str) -> QLabel:
            label = QLabel(text)
            label.setObjectName("Badge")
            label.setProperty("badgeRole", role)
            row.addWidget(label)
            return label

        badge(i18n.MATCH_LABELS.get(hit.match_kind, hit.match_kind.value), "match")
        if hit.extension:
            badge(hit.extension.lstrip(".").upper(), "type")
        if hit.modified_at:
            badge(i18n.RESULT_MODIFIED.format(value=hit.modified_at.strftime("%Y-%m-%d")), "date")
        if hit.author:
            badge(i18n.RESULT_AUTHOR.format(value=hit.author), "author")
        if hit.used_ocr:
            text = i18n.RESULT_OCR_BADGE
            if hit.ocr_confidence is not None:
                text = f"{text} {hit.ocr_confidence * 100:.0f}%"
            badge(text, "ocr")
        if show_score:
            score = badge(
                i18n.RESULT_SCORE.format(value=f"{hit.score * 100:.0f}%"), score_role(hit.score)
            )
            score.setToolTip(i18n.RESULT_SCORE_TOOLTIP)
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


class EmptyState(QWidget):
    """Prosty komunikat pokazywany, gdy nie ma czego wyswietlic."""

    def __init__(self, message: str) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 48, 24, 48)
        self._label = QLabel(message)
        self._label.setObjectName("Muted")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setWordWrap(True)
        layout.addWidget(self._label)
        layout.addStretch(1)

    def set_message(self, message: str) -> None:
        """Podmienia tresc komunikatu bez tworzenia nowej kontrolki."""
        self._label.setText(message)


__all__ = [
    "ICON_BUTTON_SIZE",
    "MAX_PATH_CHARS",
    "SCORE_HIGH",
    "SCORE_MID",
    "EmptyState",
    "ResultCard",
    "score_role",
    "shorten_path",
    "snippet_to_html",
]

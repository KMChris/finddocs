"""Karta pojedynczego wyniku wyszukiwania."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
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
from finddocs.gui.theme import Palette, highlight_css
from finddocs.search.highlight import HIGHLIGHT_CLOSE, HIGHLIGHT_OPEN
from finddocs.types import DocumentHit, TextOrigin

MAX_PATH_CHARS = 110


def snippet_to_html(text: str, palette: Palette) -> str:
    """Zamienia znaczniki trafien na bezpieczny HTML z wyroznieniem."""
    import html

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
        layout.setSpacing(8)

        title = QLabel(hit.name)
        title.setObjectName("ResultTitle")
        title.setWordWrap(True)
        title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(title)

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

        layout.addLayout(self._build_actions())

    # --- czesci skladowe --------------------------------------------------

    def _build_badges(self, hit: DocumentHit, show_score: bool) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)

        def badge(text: str, name: str = "Badge") -> None:
            label = QLabel(text)
            label.setObjectName(name)
            row.addWidget(label)

        badge(i18n.MATCH_LABELS.get(hit.match_kind, hit.match_kind.value))
        if hit.extension:
            badge(hit.extension.lstrip(".").upper())
        if hit.modified_at:
            badge(i18n.RESULT_MODIFIED.format(value=hit.modified_at.strftime("%Y-%m-%d")))
        if hit.author:
            badge(i18n.RESULT_AUTHOR.format(value=hit.author))
        if hit.used_ocr:
            text = i18n.RESULT_OCR_BADGE
            if hit.ocr_confidence is not None:
                text = f"{text} {hit.ocr_confidence * 100:.0f}%"
            badge(text, "BadgeOcr")
        if show_score:
            score = QLabel(i18n.RESULT_SCORE.format(value=f"{hit.score * 100:.0f}%"))
            score.setObjectName("Badge")
            score.setToolTip(i18n.RESULT_SCORE_TOOLTIP)
            row.addWidget(score)
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

    def _build_actions(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        open_button = QPushButton(i18n.RESULT_OPEN)
        open_button.setObjectName("Primary")
        open_button.clicked.connect(lambda: self.open_document.emit(self.hit))
        row.addWidget(open_button)

        location_button = QPushButton(i18n.RESULT_OPEN_LOCATION)
        location_button.clicked.connect(lambda: self.open_location.emit(self.hit))
        row.addWidget(location_button)

        copy_button = QPushButton(i18n.RESULT_COPY_LINK)
        copy_button.clicked.connect(lambda: self.copy_link.emit(self.hit))
        row.addWidget(copy_button)

        row.addStretch(1)
        return row


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


__all__ = ["MAX_PATH_CHARS", "EmptyState", "ResultCard", "shorten_path", "snippet_to_html"]

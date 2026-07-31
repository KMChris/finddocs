"""Ekran wyszukiwania."""

from __future__ import annotations

import datetime as _dt

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from finddocs.gui import i18n
from finddocs.gui.context import AppContext
from finddocs.gui.theme import Palette
from finddocs.gui.widgets.result_card import EmptyState, ResultCard
from finddocs.gui.workers import CancellationFlag, SearchTask, thread_pool
from finddocs.logging_setup import get_logger
from finddocs.search.highlight import strip_highlight
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


class SearchView(QWidget):
    """Pole zapytania, tryby, filtry i lista wynikow."""

    status_message = Signal(str)

    def __init__(self, context: AppContext, palette: Palette) -> None:
        super().__init__()
        self.context = context
        self.palette_colors = palette
        self._task: SearchTask | None = None
        self._token: CancellationFlag | None = None
        self._response: SearchResponse | None = None
        self._page = 0
        self._page_size = context.config.search.page_size

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(12)

        title = QLabel(i18n.NAV_SEARCH)
        title.setObjectName("PageTitle")
        root.addWidget(title)

        root.addWidget(self._build_query_row())
        root.addWidget(self._build_mode_row())
        self._filters_panel = self._build_filters()
        root.addWidget(self._filters_panel)
        self._filters_panel.setVisible(False)

        self._summary = QLabel("")
        self._summary.setObjectName("Muted")
        self._summary.setWordWrap(True)
        root.addWidget(self._summary)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._results_host = QWidget()
        self._results_layout = QVBoxLayout(self._results_host)
        self._results_layout.setContentsMargins(0, 0, 8, 0)
        self._results_layout.setSpacing(10)
        self._results_layout.addStretch(1)
        self._scroll.setWidget(self._results_host)
        root.addWidget(self._scroll, stretch=1)

        root.addLayout(self._build_pagination())
        self._show_empty(i18n.SEARCH_EMPTY_STATE)

    # --- budowa interfejsu ------------------------------------------------

    def _build_query_row(self) -> QWidget:
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self.query_edit = QLineEdit()
        self.query_edit.setObjectName("SearchBox")
        self.query_edit.setPlaceholderText(i18n.SEARCH_PLACEHOLDER)
        self.query_edit.setClearButtonEnabled(True)
        self.query_edit.returnPressed.connect(self.run_search)
        row.addWidget(self.query_edit, stretch=1)

        self.search_button = QPushButton(i18n.SEARCH_BUTTON)
        self.search_button.setObjectName("Primary")
        self.search_button.clicked.connect(self.run_search)
        row.addWidget(self.search_button)

        self.cancel_button = QPushButton(i18n.SEARCH_CANCEL)
        self.cancel_button.clicked.connect(self.cancel_search)
        self.cancel_button.setEnabled(False)
        row.addWidget(self.cancel_button)
        return container

    def _build_mode_row(self) -> QWidget:
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        default_mode = SearchMode(self.context.config.search.default_mode)
        for index, mode in enumerate(SearchMode):
            button = QPushButton(i18n.MODE_LABELS[mode])
            button.setObjectName("ModeButton")
            button.setCheckable(True)
            button.setToolTip(i18n.MODE_HINTS[mode])
            button.setChecked(mode is default_mode)
            self.mode_group.addButton(button, index)
            row.addWidget(button)
        self.mode_group.idClicked.connect(lambda _id: self._update_mode_hint())

        self.mode_hint = QLabel(i18n.MODE_HINTS[default_mode])
        self.mode_hint.setObjectName("Hint")
        row.addWidget(self.mode_hint)
        row.addStretch(1)

        self.filters_toggle = QPushButton(i18n.SEARCH_FILTERS)
        self.filters_toggle.setCheckable(True)
        self.filters_toggle.toggled.connect(self._toggle_filters)
        row.addWidget(self.filters_toggle)
        return container

    def _build_filters(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Card")
        grid = QGridLayout(panel)
        grid.setContentsMargins(16, 14, 16, 14)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)

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

        self.filter_path = QLineEdit()
        self.filter_path.setPlaceholderText("np. transakcje/klientA")

        self.filter_date_from = QDateEdit()
        self.filter_date_to = QDateEdit()
        for editor in (self.filter_date_from, self.filter_date_to):
            editor.setCalendarPopup(True)
            editor.setDisplayFormat("dd.MM.yyyy")
            editor.setSpecialValueText(FILTER_ANY)
            editor.setMinimumDate(QDate(1900, 1, 1))
            editor.setDate(QDate(1900, 1, 1))

        self.filter_ocr = QCheckBox(i18n.FILTER_OCR)

        widgets = [
            (i18n.FILTER_EXTENSION, self.filter_extension),
            (i18n.FILTER_SOURCE, self.filter_source),
            (i18n.FILTER_LIBRARY, self.filter_library),
            (i18n.FILTER_AUTHOR, self.filter_author),
            (i18n.FILTER_PATH, self.filter_path),
            (i18n.FILTER_DATE_FROM, self.filter_date_from),
            (i18n.FILTER_DATE_TO, self.filter_date_to),
        ]
        for index, (label_text, widget) in enumerate(widgets):
            label = QLabel(label_text)
            label.setObjectName("Muted")
            grid.addWidget(label, index // 4 * 2, index % 4)
            grid.addWidget(widget, index // 4 * 2 + 1, index % 4)

        grid.addWidget(self.filter_ocr, 3, 3)
        clear = QPushButton(i18n.SEARCH_FILTERS_CLEAR)
        clear.clicked.connect(self.clear_filters)
        grid.addWidget(clear, 4, 0)
        return panel

    def _build_pagination(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        self.previous_button = QPushButton(i18n.PAGINATION_PREVIOUS)
        self.previous_button.clicked.connect(lambda: self.change_page(-1))
        self.next_button = QPushButton(i18n.PAGINATION_NEXT)
        self.next_button.clicked.connect(lambda: self.change_page(1))
        self.page_label = QLabel("")
        self.page_label.setObjectName("Muted")
        row.addStretch(1)
        row.addWidget(self.previous_button)
        row.addWidget(self.page_label)
        row.addWidget(self.next_button)
        row.addStretch(1)
        self._update_pagination()
        return row

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
            if qdate == QDate(1900, 1, 1):
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

    def clear_filters(self) -> None:
        for combo in (
            self.filter_extension,
            self.filter_source,
            self.filter_library,
            self.filter_author,
        ):
            combo.setCurrentIndex(0)
        self.filter_path.clear()
        self.filter_date_from.setDate(QDate(1900, 1, 1))
        self.filter_date_to.setDate(QDate(1900, 1, 1))
        self.filter_ocr.setChecked(False)

    def _toggle_filters(self, visible: bool) -> None:
        self._filters_panel.setVisible(visible)
        if visible:
            self.refresh_filter_values()

    def _update_mode_hint(self) -> None:
        self.mode_hint.setText(i18n.MODE_HINTS[self.current_mode()])

    # --- wyszukiwanie -----------------------------------------------------

    def focus_query(self) -> None:
        self.query_edit.setFocus()
        self.query_edit.selectAll()

    def run_search(self, *, reset_page: bool = True) -> None:
        query = self.query_edit.text().strip()
        if not query:
            self._show_empty(i18n.SEARCH_EMPTY_STATE)
            return
        index = self.context.index
        if index is not None and index.status().indexed_documents == 0:
            self._show_empty(i18n.SEARCH_INDEX_EMPTY)
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
        pages = max(1, -(-self._response.total_documents // self._page_size))
        new_page = min(max(0, self._page + delta), pages - 1)
        if new_page == self._page:
            return
        self._page = new_page
        self.run_search(reset_page=False)

    # --- reakcje na wynik -------------------------------------------------

    def _on_results(self, response: object) -> None:
        if not isinstance(response, SearchResponse):
            return
        self._set_busy(False)
        self._response = response
        self._render(response)
        self.status_message.emit(
            f"{self._count_text(response)}, {i18n.RESULTS_TOOK.format(ms=response.took_ms)}"
        )

    def _on_failed(self, code: str, message: str) -> None:
        self._set_busy(False)
        self._show_empty(f"{message}\n\nKod bledu: {code}")
        self.status_message.emit(message)

    def _on_cancelled(self) -> None:
        self._set_busy(False)
        self.status_message.emit("Wyszukiwanie przerwane.")

    def _set_busy(self, busy: bool) -> None:
        self.search_button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        self.query_edit.setEnabled(not busy)

    def _count_text(self, response: SearchResponse) -> str:
        template = (
            i18n.RESULTS_COUNT_EXACT if response.total_is_exact else i18n.RESULTS_COUNT_APPROX
        )
        return template.format(count=response.total_documents)

    def _render(self, response: SearchResponse) -> None:
        self._clear_results()
        notes = list(response.notes)
        summary = self._count_text(response)
        if notes:
            summary = f"{summary}. " + " ".join(notes)
        self._summary.setText(summary)

        if not response.hits:
            self._show_empty(i18n.SEARCH_NO_RESULTS)
            self._update_pagination()
            return

        for hit in response.hits:
            card = ResultCard(
                hit, self.palette_colors, show_score=self.context.config.ui.show_scores
            )
            card.open_document.connect(self._open_document)
            card.open_location.connect(self._open_location)
            card.copy_link.connect(self._copy_link)
            self._results_layout.insertWidget(self._results_layout.count() - 1, card)
        self._scroll.verticalScrollBar().setValue(0)
        self._update_pagination()

    def _clear_results(self) -> None:
        while self._results_layout.count() > 1:
            item = self._results_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()

    def _show_empty(self, message: str) -> None:
        self._clear_results()
        self._summary.setText("")
        placeholder = EmptyState(message)
        self._results_layout.insertWidget(0, placeholder)

    def _update_pagination(self) -> None:
        if self._response is None or self._response.total_documents == 0:
            self.page_label.setText("")
            self.previous_button.setEnabled(False)
            self.next_button.setEnabled(False)
            return
        pages = max(1, -(-self._response.total_documents // self._page_size))
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

    def _copy_link(self, hit: object) -> None:
        if not isinstance(hit, DocumentHit):
            return
        target = hit.web_url or hit.local_path or hit.logical_path
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(target)
        self.status_message.emit("Skopiowano odnosnik do schowka.")

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
        if key == Qt.Key.Key_Escape and self.cancel_button.isEnabled():
            self.cancel_search()
            return
        super().keyPressEvent(event)  # type: ignore[arg-type]


__all__ = ["SearchView"]

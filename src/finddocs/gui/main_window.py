"""Okno glowne aplikacji."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QCloseEvent, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from finddocs.gui import i18n
from finddocs.gui.context import AppContext
from finddocs.gui.diagnostics_view import DiagnosticsView
from finddocs.gui.dialogs import ask_yes_no, show_info
from finddocs.gui.indexing_view import IndexingView
from finddocs.gui.report_view import ReportView
from finddocs.gui.search_view import SearchView
from finddocs.gui.sources_view import SourcesView
from finddocs.gui.theme import SPACE_LG, SPACE_MD, SPACE_SM, SPACE_XS, Palette, theme_icon
from finddocs.gui.widgets.page import StatusDot
from finddocs.logging_setup import get_logger
from finddocs.version import APP_VERSION

log = get_logger(__name__)

SIDEBAR_WIDTH = 232

#: Bok znaczka aplikacji w naglowku panelu nawigacji.
BRAND_ICON_SIZE = 26

#: Ekrany nawigacji: napis, nazwa glifu. Kolejnosc odpowiada kolejnosci widokow
#: na stosie i numerom skrotow Ctrl+1 do Ctrl+5.
NAV_ITEMS: tuple[tuple[str, str], ...] = (
    (i18n.NAV_SEARCH, "search"),
    (i18n.NAV_SOURCES, "folder"),
    (i18n.NAV_INDEXING, "database"),
    (i18n.NAV_REPORT, "chart"),
    (i18n.NAV_DIAGNOSTICS, "pulse"),
)


class MainWindow(QMainWindow):
    """Okno z panelem nawigacji i widokami."""

    def __init__(self, context: AppContext, palette: Palette, icon: QIcon | None = None) -> None:
        super().__init__()
        self.context = context
        self.palette_colors = palette
        self.setWindowTitle(f"{i18n.APP_TITLE} {APP_VERSION}")
        if icon is not None:
            self.setWindowIcon(icon)
        self.resize(
            context.config.ui.window_width,
            context.config.ui.window_height,
        )
        self.setMinimumSize(QSize(980, 640))

        self.window_icon = icon
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_sidebar())
        self.stack = QStackedWidget()
        layout.addWidget(self.stack, stretch=1)
        self.setCentralWidget(central)

        self.search_view = SearchView(context, palette)
        self.sources_view = SourcesView(context)
        self.indexing_view = IndexingView(context)
        self.report_view = ReportView(context)
        self.diagnostics_view = DiagnosticsView(context)

        for view in (
            self.search_view,
            self.sources_view,
            self.indexing_view,
            self.report_view,
            self.diagnostics_view,
        ):
            self.stack.addWidget(view)
            signal = getattr(view, "status_message", None)
            if signal is not None:
                signal.connect(self.show_status)

        self.indexing_view.index_changed.connect(self._on_index_changed)
        self.sources_view.sources_changed.connect(self._on_sources_changed)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        # Kropka niesie stan trybu semantycznego kolorem, wiec da sie go odczytac
        # katem oka, bez czytania calego paska.
        self.semantic_dot = StatusDot("off")
        self.index_label = QLabel("")
        self.status.addPermanentWidget(self.semantic_dot)
        self.status.addPermanentWidget(self.index_label)

        self._build_shortcuts()
        self.nav.setCurrentRow(0)
        self.refresh_index_status()

    # --- budowa -----------------------------------------------------------

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(SIDEBAR_WIDTH)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, SPACE_MD)
        layout.setSpacing(0)

        layout.addWidget(self._build_brand())

        self.nav = QListWidget()
        self.nav.setObjectName("SidebarList")
        self.nav.setFrameShape(QListWidget.Shape.NoFrame)
        self.nav.setIconSize(QSize(18, 18))
        for position, (label, icon_name) in enumerate(NAV_ITEMS, start=1):
            item = QListWidgetItem(theme_icon(icon_name, self.palette_colors), label, self.nav)
            item.setToolTip(f"{label} (Ctrl+{position})")
        self.nav.currentRowChanged.connect(self._on_nav_changed)
        layout.addWidget(self.nav, stretch=1)

        version = QLabel(f"Wersja {APP_VERSION}")
        version.setObjectName("Hint")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version)
        return sidebar

    def _build_brand(self) -> QWidget:
        """Znaczek aplikacji, nazwa i jednozdaniowy opis nad nawigacja."""
        brand = QWidget()
        outer = QVBoxLayout(brand)
        outer.setContentsMargins(SPACE_LG, SPACE_LG, SPACE_LG, SPACE_MD)
        outer.setSpacing(SPACE_XS)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(SPACE_SM)
        if self.window_icon is not None and not self.window_icon.isNull():
            mark = QLabel()
            mark.setPixmap(self.window_icon.pixmap(QSize(BRAND_ICON_SIZE, BRAND_ICON_SIZE)))
            row.addWidget(mark)
        title = QLabel(i18n.APP_TITLE)
        title.setObjectName("AppTitle")
        row.addWidget(title)
        row.addStretch(1)
        outer.addLayout(row)

        subtitle = QLabel(i18n.APP_SUBTITLE)
        subtitle.setObjectName("AppSubtitle")
        subtitle.setWordWrap(True)
        outer.addWidget(subtitle)
        return brand

    def _build_shortcuts(self) -> None:
        find = QAction("Szukaj", self)
        find.setShortcut(QKeySequence.StandardKey.Find)
        find.triggered.connect(self._focus_search)
        self.addAction(find)

        refresh = QAction("Odśwież", self)
        refresh.setShortcut(QKeySequence.StandardKey.Refresh)
        refresh.triggered.connect(self.refresh_index_status)
        self.addAction(refresh)

        # Ctrl+1 do Ctrl+5 przelaczaja ekrany w kolejnosci panelu nawigacji.
        for position in range(1, len(NAV_ITEMS) + 1):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{position}"), self)
            shortcut.activated.connect(lambda row=position - 1: self.nav.setCurrentRow(row))

    # --- reakcje ----------------------------------------------------------

    def _on_nav_changed(self, row: int) -> None:
        self.stack.setCurrentIndex(row)
        widget = self.stack.currentWidget()
        if widget is self.search_view:
            self.search_view.refresh_filter_values()
            self.search_view.focus_query()
        elif widget is self.indexing_view:
            self.indexing_view.refresh_tables()
        elif widget is self.diagnostics_view:
            self.diagnostics_view.refresh()
        elif widget is self.sources_view:
            self.sources_view.refresh()

    def _focus_search(self) -> None:
        self.nav.setCurrentRow(0)
        self.search_view.focus_query()

    def _on_index_changed(self) -> None:
        self.refresh_index_status()
        self.search_view.refresh_filter_values()

    def _on_sources_changed(self) -> None:
        self.refresh_index_status()

    def show_status(self, message: str) -> None:
        if message:
            self.status.showMessage(message, 8000)

    def refresh_index_status(self) -> None:
        """Stan indeksu w pasku okna: liczby, tryb semantyczny i rozmiar."""
        status = self.context.status_summary()
        if not status:
            self.semantic_dot.set_role("warn")
            self.semantic_dot.setToolTip(i18n.STATUS_INDEX_UNAVAILABLE)
            self.index_label.setText(i18n.STATUS_INDEX_UNAVAILABLE)
            return
        parts = [
            f"Dokumenty: {status.get('dokumenty_zaindeksowane', 0)}",
            f"Fragmenty: {status.get('fragmenty', 0)}",
        ]
        if status.get("semantyka_dostepna"):
            role, semantic = "ok", f"Model: {status.get('model')}"
        elif not self.context.config.embedding.semantic_enabled:
            role, semantic = "off", i18n.STATUS_SEMANTIC_DISABLED
        else:
            role, semantic = "warn", i18n.STATUS_SEMANTIC_UNAVAILABLE
        parts.append(semantic)
        parts.append(i18n.format_bytes(int(status.get("rozmiar_bajty", 0))))
        self.semantic_dot.set_role(role)
        self.semantic_dot.setToolTip(semantic)
        self.index_label.setText(i18n.STATUS_SEPARATOR.join(parts))

    def run_startup_checks(self) -> None:
        """Pokazuje komunikaty startowe wymagajace decyzji uzytkownika.

        Metode wywolujemy dopiero po ``show()``. Okna modalne otwarte w
        konstruktorze wisialyby nad pustym ekranem i blokowalyby proces
        w trybach nieinteraktywnych.
        """
        self._show_startup_notes()
        self._offer_resume()

    def _show_startup_notes(self) -> None:
        notes = self.context.startup_notes
        if not notes:
            return
        details = "\n".join(f"- {note}" for note in notes)
        if self.context.rebuild_required:
            show_info(
                self,
                i18n.INDEX_INCOMPATIBLE.format(details=details),
                i18n.INDEX_INCOMPATIBLE_TITLE,
            )
            return
        show_info(self, i18n.STARTUP_NOTES.format(details=details), i18n.STARTUP_NOTES_TITLE)

    def _offer_resume(self) -> None:
        runner = self.context.runner
        if runner is None:
            return
        jobs = [j for j in runner.resumable_jobs() if j["stan"] in {"paused", "running"}]
        if not jobs:
            return
        if ask_yes_no(self, i18n.RESUME_PROMPT, i18n.RESUME_TITLE):
            self.nav.setCurrentRow(2)
            self.indexing_view.resume_interrupted(str(jobs[0]["job_id"]))

    # --- zamkniecie -------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:
        """Zapisuje ustawienia okna i zamyka zasoby aplikacji."""
        runner = self.context.runner
        if runner is not None and runner.is_running:
            confirmed = ask_yes_no(
                self,
                "Indeksowanie jest w toku. Zamknięcie aplikacji przerwie zadanie. "
                "Postęp zostanie zachowany i będzie można je wznowić. Zamknąć?",
            )
            if not confirmed:
                event.ignore()
                return
        self.context.config.ui.window_width = self.width()
        self.context.config.ui.window_height = self.height()
        try:
            self.context.save()
        except Exception as exc:
            log.warning("gui.save_on_close_failed", error_type=type(exc).__name__)
        self.context.close()
        event.accept()


__all__ = ["SIDEBAR_WIDTH", "MainWindow"]

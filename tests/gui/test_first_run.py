"""Testy pierwszego uruchomienia okna glownego."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from finddocs.gui import i18n
from finddocs.gui.context import AppContext
from finddocs.gui.indexing_view import IndexingView
from finddocs.gui.main_window import MainWindow
from finddocs.gui.report_view import ReportView
from finddocs.gui.search_view import SearchView
from finddocs.gui.sources_view import SourcesView
from finddocs.gui.theme import Palette


@pytest.mark.gui
def test_window_builds_on_empty_config(
    qtbot: object, gui_context: AppContext, gui_palette: Palette
) -> None:
    """Okno powstaje na domyslnej konfiguracji, bez zadnego skonfigurowanego zrodla."""
    assert gui_context.config.sources == []

    window = MainWindow(gui_context, gui_palette)
    qtbot.addWidget(window)  # type: ignore[attr-defined]

    assert window.windowTitle().startswith(i18n.APP_TITLE)
    # Cztery ekrany nawigacji glownej plus Ustawienia przypiete na dole.
    # Diagnostyka jest zakladka Ustawien, nie osobnym ekranem.
    assert window.stack.count() == 5
    assert window.nav.count() == 4
    assert window.bottom_nav.count() == 1


@pytest.mark.gui
def test_startup_note_is_shown_without_model(
    main_window: MainWindow, message_boxes: list[QMessageBox]
) -> None:
    """Brak modelu jest zglaszany przy starcie jako uwaga, a nie jako blad."""
    assert main_window.context.startup_notes
    # Konstruktor nie otwiera zadnego okna, inaczej okno modalne wisialoby nad pustym
    # ekranem. Komunikaty pokazuje dopiero jawne wywolanie po ``show()``.
    assert message_boxes == []

    main_window.run_startup_checks()

    assert message_boxes, "Uwagi startowe powinny pojawic sie w oknie komunikatu."
    text = message_boxes[0].text()
    assert "Tryb dokładny działa normalnie" in text
    # Brak modelu nie uniewaznia indeksu pelnotekstowego, wiec nie straszymy przebudowa.
    assert main_window.context.rebuild_required is False
    assert message_boxes[0].windowTitle() == i18n.STARTUP_NOTES_TITLE


@pytest.mark.gui
def test_no_widget_flashes_as_separate_window(
    qtbot: object, gui_context: AppContext, gui_palette: Palette
) -> None:
    """Zaden widget nie moze mignac na ekranie jako osobne okno.

    ``setVisible(True)`` na kontrolce bez rodzica robi z niej okno najwyzszego
    poziomu. Kontrolka trafia potem do ukladu i okno znika, ale uzytkownik
    widzi przy starcie migniecie. Widocznosc ustawiamy dopiero po wstawieniu
    do ukladu, a ten test tego pilnuje.
    """
    application = QApplication.instance()
    assert application is not None
    stray: list[str] = []

    class WindowSpy(QObject):
        def eventFilter(self, watched: QObject, event: QEvent) -> bool:
            if (
                event.type() == QEvent.Type.Show
                and isinstance(watched, QWidget)
                and watched.isWindow()
                and not isinstance(watched, MainWindow)
            ):
                stray.append(f"{type(watched).__name__} {watched.objectName()}")
            return False

    spy = WindowSpy()
    application.installEventFilter(spy)
    try:
        window = MainWindow(gui_context, gui_palette)
        qtbot.addWidget(window)  # type: ignore[attr-defined]
    finally:
        application.removeEventFilter(spy)

    assert stray == []


@pytest.mark.gui
def test_startup_notes_suppressed_in_headless_mode(
    main_window: MainWindow,
    message_boxes: list[QMessageBox],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Z ``FINDDOCS_NO_DIALOG=1`` okna nie blokuja uruchomienia bez uzytkownika."""
    monkeypatch.setenv("FINDDOCS_NO_DIALOG", "1")

    main_window.run_startup_checks()

    assert message_boxes == []


@pytest.mark.gui
def test_search_screen_is_visible_first(main_window: MainWindow) -> None:
    """Po starcie widoczny jest ekran wyszukiwania."""
    assert main_window.stack.currentIndex() == 0
    assert main_window.stack.currentWidget() is main_window.search_view
    assert isinstance(main_window.stack.currentWidget(), SearchView)
    assert main_window.nav.currentItem().text() == i18n.NAV_SEARCH


@pytest.mark.gui
def test_status_bar_shows_index_state(main_window: MainWindow) -> None:
    """Pasek stanu pokazuje liczby dokumentow i informacje o trybie semantycznym."""
    text = main_window.index_label.text()
    assert "Dokumenty: 0" in text
    assert "Fragmenty: 0" in text
    assert "Tryb semantyczny niedostępny" in text


@pytest.mark.gui
def test_status_bar_reports_indexed_documents(
    qtbot: object, indexed_gui_context: AppContext, gui_palette: Palette
) -> None:
    """Po zaindeksowaniu korpusu pasek stanu pokazuje liczbe dokumentow."""
    window = MainWindow(indexed_gui_context, gui_palette)
    qtbot.addWidget(window)  # type: ignore[attr-defined]

    window.refresh_index_status()

    assert "Dokumenty: 0" not in window.index_label.text()
    assert "Fragmenty: 0" not in window.index_label.text()


@pytest.mark.gui
def test_navigation_switches_stack(main_window: MainWindow) -> None:
    """Nawigacja przelacza wszystkie cztery ekrany."""
    expected = [
        (i18n.NAV_SEARCH, SearchView),
        (i18n.NAV_SOURCES, SourcesView),
        (i18n.NAV_INDEXING, IndexingView),
        (i18n.NAV_REPORT, ReportView),
    ]

    for row, (label, view_type) in enumerate(expected):
        main_window.nav.setCurrentRow(row)
        assert main_window.nav.item(row).text() == label
        assert main_window.stack.currentIndex() == row
        assert isinstance(main_window.stack.currentWidget(), view_type)

    main_window.nav.setCurrentRow(0)
    assert main_window.stack.currentWidget() is main_window.search_view


@pytest.mark.gui
def test_skroty_przelaczaja_ekrany(main_window: MainWindow) -> None:
    """Ctrl+1 do Ctrl+4 odpowiadaja pozycjom nawigacji, Ctrl+5 ustawieniom."""
    from PySide6.QtGui import QKeySequence, QShortcut

    registered = {shortcut.key().toString() for shortcut in main_window.findChildren(QShortcut)}
    expected = {QKeySequence(f"Ctrl+{n}").toString() for n in range(1, 6)}
    expected.add(QKeySequence("Ctrl+K").toString())

    assert expected <= registered
    for row in range(main_window.nav.count()):
        assert main_window.nav.item(row).toolTip().endswith(f"(Ctrl+{row + 1})")


@pytest.mark.gui
def test_kropka_stanu_odzwierciedla_tryb_semantyczny(main_window: MainWindow) -> None:
    """Kolor kropki mowi to samo co napis, tylko szybciej."""
    main_window.refresh_index_status()
    assert main_window.semantic_dot.property("dotRole") == "warn"
    assert main_window.semantic_dot.toolTip() == i18n.STATUS_SEMANTIC_UNAVAILABLE

    main_window.context.config.embedding.semantic_enabled = False
    main_window.refresh_index_status()

    assert main_window.semantic_dot.property("dotRole") == "off"
    assert main_window.semantic_dot.toolTip() == i18n.STATUS_SEMANTIC_DISABLED


@pytest.mark.gui
def test_glify_na_przyciskach_akcentowych_maja_kolor_tekstu_na_akcencie(
    main_window: MainWindow, gui_palette: Palette
) -> None:
    """Glif w kolorze zwyklego tekstu na tle akcentu odcina sie od napisu obok.

    W trybie ciemnym akcent jest jasny, a napis na nim ciemny. Glif wzięty
    z ``theme_icon`` jest wtedy jasny, wiec ikona i napis na jednym przycisku
    maja przeciwne kolory. Test sprawdza to na wszystkich przyciskach okna,
    zeby kolejny przycisk akcentowy nie powtorzyl tej pomylki.
    """
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QPushButton
    from tests.gui.helpers import color_distance, glyph_color

    accent_text = QColor(gui_palette.accent_text)
    plain_text = QColor(gui_palette.text)
    checked = 0
    for button in main_window.findChildren(QPushButton):
        if button.objectName() not in ("Primary", "PrimaryIcon") or button.icon().isNull():
            continue
        color = glyph_color(button.icon())
        assert color_distance(color, accent_text) < color_distance(color, plain_text), (
            f"przycisk {button.objectName()} z napisem {button.text()!r} "
            "ma glif w kolorze tekstu zwyklego przycisku"
        )
        checked += 1
    assert checked >= 4, "okno powinno miec kilka przyciskow akcentowych z ikona"


@pytest.mark.gui
def test_status_message_reaches_status_bar(main_window: MainWindow) -> None:
    """Widoki zglaszaja komunikaty przez sygnal status_message do paska stanu."""
    main_window.search_view.status_message.emit("Komunikat testowy")

    assert main_window.status.currentMessage() == "Komunikat testowy"


@pytest.mark.gui
def test_kontrolki_bez_napisu_maja_nazwy_dostepnosci(main_window: MainWindow) -> None:
    """Czytnik ekranu musi umiec nazwac kontrolki, ktore nie maja napisu."""
    assert main_window.nav.accessibleName() == i18n.A11Y_NAV
    assert main_window.bottom_nav.accessibleName() == i18n.NAV_SETTINGS
    assert main_window.search_view.query_edit.accessibleName() == i18n.A11Y_QUERY
    assert main_window.search_view.search_button.accessibleName() == i18n.SEARCH_BUTTON
    assert main_window.search_view.sort_combo.accessibleName() == i18n.A11Y_SORT
    for view in (
        main_window.indexing_view,
        main_window.report_view,
        main_window.settings_view.diagnostics,
    ):
        assert view.table_filter.accessibleName() == i18n.TABLE_FILTER_PLACEHOLDER


@pytest.mark.gui
def test_zmiana_ekranu_czysci_komunikat_paska_stanu(main_window: MainWindow) -> None:
    """Komunikat z jednego ekranu nie moze wisiec nad innym."""
    main_window.search_view.status_message.emit("Wyszukiwanie w toku...")
    assert main_window.status.currentMessage()

    main_window.nav.setCurrentRow(2)

    assert main_window.status.currentMessage() == ""

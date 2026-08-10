"""Testy pierwszego uruchomienia okna glownego."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QMessageBox

from finddocs.gui import i18n
from finddocs.gui.context import AppContext
from finddocs.gui.diagnostics_view import DiagnosticsView
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
    assert window.stack.count() == 5
    assert window.nav.count() == 5


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
    """Nawigacja przelacza wszystkie piec ekranow."""
    expected = [
        (i18n.NAV_SEARCH, SearchView),
        (i18n.NAV_SOURCES, SourcesView),
        (i18n.NAV_INDEXING, IndexingView),
        (i18n.NAV_REPORT, ReportView),
        (i18n.NAV_DIAGNOSTICS, DiagnosticsView),
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
    """Ctrl+1 do Ctrl+5 odpowiadaja pozycjom panelu nawigacji."""
    from PySide6.QtGui import QKeySequence, QShortcut

    registered = {shortcut.key().toString() for shortcut in main_window.findChildren(QShortcut)}
    expected = {QKeySequence(f"Ctrl+{n}").toString() for n in range(1, 6)}

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
def test_status_message_reaches_status_bar(main_window: MainWindow) -> None:
    """Widoki zglaszaja komunikaty przez sygnal status_message do paska stanu."""
    main_window.search_view.status_message.emit("Komunikat testowy")

    assert main_window.status.currentMessage() == "Komunikat testowy"

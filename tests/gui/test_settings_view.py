"""Testy ekranu ustawien, okna O programie i przypietej pozycji nawigacji."""

from __future__ import annotations

import json

import pytest
from PySide6.QtWidgets import QLabel

from finddocs.gui.context import AppContext
from finddocs.gui.main_window import SETTINGS_STACK_INDEX, MainWindow
from finddocs.gui.settings_view import THEME_VALUES, AboutDialog, SettingsView
from finddocs.version import APP_VERSION


@pytest.fixture
def settings_view(qtbot: object, gui_context: AppContext) -> SettingsView:
    view = SettingsView(gui_context)
    qtbot.addWidget(view)  # type: ignore[attr-defined]
    return view


@pytest.mark.gui
def test_zmiana_motywu_zapisuje_konfiguracje_i_zglasza_zadanie(
    settings_view: SettingsView, gui_context: AppContext
) -> None:
    """Motyw zapisuje sie od razu, a przebudowe okna zleca sygnal."""
    requested: list[str] = []
    settings_view.theme_change_requested.connect(requested.append)

    settings_view.theme_switch.buttons()[THEME_VALUES.index("dark")].click()

    assert gui_context.config.ui.theme == "dark"
    assert requested == ["dark"]
    saved = json.loads(gui_context.paths.config_file.read_text(encoding="utf-8"))
    assert saved["ui"]["theme"] == "dark"


@pytest.mark.gui
def test_ponowny_wybor_tego_samego_motywu_nie_zglasza_zadania(
    settings_view: SettingsView, gui_context: AppContext
) -> None:
    requested: list[str] = []
    settings_view.theme_change_requested.connect(requested.append)

    settings_view.theme_switch.buttons()[THEME_VALUES.index(gui_context.config.ui.theme)].click()

    assert requested == []


@pytest.mark.gui
def test_liczba_wynikow_na_strone_dziala_od_razu(main_window: MainWindow) -> None:
    """Zmiana w ustawieniach trafia do konfiguracji i do ekranu wyszukiwania."""
    main_window.settings_view.page_size_spin.setValue(45)

    assert main_window.context.config.search.page_size == 45
    assert main_window.search_view._page_size == 45


@pytest.mark.gui
def test_pozostale_ustawienia_zapisuja_sie_od_razu(
    settings_view: SettingsView, gui_context: AppContext
) -> None:
    settings_view.open_with_combo.setCurrentIndex(
        settings_view.open_with_combo.findData("local_path")
    )
    settings_view.show_scores_check.setChecked(False)

    assert gui_context.config.ui.open_documents_with == "local_path"
    assert gui_context.config.ui.show_scores is False
    saved = json.loads(gui_context.paths.config_file.read_text(encoding="utf-8"))
    assert saved["ui"]["open_documents_with"] == "local_path"
    assert saved["ui"]["show_scores"] is False


@pytest.mark.gui
def test_ustawienia_sa_przypiete_na_dole_i_wybor_jest_wylaczny(
    main_window: MainWindow,
) -> None:
    """Zaznaczona jest zawsze dokladnie jedna pozycja obu list nawigacji."""
    main_window.select_settings()

    assert main_window.stack.currentIndex() == SETTINGS_STACK_INDEX
    assert main_window.nav.currentRow() == -1
    assert main_window.bottom_nav.currentRow() == 0

    main_window.nav.setCurrentRow(0)

    assert main_window.stack.currentIndex() == 0
    assert main_window.bottom_nav.currentRow() == -1
    assert main_window.bottom_nav.selectedItems() == []


@pytest.mark.gui
def test_diagnostyka_jest_zakladka_ustawien(main_window: MainWindow) -> None:
    """Diagnostyka nie ma pozycji nawigacji, jest druga zakladka Ustawien."""
    from finddocs.gui import i18n
    from finddocs.gui.diagnostics_view import DiagnosticsView

    labels = [main_window.nav.item(row).text() for row in range(main_window.nav.count())]
    assert i18n.DIAG_TITLE not in labels

    settings = main_window.settings_view
    assert settings.tabs.count() == 2
    assert settings.tabs.tabText(1) == i18n.DIAG_TITLE

    settings.tabs.setCurrentIndex(1)
    assert settings.tabs.currentWidget() is settings.diagnostics
    assert isinstance(settings.diagnostics, DiagnosticsView)


@pytest.mark.gui
def test_komunikaty_diagnostyki_docieraja_do_paska_stanu(main_window: MainWindow) -> None:
    """Sygnal status_message panelu diagnostyki przechodzi przez ustawienia."""
    main_window.settings_view.diagnostics.status_message.emit("Komunikat diagnostyki")

    assert main_window.status.currentMessage() == "Komunikat diagnostyki"


@pytest.mark.gui
def test_okno_o_programie_pokazuje_wersje_i_katalogi(
    qtbot: object, gui_context: AppContext
) -> None:
    dialog = AboutDialog(gui_context)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]

    labels = [label.text() for label in dialog.findChildren(QLabel)]
    assert any(APP_VERSION in text for text in labels)
    assert any(str(gui_context.paths.root) in text for text in labels)
    assert any(str(gui_context.paths.logs_dir) in text for text in labels)

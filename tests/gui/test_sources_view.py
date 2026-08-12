"""Testy ekranu zrodel: zaznaczenie, dane wiersza i stan pusty."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

from finddocs.gui import i18n
from finddocs.gui.context import AppContext
from finddocs.gui.sources_view import SOURCE_ID_ROLE, SharePointDialog, SourcesView


@pytest.fixture
def sources_view(qtbot: object, gui_context_with_source: AppContext) -> SourcesView:
    """Widok zrodel z jednym skonfigurowanym katalogiem lokalnym."""
    view = SourcesView(gui_context_with_source)
    qtbot.addWidget(view)  # type: ignore[attr-defined]
    return view


@pytest.mark.gui
def test_akcje_wymagajace_zaznaczenia_sa_wylaczone_bez_wyboru(sources_view: SourcesView) -> None:
    """Klikniecie bez zaznaczenia konczylo sie oknem z pouczeniem, zamiast akcja."""
    assert sources_view.table.rowCount() == 1
    assert not sources_view.test_button.isEnabled()
    assert not sources_view.remove_button.isEnabled()

    sources_view.table.selectRow(0)

    assert sources_view.test_button.isEnabled()
    assert sources_view.remove_button.isEnabled()


@pytest.mark.gui
def test_identyfikator_zrodla_jest_w_danych_wiersza_a_nie_w_kolumnie(
    sources_view: SourcesView,
) -> None:
    """Identyfikator to wartosc techniczna, wiec nie zajmuje kolumny w tabeli."""
    headers = [
        sources_view.table.horizontalHeaderItem(column).text()
        for column in range(sources_view.table.columnCount())
    ]
    assert headers == ["Nazwa", "Rodzaj", "Lokalizacja", "Aktywne"]

    item = sources_view.table.item(0, 0)
    assert item.data(SOURCE_ID_ROLE) == "zrodlo-testowe"

    sources_view.table.selectRow(0)
    source = sources_view._selected_source()
    assert source is not None
    assert source.source_id == "zrodlo-testowe"


@pytest.mark.gui
def test_pole_wyboru_w_wierszu_przelacza_zrodlo(sources_view: SourcesView) -> None:
    """Wlaczenie zrodla to stan wiersza, bez zaznaczania i osobnego przycisku."""
    item = sources_view.table.item(0, 3)
    before = sources_view.context.config.sources[0].enabled
    assert item.checkState() is (Qt.CheckState.Checked if before else Qt.CheckState.Unchecked)

    item.setCheckState(Qt.CheckState.Unchecked if before else Qt.CheckState.Checked)

    assert sources_view.context.config.sources[0].enabled is not before


@pytest.mark.gui
def test_opcja_archiwow_zapisuje_konfiguracje(sources_view: SourcesView) -> None:
    """Pole wyboru archiwow ZIP przelacza opcje indeksowania i zapisuje ustawienia."""
    config = sources_view.context.config
    assert config.indexing.index_archives is False
    assert sources_view.archives_check.isChecked() is False

    sources_view.archives_check.setChecked(True)

    assert config.indexing.index_archives is True

    sources_view.archives_check.setChecked(False)

    assert config.indexing.index_archives is False


@pytest.mark.gui
def test_dialog_sharepoint_oznacza_brakujace_pola(qtbot: object) -> None:
    """Walidacja dziala na miejscu: czerwone pola i podpis, bez osobnego okna."""
    dialog = SharePointDialog()
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]

    dialog._validate_and_accept()

    assert not dialog.error_label.isHidden()
    assert "adres witryny" in dialog.error_label.text()
    assert dialog.site_edit.property("fieldInvalid") == "true"

    dialog.site_edit.setText("https://firma.sharepoint.com/sites/Finanse")

    assert dialog.site_edit.property("fieldInvalid") == ""


@pytest.mark.gui
def test_brak_zrodel_konczy_sie_podpowiedzia_co_zrobic(
    qtbot: object, gui_context: AppContext
) -> None:
    """Pierwsze uruchomienie pokazuje pusta tabele, wiec potrzebuje wskazowki."""
    view = SourcesView(gui_context)
    qtbot.addWidget(view)  # type: ignore[attr-defined]

    assert view.table.rowCount() == 0
    assert not view.empty_banner.isHidden()
    assert view.empty_banner.text() == i18n.SOURCES_EMPTY_HINT


@pytest.mark.gui
def test_dodanie_zrodla_chowa_podpowiedz(sources_view: SourcesView) -> None:
    assert sources_view.empty_banner.isHidden()

"""Testy ekranu zrodel: zaznaczenie, dane wiersza i stan pusty."""

from __future__ import annotations

import pytest

from finddocs.gui import i18n
from finddocs.gui.context import AppContext
from finddocs.gui.sources_view import SOURCE_ID_ROLE, SourcesView


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
    assert not sources_view.toggle_button.isEnabled()
    assert not sources_view.remove_button.isEnabled()

    sources_view.table.selectRow(0)

    assert sources_view.test_button.isEnabled()
    assert sources_view.toggle_button.isEnabled()
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
def test_przelaczenie_zrodla_dziala_na_zaznaczonym_wierszu(sources_view: SourcesView) -> None:
    sources_view.table.selectRow(0)
    before = sources_view.context.config.sources[0].enabled

    sources_view.toggle_selected()

    assert sources_view.context.config.sources[0].enabled is not before
    assert sources_view.table.item(0, 3).text() == ("tak" if not before else "nie")


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

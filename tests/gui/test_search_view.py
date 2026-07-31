"""Testy ekranu wyszukiwania."""

from __future__ import annotations

import datetime as _dt
from collections.abc import Callable

import pytest
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from finddocs.gui import i18n
from finddocs.gui.context import AppContext
from finddocs.gui.search_view import SearchView
from finddocs.gui.theme import Palette
from finddocs.gui.widgets.result_card import ResultCard
from finddocs.types import ChunkHit, DocumentHit, MatchKind, SearchMode, SourceKind, TextOrigin

QUERY = "przelewow"
MISSING_QUERY = "kwantowagalaktykaniewystepujaca"

#: Wyszukiwanie idzie do puli watkow, wiec czekamy na wynik zamiast usypiac test.
TIMEOUT_MS = 15_000


@pytest.fixture
def make_search_view(
    qtbot: object, indexed_gui_context: AppContext, gui_palette: Palette
) -> Callable[..., SearchView]:
    """Fabryka widoku wyszukiwania na zaindeksowanym korpusie."""

    def build(page_size: int = 20) -> SearchView:
        indexed_gui_context.config.search.page_size = page_size
        view = SearchView(indexed_gui_context, gui_palette)
        qtbot.addWidget(view)  # type: ignore[attr-defined]
        return view

    return build


def _mode_button(view: SearchView, mode: SearchMode) -> QPushButton:
    button = view.mode_group.button(list(SearchMode).index(mode))
    assert button is not None
    return button


def _sample_hit() -> DocumentHit:
    """Wynik zbudowany recznie, bez udzialu indeksu."""
    chunk = ChunkHit(
        chunk_id=1,
        doc_id=7,
        ordinal=0,
        text="Procedura przelewow krajowych.",
        highlighted="Procedura [[hl]]przelewow[[/hl]] krajowych.",
        score=0.9,
        match_kind=MatchKind.EXACT,
        origin=TextOrigin.NATIVE,
        page=2,
    )
    return DocumentHit(
        doc_id=7,
        name="procedura.pdf",
        logical_path="procedury/2024/procedura.pdf",
        library="Dokumenty",
        source_id="zrodlo-testowe",
        source_kind=SourceKind.LOCAL_DIR,
        extension=".pdf",
        mime_type="application/pdf",
        modified_at=_dt.datetime(2024, 5, 17, 12, 0),
        indexed_at=None,
        author="Kowalski Jan",
        web_url="https://przyklad.test/procedura.pdf",
        parent_url="https://przyklad.test/procedury",
        local_path="C:/dane/procedura.pdf",
        used_ocr=True,
        ocr_confidence=0.91,
        score=0.75,
        match_kind=MatchKind.HYBRID,
        chunks=[chunk],
        total_matching_chunks=3,
    )


# --- wyszukiwanie ---------------------------------------------------------------


@pytest.mark.gui
def test_query_returns_result_cards(
    qtbot: object,
    make_search_view: Callable[..., SearchView],
    result_cards: Callable[[QWidget], list[ResultCard]],
    corpus_stats: dict[str, int],
) -> None:
    """Wpisanie zapytania i uruchomienie wyszukiwania konczy sie kartami wynikow."""
    view = make_search_view()
    view.query_edit.setText(QUERY)

    view.run_search()

    qtbot.waitUntil(lambda: bool(result_cards(view)), timeout=TIMEOUT_MS)  # type: ignore[attr-defined]
    assert len(result_cards(view)) == corpus_stats["przelewow"]
    assert i18n.RESULTS_COUNT_EXACT.format(count=corpus_stats["przelewow"]) in view._summary.text()
    assert view.search_button.isEnabled()
    assert not view.cancel_button.isEnabled()


@pytest.mark.gui
@pytest.mark.parametrize("mode", [SearchMode.EXACT, SearchMode.HYBRID])
def test_exact_and_hybrid_modes_return_results(
    qtbot: object,
    make_search_view: Callable[..., SearchView],
    result_cards: Callable[[QWidget], list[ResultCard]],
    corpus_stats: dict[str, int],
    mode: SearchMode,
) -> None:
    """Tryb dokladny i hybrydowy zwracaja te same dokumenty, gdy brak modelu."""
    view = make_search_view()
    _mode_button(view, mode).setChecked(True)
    assert view.current_mode() is mode

    view.query_edit.setText(QUERY)
    view.run_search()

    qtbot.waitUntil(lambda: bool(result_cards(view)), timeout=TIMEOUT_MS)  # type: ignore[attr-defined]
    assert len(result_cards(view)) == corpus_stats["przelewow"]


@pytest.mark.gui
def test_hybrid_mode_reports_missing_semantic_index(
    qtbot: object,
    make_search_view: Callable[..., SearchView],
    result_cards: Callable[[QWidget], list[ResultCard]],
) -> None:
    """Bez modelu tryb hybrydowy informuje, ze uzyto tylko czesci dokladnej."""
    view = make_search_view()
    _mode_button(view, SearchMode.HYBRID).setChecked(True)
    view.query_edit.setText(QUERY)

    view.run_search()

    qtbot.waitUntil(lambda: bool(result_cards(view)), timeout=TIMEOUT_MS)  # type: ignore[attr-defined]
    assert "semantyczny jest niedostepny" in view._summary.text()


@pytest.mark.gui
def test_mode_hint_follows_selection(make_search_view: Callable[..., SearchView]) -> None:
    """Podpowiedz pod przyciskami opisuje wybrany tryb."""
    view = make_search_view()

    _mode_button(view, SearchMode.EXACT).click()

    assert view.mode_hint.text() == i18n.MODE_HINTS[SearchMode.EXACT]


@pytest.mark.gui
def test_empty_index_asks_for_indexing(
    qtbot: object,
    gui_context: AppContext,
    gui_palette: Palette,
    empty_state_text: Callable[[QWidget], str],
) -> None:
    """Pusty indeks konczy sie komunikatem o koniecznosci zaindeksowania."""
    view = SearchView(gui_context, gui_palette)
    qtbot.addWidget(view)  # type: ignore[attr-defined]
    view.query_edit.setText(QUERY)

    view.run_search()

    assert empty_state_text(view) == i18n.SEARCH_INDEX_EMPTY


@pytest.mark.gui
def test_empty_query_shows_instructions(
    make_search_view: Callable[..., SearchView],
    empty_state_text: Callable[[QWidget], str],
) -> None:
    """Puste zapytanie nie uruchamia wyszukiwania, tylko przypomina o trybach."""
    view = make_search_view()
    view.query_edit.setText("   ")

    view.run_search()

    assert empty_state_text(view) == i18n.SEARCH_EMPTY_STATE


@pytest.mark.gui
def test_query_without_hits_shows_message(
    qtbot: object,
    make_search_view: Callable[..., SearchView],
    empty_state_text: Callable[[QWidget], str],
) -> None:
    """Zapytanie bez trafien konczy sie komunikatem o braku wynikow."""
    view = make_search_view()
    view.query_edit.setText(MISSING_QUERY)

    view.run_search()

    qtbot.waitUntil(  # type: ignore[attr-defined]
        lambda: empty_state_text(view) == i18n.SEARCH_NO_RESULTS,
        timeout=TIMEOUT_MS,
    )
    assert not view.previous_button.isEnabled()
    assert not view.next_button.isEnabled()


# --- paginacja ------------------------------------------------------------------


@pytest.mark.gui
def test_pagination_buttons_follow_page(
    qtbot: object,
    make_search_view: Callable[..., SearchView],
    result_cards: Callable[[QWidget], list[ResultCard]],
) -> None:
    """Przyciski stron wlaczaja sie i wylaczaja zgodnie z numerem strony."""
    view = make_search_view(page_size=2)
    pages = 3  # 5 dokumentow po 2 na strone

    view.query_edit.setText(QUERY)
    view.run_search()
    qtbot.waitUntil(lambda: bool(result_cards(view)), timeout=TIMEOUT_MS)  # type: ignore[attr-defined]

    assert view.page_label.text() == i18n.PAGINATION_STATUS.format(page=1, pages=pages)
    assert not view.previous_button.isEnabled()
    assert view.next_button.isEnabled()
    assert len(result_cards(view)) == 2

    view.next_button.click()
    qtbot.waitUntil(  # type: ignore[attr-defined]
        lambda: view.page_label.text() == i18n.PAGINATION_STATUS.format(page=2, pages=pages),
        timeout=TIMEOUT_MS,
    )
    assert view.previous_button.isEnabled()
    assert view.next_button.isEnabled()
    assert len(result_cards(view)) == 2

    view.next_button.click()
    qtbot.waitUntil(  # type: ignore[attr-defined]
        lambda: view.page_label.text() == i18n.PAGINATION_STATUS.format(page=3, pages=pages),
        timeout=TIMEOUT_MS,
    )
    assert view.previous_button.isEnabled()
    assert not view.next_button.isEnabled()
    assert len(result_cards(view)) == 1

    view.previous_button.click()
    qtbot.waitUntil(  # type: ignore[attr-defined]
        lambda: view.page_label.text() == i18n.PAGINATION_STATUS.format(page=2, pages=pages),
        timeout=TIMEOUT_MS,
    )
    assert view.previous_button.isEnabled()


# --- filtry ---------------------------------------------------------------------


@pytest.mark.gui
def test_extension_filter_narrows_results(
    qtbot: object,
    make_search_view: Callable[..., SearchView],
    result_cards: Callable[[QWidget], list[ResultCard]],
    corpus_stats: dict[str, int],
) -> None:
    """Ustawienie rozszerzenia zaweza liste wynikow."""
    view = make_search_view()
    view.filters_toggle.setChecked(True)
    view.query_edit.setText(QUERY)

    position = view.filter_extension.findData(".md")
    assert position > 0, "Filtr rozszerzen powinien znac rozszerzenia z indeksu."
    view.filter_extension.setCurrentIndex(position)
    assert view.current_filters().extensions == [".md"]

    view.run_search()

    qtbot.waitUntil(lambda: bool(result_cards(view)), timeout=TIMEOUT_MS)  # type: ignore[attr-defined]
    cards = result_cards(view)
    assert len(cards) == corpus_stats["markdown"]
    assert all(card.hit.extension == ".md" for card in cards)


@pytest.mark.gui
def test_clear_filters_resets_every_field(make_search_view: Callable[..., SearchView]) -> None:
    """clear_filters czysci listy, sciezke, daty i pole OCR."""
    view = make_search_view()
    view.filters_toggle.setChecked(True)
    view.filter_extension.setCurrentIndex(view.filter_extension.findData(".txt"))
    view.filter_path.setText("procedury/2024")
    view.filter_date_from.setDate(QDate(2015, 7, 24))
    view.filter_date_to.setDate(QDate(2016, 1, 1))
    view.filter_ocr.setChecked(True)
    assert not view.current_filters().is_empty()

    view.clear_filters()

    filters = view.current_filters()
    assert filters.is_empty()
    assert view.filter_extension.currentIndex() == 0
    assert view.filter_source.currentIndex() == 0
    assert view.filter_library.currentIndex() == 0
    assert view.filter_author.currentIndex() == 0
    assert view.filter_path.text() == ""
    assert view.filter_date_from.date() == QDate(1900, 1, 1)
    assert view.filter_date_to.date() == QDate(1900, 1, 1)
    assert not view.filter_ocr.isChecked()


# --- karta wyniku ---------------------------------------------------------------


@pytest.mark.gui
def test_result_card_emits_actions(qtbot: object, gui_palette: Palette) -> None:
    """Karta wyniku emituje sygnaly otwarcia, lokalizacji i kopiowania."""
    hit = _sample_hit()
    card = ResultCard(hit, gui_palette)
    qtbot.addWidget(card)  # type: ignore[attr-defined]
    buttons = {button.text(): button for button in card.findChildren(QPushButton)}

    signals = [
        (card.open_document, i18n.RESULT_OPEN),
        (card.open_location, i18n.RESULT_OPEN_LOCATION),
        (card.copy_link, i18n.RESULT_COPY_LINK),
    ]
    for signal, label in signals:
        assert label in buttons, f"Karta powinna miec przycisk {label}."
        received: list[object] = []
        signal.connect(received.append)

        buttons[label].click()

        assert received == [hit]


@pytest.mark.gui
def test_copy_link_writes_to_clipboard(
    qtbot: object,
    make_search_view: Callable[..., SearchView],
    result_cards: Callable[[QWidget], list[ResultCard]],
) -> None:
    """Kopiowanie odnosnika wstawia adres dokumentu do schowka."""
    view = make_search_view()
    view.query_edit.setText(QUERY)
    view.run_search()
    qtbot.waitUntil(lambda: bool(result_cards(view)), timeout=TIMEOUT_MS)  # type: ignore[attr-defined]

    card = result_cards(view)[0]
    expected = card.hit.web_url or card.hit.local_path or card.hit.logical_path
    clipboard = QApplication.clipboard()
    clipboard.setText("")

    copy_button = next(
        button
        for button in card.findChildren(QPushButton)
        if button.text() == i18n.RESULT_COPY_LINK
    )
    copy_button.click()

    assert clipboard.text() == expected

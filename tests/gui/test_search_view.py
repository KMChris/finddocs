"""Testy ekranu wyszukiwania."""

from __future__ import annotations

import datetime as _dt
from collections.abc import Callable

import pytest
from PySide6.QtCore import QDate, QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

from finddocs.gui import i18n
from finddocs.gui.context import AppContext
from finddocs.gui.search_view import SearchView
from finddocs.gui.theme import Palette
from finddocs.gui.widgets.result_card import (
    VISIBLE_CHUNKS,
    ResultCard,
    file_glyph,
    flatten_snippet,
    score_role,
)
from finddocs.search.service import HYBRID_NOTE, SEMANTIC_NOTE, TRUNCATED_NOTE
from finddocs.types import (
    ChunkHit,
    DocumentHit,
    MatchKind,
    QueryAnalysis,
    SearchMode,
    SearchResponse,
    SourceKind,
    TextOrigin,
)

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
    # Liczba wynikow i czas zapytania sa w wierszu tytulu, wiec nie zabieraja
    # osobnego wiersza ani nie powtarzaja sie w pasku stanu.
    expected = i18n.RESULTS_COUNT_EXACT.format(
        count=i18n.documents_count(corpus_stats["przelewow"])
    )
    assert view.header.meta_label.text().startswith(expected)
    assert "ms" in view.header.meta_label.text()
    assert not view.is_searching()
    assert view.query_edit.isEnabled()
    assert view.search_button.toolTip() == i18n.SEARCH_BUTTON


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
    # Uwaga o niekompletnosci idzie do banera ostrzegawczego nad lista wynikow.
    assert "semantyczny jest niedostępny" in view.notes_banner.text()
    assert view.notes_banner.property("bannerRole") == "warning"
    assert not view.notes_banner.isHidden()


def _response_with_notes(notes: list[str]) -> SearchResponse:
    """Odpowiedz zbudowana recznie, do testow banera uwag."""
    return SearchResponse(
        hits=[],
        total_documents=0,
        total_is_exact=False,
        mode=SearchMode.HYBRID,
        took_ms=1,
        query_analysis=QueryAnalysis(
            raw_query="zapytanie", normalized_query="zapytanie", semantic_text="zapytanie"
        ),
        notes=notes,
    )


@pytest.mark.gui
def test_uwagi_edukacyjne_nie_otwieraja_banera(
    make_search_view: Callable[..., SearchView],
) -> None:
    """Stala charakterystyka trybu zostaje w podpowiedzi, nie w banerze."""
    view = make_search_view()

    view._render(_response_with_notes([HYBRID_NOTE, SEMANTIC_NOTE]))

    assert view.notes_banner.isHidden()
    assert view.notes_banner.text() == ""


@pytest.mark.gui
def test_uwaga_dynamiczna_trafia_do_banera_bez_edukacyjnej(
    make_search_view: Callable[..., SearchView],
) -> None:
    """Baner pokazuje uwage zalezna od zapytania i pomija edukacyjna."""
    view = make_search_view()

    view._render(_response_with_notes([HYBRID_NOTE, TRUNCATED_NOTE]))

    assert not view.notes_banner.isHidden()
    assert view.notes_banner.text() == TRUNCATED_NOTE


@pytest.mark.gui
def test_tryb_dokladny_nie_otwiera_banera(
    qtbot: object,
    make_search_view: Callable[..., SearchView],
    result_cards: Callable[[QWidget], list[ResultCard]],
) -> None:
    """Wyszukiwanie dokladne bez uwag zostawia baner ukryty."""
    view = make_search_view()
    _mode_button(view, SearchMode.EXACT).setChecked(True)
    view.query_edit.setText(QUERY)

    view.run_search()

    qtbot.waitUntil(lambda: bool(result_cards(view)), timeout=TIMEOUT_MS)  # type: ignore[attr-defined]
    assert view.notes_banner.isHidden()


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
    empty_state_title: Callable[[QWidget], str],
) -> None:
    """Pusty indeks konczy sie komunikatem o koniecznosci zaindeksowania."""
    view = SearchView(gui_context, gui_palette)
    qtbot.addWidget(view)  # type: ignore[attr-defined]
    view.query_edit.setText(QUERY)

    view.run_search()

    assert empty_state_title(view) == i18n.SEARCH_INDEX_EMPTY_TITLE
    assert empty_state_text(view) == i18n.SEARCH_INDEX_EMPTY


@pytest.mark.gui
def test_empty_query_shows_instructions(
    make_search_view: Callable[..., SearchView],
    empty_state_text: Callable[[QWidget], str],
    empty_state_title: Callable[[QWidget], str],
) -> None:
    """Puste zapytanie nie uruchamia wyszukiwania, tylko przypomina o trybach."""
    view = make_search_view()
    view.query_edit.setText("   ")

    view.run_search()

    assert empty_state_title(view) == i18n.SEARCH_EMPTY_TITLE
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
def test_pola_filtrow_wypelniaja_kolumny_siatki(
    make_search_view: Callable[..., SearchView],
) -> None:
    """Szerokosc pola nie moze zalezec od najdluzszej wartosci z indeksu."""
    from PySide6.QtWidgets import QSizePolicy

    view = make_search_view()
    fields = (
        view.filter_extension,
        view.filter_source,
        view.filter_library,
        view.filter_author,
        view.filter_date_from,
        view.filter_date_to,
    )
    for field in fields:
        assert field.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Expanding


@pytest.mark.gui
def test_przycisk_filtrow_liczy_aktywne_filtry(
    make_search_view: Callable[..., SearchView],
) -> None:
    """Zwiniety panel nie moze ukrywac faktu, ze wyniki sa zawezone."""
    view = make_search_view()
    assert view.filters_toggle.text() == i18n.SEARCH_FILTERS
    assert not view.clear_filters_button.isEnabled()

    view.filter_path.setText("procedury/2024")
    assert view.active_filter_count() == 1
    assert view.filters_toggle.text() == i18n.SEARCH_FILTERS_ACTIVE.format(count=1)
    assert view.clear_filters_button.isEnabled()

    view.filter_ocr.setChecked(True)
    view.filter_date_from.setDate(QDate(2015, 7, 24))
    assert view.active_filter_count() == 3
    assert view.filters_toggle.text() == i18n.SEARCH_FILTERS_ACTIVE.format(count=3)

    view.clear_filters()

    assert view.filters_toggle.text() == i18n.SEARCH_FILTERS
    assert not view.clear_filters_button.isEnabled()


@pytest.mark.gui
def test_chipy_pokazuja_aktywne_filtry_i_zdejmuja_je(
    make_search_view: Callable[..., SearchView],
) -> None:
    """Stan filtrow widac bez otwierania panelu, a chip zdejmuje jeden filtr."""
    view = make_search_view()
    assert view._chips_row.isHidden()
    assert view.filter_chips() == []

    view.filter_path.setText("procedury/2024")
    view.filter_ocr.setChecked(True)

    texts = [chip.text() for chip in view.filter_chips()]
    assert any("procedury/2024" in text for text in texts)
    assert i18n.FILTER_OCR in texts
    assert not view._chips_row.isHidden()

    path_chip = next(chip for chip in view.filter_chips() if "procedury" in chip.text())
    path_chip.click()

    assert view.filter_path.text() == ""
    assert view.active_filter_count() == 1
    assert [chip.text() for chip in view.filter_chips()] == [i18n.FILTER_OCR]

    view.clear_filters()

    assert view.filter_chips() == []
    assert view._chips_row.isHidden()


@pytest.mark.gui
def test_chip_daty_pokazuje_zakres(make_search_view: Callable[..., SearchView]) -> None:
    view = make_search_view()
    view.filter_date_from.setDate(QDate(2024, 3, 1))

    texts = [chip.text() for chip in view.filter_chips()]
    assert i18n.FILTER_DATE_FROM_CHIP.format(date="01.03.2024") in texts


@pytest.mark.gui
def test_wiersz_stron_pojawia_sie_dopiero_przy_wielu_stronach(
    qtbot: object,
    make_search_view: Callable[..., SearchView],
    result_cards: Callable[[QWidget], list[ResultCard]],
) -> None:
    """Jedna strona wynikow nie potrzebuje przyciskow przewijania stron."""
    view = make_search_view(page_size=2)
    assert view._pagination.isHidden()

    view.query_edit.setText(QUERY)
    view.run_search()
    qtbot.waitUntil(lambda: bool(result_cards(view)), timeout=TIMEOUT_MS)  # type: ignore[attr-defined]

    # Piec dokumentow po dwa na strone daje trzy strony, wiec wiersz jest potrzebny.
    assert not view._pagination.isHidden()

    view._page_size = 100
    view.run_search()
    qtbot.waitUntil(lambda: view._pagination.isHidden(), timeout=TIMEOUT_MS)  # type: ignore[attr-defined]


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
    """Nazwa pliku otwiera dokument, a przyciski ikonowe emituja swoje akcje."""
    hit = _sample_hit()
    card = ResultCard(hit, gui_palette)
    qtbot.addWidget(card)  # type: ignore[attr-defined]

    assert hit.name in card.title_label.text()
    assert card.title_label.toolTip() == i18n.RESULT_OPEN_HINT
    opened: list[object] = []
    card.open_document.connect(opened.append)
    card.title_label.linkActivated.emit("open")
    assert opened == [hit]

    for signal, button, label in (
        (card.open_location, card.location_button, i18n.RESULT_OPEN_LOCATION),
        (card.copy_link, card.copy_button, i18n.RESULT_COPY_LINK),
    ):
        assert button.toolTip() == label, "Przycisk ikonowy musi opisywac akcje podpowiedzia."
        assert not button.icon().isNull()
        received: list[object] = []
        signal.connect(received.append)

        button.click()

        assert received == [hit]


@pytest.mark.gui
def test_result_card_badges_maja_kolorowe_role(qtbot: object, gui_palette: Palette) -> None:
    """Plakietki dostaja role kolorow: dopasowanie, typ, data, autor, OCR, sila."""
    card = ResultCard(_sample_hit(), gui_palette)
    qtbot.addWidget(card)  # type: ignore[attr-defined]

    roles = {
        str(label.property("badgeRole"))
        for label in card.findChildren(QLabel)
        if label.objectName() == "Badge"
    }
    assert {"match", "type", "date", "author", "ocr", "score-high"} <= roles


def _badge_roles(card: ResultCard) -> set[str]:
    return {
        str(label.property("badgeRole"))
        for label in card.findChildren(QLabel)
        if label.objectName() == "Badge"
    }


@pytest.mark.gui
def test_karta_bez_rodzaju_dopasowania_na_zyczenie(qtbot: object, gui_palette: Palette) -> None:
    """Poza trybem hybrydowym plakietka rodzaju powtarzalaby nazwe trybu."""
    card = ResultCard(_sample_hit(), gui_palette, show_match_kind=False)
    qtbot.addWidget(card)  # type: ignore[attr-defined]

    assert "match" not in _badge_roles(card)


@pytest.mark.gui
def test_tryb_dokladny_ukrywa_plakietke_rodzaju_dopasowania(
    qtbot: object,
    make_search_view: Callable[..., SearchView],
    result_cards: Callable[[QWidget], list[ResultCard]],
) -> None:
    """Wyniki trybu dokladnego nie nosza plakietki rodzaju dopasowania."""
    view = make_search_view()
    _mode_button(view, SearchMode.EXACT).setChecked(True)
    view.query_edit.setText(QUERY)

    view.run_search()

    qtbot.waitUntil(lambda: bool(result_cards(view)), timeout=TIMEOUT_MS)  # type: ignore[attr-defined]
    assert all("match" not in _badge_roles(card) for card in result_cards(view))


def test_score_role_thresholds() -> None:
    assert score_role(0.9) == "score-high"
    assert score_role(0.5) == "score-mid"
    assert score_role(0.1) == "score-low"


def test_breadcrumb_path_pomija_nazwe_pliku_i_zwija_srodek() -> None:
    from finddocs.gui.widgets.result_card import breadcrumb_path

    assert (
        breadcrumb_path("procedury/2024/procedura.pdf", "Dokumenty", exclude_name="procedura.pdf")
        == "Dokumenty › procedury › 2024"
    )
    long_path = "a/b/c/d/e/f/g/plik.txt"
    crumbs = breadcrumb_path(long_path, None, exclude_name="plik.txt")
    assert "..." in crumbs
    assert crumbs.startswith("a › b")
    assert crumbs.endswith("f › g")
    assert breadcrumb_path("plik.txt", None, exclude_name="plik.txt") == ""


@pytest.mark.gui
def test_akcje_karty_odslaniaja_sie_przy_fokusie(qtbot: object, gui_palette: Palette) -> None:
    """W spoczynku akcje sa niewidoczne, fokus i najechanie je pokazuja."""
    from finddocs.gui.widgets.result_card import ACTIONS_HIDDEN_OPACITY

    card = ResultCard(_sample_hit(), gui_palette)
    qtbot.addWidget(card)  # type: ignore[attr-defined]
    effects = card._action_effects
    assert len(effects) == 2
    assert all(effect.opacity() == ACTIONS_HIDDEN_OPACITY for effect in effects)

    card._set_actions_revealed(True)
    assert all(effect.opacity() == 1.0 for effect in effects)

    card._set_actions_revealed(False)
    assert all(effect.opacity() == ACTIONS_HIDDEN_OPACITY for effect in effects)


@pytest.mark.gui
def test_prefiks_fragmentu_jest_plakietka_bez_nawiasow(qtbot: object, gui_palette: Palette) -> None:
    card = ResultCard(_sample_hit(), gui_palette)
    qtbot.addWidget(card)  # type: ignore[attr-defined]

    snippet = _snippets(card)[0]
    assert "strona 2" in snippet.text()
    assert "[strona" not in snippet.text()
    assert "background-color" in snippet.text()


def test_file_glyph_mapuje_rozszerzenia_na_rodziny() -> None:
    assert file_glyph(".XLSX") == "file-table"
    assert file_glyph(".pdf") == "file-text"
    assert file_glyph(".eml") == "file-mail"
    assert file_glyph(".png") == "file-image"
    assert file_glyph(".xyz") == "file-generic"


@pytest.mark.gui
def test_karta_ma_glif_rodziny_pliku(qtbot: object, gui_palette: Palette) -> None:
    """Rodzaj dokumentu widac przed przeczytaniem nazwy."""
    card = ResultCard(_sample_hit(), gui_palette)
    qtbot.addWidget(card)  # type: ignore[attr-defined]

    glyph = card.findChild(QLabel, "FileGlyph")
    assert glyph is not None
    pixmap = glyph.pixmap()
    assert pixmap is not None and not pixmap.isNull()


def _hit_with_chunks(count: int, *, total: int, sheet: str | None = None) -> DocumentHit:
    """Wynik z podana liczba fragmentow, do testow zwijania."""
    chunks = [
        ChunkHit(
            chunk_id=index + 1,
            doc_id=7,
            ordinal=index,
            text=f"Fragment {index}\nz lamaniem wiersza.",
            highlighted=f"Fragment [[hl]]{index}[[/hl]]\nz lamaniem wiersza.",
            score=0.5,
            match_kind=MatchKind.EXACT,
            origin=TextOrigin.NATIVE,
            sheet=sheet,
        )
        for index in range(count)
    ]
    hit = _sample_hit()
    hit.chunks = chunks
    hit.total_matching_chunks = total
    return hit


def _snippets(card: ResultCard) -> list[QLabel]:
    return [label for label in card.findChildren(QLabel) if label.objectName() == "Snippet"]


@pytest.mark.gui
def test_karta_zwija_fragmenty_ponad_limit(qtbot: object, gui_palette: Palette) -> None:
    """Widoczne sa najwyzej dwa fragmenty, reszte rozwija odnosnik."""
    card = ResultCard(_hit_with_chunks(3, total=9), gui_palette)
    qtbot.addWidget(card)  # type: ignore[attr-defined]

    snippets = _snippets(card)
    assert len(snippets) == 3
    assert sum(1 for s in snippets if not s.isHidden()) == VISIBLE_CHUNKS == 2
    assert card.expand_button is not None
    assert card.expand_button.text() == i18n.RESULT_SHOW_MORE.format(count=1)
    assert card.more_hint is not None
    assert card.more_hint.isHidden()

    card.expand_button.click()

    assert all(not s.isHidden() for s in _snippets(card))
    assert card.expand_button.isHidden()
    assert not card.more_hint.isHidden()
    assert card.more_hint.text() == i18n.RESULT_MORE_CHUNKS.format(count=9)


@pytest.mark.gui
def test_karta_bez_nadmiaru_nie_ma_odnosnika(qtbot: object, gui_palette: Palette) -> None:
    """Dwa fragmenty mieszcza sie w limicie, wiec odnosnik nie powstaje."""
    card = ResultCard(_hit_with_chunks(2, total=2), gui_palette)
    qtbot.addWidget(card)  # type: ignore[attr-defined]

    assert card.expand_button is None
    assert card.more_hint is None
    assert all(not s.isHidden() for s in _snippets(card))


@pytest.mark.gui
def test_proza_jest_sklejana_a_tabela_zachowuje_wiersze(
    qtbot: object, gui_palette: Palette
) -> None:
    """Lamania z ekstrakcji znikaja w prozie, fragment arkusza trzyma uklad."""
    prose = ResultCard(_hit_with_chunks(1, total=1), gui_palette)
    table = ResultCard(_hit_with_chunks(1, total=1, sheet="Dane"), gui_palette)
    qtbot.addWidget(prose)  # type: ignore[attr-defined]
    qtbot.addWidget(table)  # type: ignore[attr-defined]

    assert "<br>" not in _snippets(prose)[0].text()
    assert "<br>" in _snippets(table)[0].text()


def test_flatten_snippet_skleja_biale_znaki() -> None:
    assert flatten_snippet("a\nb\n\n  c\td") == "a b c d"


@pytest.mark.gui
def test_karta_wyniku_otwiera_dokument_z_klawiatury(qtbot: object, gui_palette: Palette) -> None:
    """Karta przyjmuje fokus, a Enter na niej otwiera dokument."""
    hit = _sample_hit()
    card = ResultCard(hit, gui_palette)
    qtbot.addWidget(card)  # type: ignore[attr-defined]
    opened: list[object] = []
    card.open_document.connect(opened.append)

    assert card.focusPolicy() == Qt.FocusPolicy.StrongFocus
    for key in (Qt.Key.Key_Return, Qt.Key.Key_Space):
        card.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))

    assert opened == [hit, hit]


@pytest.mark.gui
def test_dwuklik_w_karte_otwiera_dokument(qtbot: object, gui_palette: Palette) -> None:
    """Caly prostokat karty wyglada na klikalny, wiec musi reagowac na dwuklik."""
    hit = _sample_hit()
    card = ResultCard(hit, gui_palette)
    qtbot.addWidget(card)  # type: ignore[attr-defined]
    opened: list[object] = []
    card.open_document.connect(opened.append)

    qtbot.mouseDClick(card, Qt.MouseButton.LeftButton)  # type: ignore[attr-defined]

    assert opened == [hit]


@pytest.mark.gui
def test_plakietki_niosa_krotki_napis_i_pelne_zdanie_w_podpowiedzi(
    qtbot: object, gui_palette: Palette
) -> None:
    """Data i sila dopasowania musza byc krotkie, zeby nie zaslaniac fragmentu."""
    card = ResultCard(_sample_hit(), gui_palette)
    qtbot.addWidget(card)  # type: ignore[attr-defined]
    badges = {
        str(label.property("badgeRole")): label
        for label in card.findChildren(QLabel)
        if label.objectName() == "Badge"
    }

    assert badges["date"].text() == "2024-05-17"
    assert badges["date"].toolTip() == i18n.BADGE_MODIFIED_TOOLTIP
    assert badges["score-high"].text() == i18n.RESULT_SCORE_SHORT.format(value="75%")
    assert badges["score-high"].toolTip() == i18n.RESULT_SCORE_TOOLTIP
    assert badges["author"].text() == "Kowalski Jan"


@pytest.mark.gui
def test_search_button_toggles_between_szukaj_and_przerwij(
    make_search_view: Callable[..., SearchView],
) -> None:
    """W trakcie wyszukiwania przycisk lupy zamienia sie w Przerwij.

    Pole zapytania zostaje aktywne: blokada zabierala fokus w polowie pisania,
    a Enter w trakcie pracy i tak przerywa biezace wyszukiwanie i zleca nowe.
    """
    view = make_search_view()
    assert view.search_button.toolTip() == i18n.SEARCH_BUTTON

    view._set_busy(True)
    assert view.is_searching()
    assert view.search_button.toolTip() == i18n.SEARCH_CANCEL
    assert view.query_edit.isEnabled()
    assert view.search_button.isEnabled()

    view.cancel_search()
    assert not view.is_searching()
    assert view.search_button.toolTip() == i18n.SEARCH_BUTTON
    assert view.query_edit.isEnabled()


@pytest.mark.gui
def test_sortowanie_dostepne_tylko_w_trybie_dokladnym(
    make_search_view: Callable[..., SearchView],
) -> None:
    """Tryby wektorowe zwracaja ranking, wiec sortowanie po dacie tam nie dziala."""
    view = make_search_view()
    assert not view.sort_combo.isEnabled()

    _mode_button(view, SearchMode.EXACT).click()
    assert view.sort_combo.isEnabled()

    view.sort_combo.setCurrentIndex(view.sort_combo.findData("modified_desc"))
    assert view.current_order() == "modified_desc"

    _mode_button(view, SearchMode.HYBRID).click()
    assert not view.sort_combo.isEnabled()
    assert view.current_order() == "relevance"


@pytest.mark.gui
def test_sortowanie_po_dacie_ustawia_najnowsze_na_gorze(
    qtbot: object,
    gui_context_with_source: AppContext,
    gui_corpus: object,
    gui_palette: Palette,
    result_cards: Callable[[QWidget], list[ResultCard]],
) -> None:
    """Porzadek po dacie modyfikacji obejmuje caly zbior trafien."""
    import os
    import time as _time
    from pathlib import Path

    from finddocs.jobs.indexing_job import IndexingJob, JobOptions
    from finddocs.types import JobKind, JobState

    files = sorted(Path(str(gui_corpus)).glob("procedura-0*.txt"))
    now = _time.time()
    for offset, path in enumerate(files):
        stamp = now - 86400 * (len(files) - offset)
        os.utime(path, (stamp, stamp))
    job = IndexingJob(
        gui_context_with_source.config,
        gui_context_with_source.require_index(),
        options=JobOptions(kind=JobKind.RESCAN),
        paths=gui_context_with_source.paths,
    )
    assert job.run().state is JobState.COMPLETED

    view = SearchView(gui_context_with_source, gui_palette)
    qtbot.addWidget(view)  # type: ignore[attr-defined]
    _mode_button(view, SearchMode.EXACT).click()
    view.sort_combo.setCurrentIndex(view.sort_combo.findData("modified_desc"))
    view.query_edit.setText(QUERY)

    view.run_search()

    qtbot.waitUntil(lambda: bool(result_cards(view)), timeout=TIMEOUT_MS)  # type: ignore[attr-defined]
    dates = [card.hit.modified_at for card in result_cards(view)]
    assert all(date is not None for date in dates)
    assert dates == sorted(dates, reverse=True)  # type: ignore[type-var]


@pytest.mark.gui
def test_historia_zapytan_zasila_podpowiedzi(
    qtbot: object,
    make_search_view: Callable[..., SearchView],
    result_cards: Callable[[QWidget], list[ResultCard]],
) -> None:
    """Udane wyszukiwanie zapisuje zapytanie w podpowiedziach tej sesji."""
    view = make_search_view()
    view.query_edit.setText(QUERY)
    view.run_search()
    qtbot.waitUntil(lambda: bool(result_cards(view)), timeout=TIMEOUT_MS)  # type: ignore[attr-defined]

    assert QUERY in view._history
    assert view.query_edit.completer() is not None
    assert QUERY in view._history_model.stringList()


@pytest.mark.gui
def test_escape_czysci_pole_zapytania(make_search_view: Callable[..., SearchView]) -> None:
    view = make_search_view()
    view.query_edit.setText("cokolwiek")

    view.keyPressEvent(
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    )

    assert view.query_edit.text() == ""


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

    card.copy_button.click()

    assert clipboard.text() == expected

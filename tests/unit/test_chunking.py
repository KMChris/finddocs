"""Testy podzialu dokumentu na fragmenty.

Fragment jest jednostka indeksowania, wiec musi znac swoje pochodzenie (strona,
naglowek, wiersze tabeli) i miec komplet reprezentacji wyszukiwawczych.
"""

from __future__ import annotations

import itertools

import pytest

from finddocs.chunking import (
    ChunkingConfig,
    MixedChunkingStrategy,
    TableChunkingStrategy,
    TextChunkingStrategy,
    chunk_document,
    select_strategy,
)
from finddocs.chunking.text_chunker import split_paragraphs, split_sentences, tail_of
from finddocs.types import ExtractedSection


@pytest.fixture
def config() -> ChunkingConfig:
    """Maly rozmiar fragmentu, zeby testy nie potrzebowaly dlugich tekstow."""
    return ChunkingConfig(
        target_chars=300,
        overlap_chars=60,
        min_chars=50,
        max_chars=600,
        table_rows_per_chunk=3,
    ).clamp()


def akapity(ile: int) -> str:
    """Tekst zlozony z krotkich akapitow oddzielonych pusta linia."""
    return "\n\n".join(f"Akapit numer {i}. " + "tresc " * 20 for i in range(ile))


def wiersze_tabeli(ile: int) -> list[ExtractedSection]:
    """Sekcje tabelaryczne: arkusz, naglowek kolumn i wiersze danych."""
    sekcje = [
        ExtractedSection(text="Arkusz: Dane", kind="sheet", sheet="Dane"),
        ExtractedSection(text="Data;Kwota;Opis", kind="table_header", sheet="Dane"),
    ]
    for numer in range(1, ile + 1):
        sekcje.append(
            ExtractedSection(
                text=f"2015-07-{numer:02d};{numer * 100},00;pozycja {numer}",
                kind="table_row",
                row=numer,
                sheet="Dane",
            )
        )
    return sekcje


# --- fragmentacja tekstu -------------------------------------------------------


def test_podzial_na_fragmenty_w_zadanym_rozmiarze(config):
    sekcje = [ExtractedSection(text=akapity(6), page=1, heading="Rozdzial I")]
    fragmenty = list(TextChunkingStrategy(config).chunk(sekcje))

    assert len(fragmenty) > 1
    assert [f.ordinal for f in fragmenty] == list(range(len(fragmenty)))
    for fragment in fragmenty:
        assert fragment.text
        assert len(fragment.text) <= config.target_chars


def test_fragmenty_nakladaja_sie_na_siebie(config):
    sekcje = [ExtractedSection(text=akapity(6), page=1)]
    fragmenty = list(TextChunkingStrategy(config).chunk(sekcje))

    assert len(fragmenty) >= 2
    for poprzedni, nastepny in itertools.pairwise(fragmenty):
        naklodka = tail_of(poprzedni.text, config.overlap_chars)
        assert naklodka
        assert nastepny.text.startswith(naklodka)


def test_brak_nakladania_gdy_overlap_zerowy():
    config = ChunkingConfig(target_chars=300, overlap_chars=0, min_chars=50).clamp()
    fragmenty = list(TextChunkingStrategy(config).chunk([ExtractedSection(text=akapity(6))]))
    assert len(fragmenty) >= 2
    for poprzedni, nastepny in itertools.pairwise(fragmenty):
        assert not nastepny.text.startswith(poprzedni.text[-20:])


def test_fragment_zachowuje_numer_strony_i_naglowek(config):
    sekcje = [
        ExtractedSection(
            text=f"Tekst strony {numer}. " + "abc " * 40,
            page=numer,
            heading=f"Naglowek {numer}",
        )
        for numer in (1, 2, 3)
    ]
    fragmenty = list(TextChunkingStrategy(config).chunk(sekcje))

    assert len(fragmenty) == 3
    assert [f.page for f in fragmenty] == [1, 2, 3]
    assert [f.heading for f in fragmenty] == ["Naglowek 1", "Naglowek 2", "Naglowek 3"]


def test_naglowek_trafia_do_tekstu_wyszukiwawczego_ale_nie_do_prezentowanego(config):
    sekcje = [ExtractedSection(text="Tresc rozdzialu. " * 10, page=4, heading="Rozdzial IV")]
    fragment = next(iter(TextChunkingStrategy(config).chunk(sekcje)))

    assert "Rozdzial IV" not in fragment.text
    assert "rozdzial iv" in fragment.search_text
    assert fragment.heading == "Rozdzial IV"


def test_bardzo_dlugi_akapit_dzielony_na_granicy_zdania(config):
    dlugi = " ".join(f"Zdanie numer {i} konczy sie kropka." for i in range(60))
    assert len(dlugi) > config.max_chars

    fragmenty = list(TextChunkingStrategy(config).chunk([ExtractedSection(text=dlugi, page=2)]))

    assert len(fragmenty) > 1
    for fragment in fragmenty:
        # Kazdy fragment konczy sie pelnym zdaniem, nie w polowie wyrazu.
        assert fragment.text.endswith("kropka.")
        assert len(fragment.text) <= config.max_chars


def test_zmiana_strony_konczy_fragment(config):
    sekcje = [
        ExtractedSection(text="Pierwsza strona. " * 8, page=1),
        ExtractedSection(text="Druga strona. " * 8, page=2),
    ]
    fragmenty = list(TextChunkingStrategy(config).chunk(sekcje))

    assert len(fragmenty) == 2
    assert "Druga strona." not in fragmenty[0].text
    assert fragmenty[1].page == 2


def test_puste_sekcje_nie_tworza_fragmentow(config):
    fragmenty = list(
        TextChunkingStrategy(config).chunk(
            [ExtractedSection(text="   "), ExtractedSection(text="\n\n")]
        )
    )
    assert fragmenty == []


def test_split_sentences_i_split_paragraphs():
    assert split_sentences("Pierwsze zdanie. Drugie zdanie! Trzecie? 4 czwarte.") == [
        "Pierwsze zdanie.",
        "Drugie zdanie!",
        "Trzecie?",
        "4 czwarte.",
    ]
    assert split_paragraphs("Pierwszy\n\nDrugi\n \nTrzeci") == ["Pierwszy", "Drugi", "Trzeci"]


def test_tail_of_przycina_do_granicy_slowa():
    # Naklodka nigdy nie zaczyna sie w polowie wyrazu. Gdy ciecie wypada wewnatrz
    # slowa (albo dokladnie na jego poczatku), funkcja przesuwa sie do nastepnej spacji.
    assert tail_of("Alfa beta gamma delta", 12) == "gamma delta"
    assert tail_of("Alfa beta gamma delta", 8) == "delta"
    assert tail_of("krotki", 100) == "krotki"
    assert tail_of("cokolwiek", 0) == ""
    assert tail_of("", 10) == ""


# --- fragmentacja tabel --------------------------------------------------------


def test_naglowek_kolumn_dolaczony_do_kazdego_fragmentu(config):
    fragmenty = list(TableChunkingStrategy(config).chunk(wiersze_tabeli(7)))

    assert len(fragmenty) == 3
    for fragment in fragmenty:
        assert "Data;Kwota;Opis" in fragment.text
        assert fragment.heading == "Data;Kwota;Opis"
        assert fragment.sheet == "Dane"
        assert fragment.section_kind == "table_row"


def test_grupowanie_po_table_rows_per_chunk(config):
    fragmenty = list(TableChunkingStrategy(config).chunk(wiersze_tabeli(7)))

    # Siedem wierszy przy trzech wierszach na fragment: 3 + 3 + 1.
    assert [(f.row_start, f.row_end) for f in fragmenty] == [(1, 3), (4, 6), (7, 7)]


def test_kazdy_wiersz_trafia_do_dokladnie_jednego_fragmentu(config):
    fragmenty = list(TableChunkingStrategy(config).chunk(wiersze_tabeli(7)))
    for numer in range(1, 8):
        trafienia = [f for f in fragmenty if f"pozycja {numer}" in f.text]
        assert len(trafienia) == 1


def test_naglowek_bez_wierszy_nie_tworzy_fragmentu(config):
    sekcje = [ExtractedSection(text="Data;Kwota", kind="table_header")]
    assert list(TableChunkingStrategy(config).chunk(sekcje)) == []


def test_bez_naglowka_gdy_wylaczony_w_konfiguracji():
    config = ChunkingConfig(table_rows_per_chunk=3, table_include_header=False).clamp()
    fragmenty = list(TableChunkingStrategy(config).chunk(wiersze_tabeli(3)))
    assert len(fragmenty) == 1
    assert "Data;Kwota;Opis" not in fragmenty[0].text


def test_strategia_tabelaryczna_dla_rozszerzenia_csv(config):
    strategia = select_strategy([ExtractedSection(text="a;b")], config, extension=".csv")
    assert isinstance(strategia, TableChunkingStrategy)


# --- dokument mieszany ---------------------------------------------------------


def dokument_mieszany() -> list[ExtractedSection]:
    """Cztery sekcje tekstowe i trzy tabelaryczne: udzial tabel ponizej progu."""
    return [
        ExtractedSection(text="Wstep do dokumentu. " * 8, kind="text", page=1),
        ExtractedSection(text="Drugi akapit tekstu. " * 8, kind="text", page=1),
        ExtractedSection(text="Kolumna A;Kolumna B", kind="table_header"),
        ExtractedSection(text="1;2", kind="table_row", row=1),
        ExtractedSection(text="3;4", kind="table_row", row=2),
        ExtractedSection(text="Podsumowanie tekstowe. " * 8, kind="text", page=2),
        ExtractedSection(text="Zakonczenie dokumentu. " * 8, kind="text", page=2),
    ]


def test_dokument_mieszany_uzywa_strategii_mieszanej(config):
    strategia = select_strategy(dokument_mieszany(), config)
    assert isinstance(strategia, MixedChunkingStrategy)
    assert strategia.name == "mixed"


def test_dokument_mieszany_ma_ciagla_numeracje_fragmentow(config):
    fragmenty = chunk_document(dokument_mieszany(), config)

    assert len(fragmenty) >= 3
    assert [f.ordinal for f in fragmenty] == list(range(len(fragmenty)))
    rodzaje = {f.section_kind for f in fragmenty}
    assert rodzaje == {"text", "table_row"}


def test_dokument_mieszany_zachowuje_kolejnosc_sekcji(config):
    fragmenty = chunk_document(dokument_mieszany(), config)
    tabelaryczny = next(f for f in fragmenty if f.section_kind == "table_row")

    assert fragmenty[0].section_kind == "text"
    assert "Wstep do dokumentu." in fragmenty[0].text
    assert tabelaryczny.row_start == 1
    assert tabelaryczny.row_end == 2
    assert fragmenty[-1].section_kind == "text"


# --- reprezentacje wyszukiwawcze -----------------------------------------------


@pytest.mark.parametrize(
    "sekcje",
    [
        [ExtractedSection(text="Oddzial w miescie Łódź. " * 10, page=1, heading="Naglowek")],
        wiersze_tabeli(7),
        dokument_mieszany(),
    ],
)
def test_kazdy_fragment_ma_komplet_reprezentacji(sekcje, config):
    for fragment in chunk_document(list(sekcje), config):
        assert fragment.text.strip()
        assert fragment.search_text.strip()
        assert fragment.folded_text.strip()
        assert fragment.char_end >= fragment.char_start


def test_folded_text_sklada_polskie_znaki(config):
    sekcje = [ExtractedSection(text="Oddzial w miescie Łódź obsluguje klientow. " * 5, page=1)]
    fragment = chunk_document(sekcje, config)[0]

    assert "Łódź" in fragment.text
    assert "łódź" in fragment.search_text
    assert "lodz" in fragment.folded_text


def test_tokeny_znormalizowane_trafiaja_do_fragmentu(config):
    sekcje = [
        ExtractedSection(
            text="Przelew z dnia 24.07.2015 na rachunek 01 2345 6789, kwota 314 zl. " * 3,
            page=1,
        )
    ]
    fragment = chunk_document(sekcje, config)[0]
    tokeny = fragment.normalized_tokens.split()

    assert "dat20150724" in tokeny
    assert "num0123456789" in tokeny
    assert "kwo31400" in tokeny

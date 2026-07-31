"""Testy regresyjne parserow tekstowych: pliki czysto tekstowe, HTML i RTF.

Kazdy test buduje plik od zera, wiec repozytorium nie zawiera zadnych binariow.
Wspolny motyw sprawdzenia to zachowanie polskich znakow niezaleznie od kodowania
zrodla, bo wlasnie tam parsery najlatwiej zawodza.
"""

from __future__ import annotations

import codecs
from collections.abc import Callable
from pathlib import Path

import pytest
from parser_data import DISCLAIMER, POLISH_LETTERS, POLISH_SAMPLE, assert_polish

from finddocs.errors import EmptyDocumentError
from finddocs.extractors.base import ExtractionContext
from finddocs.extractors.html_text import HtmlExtractor, html_to_text
from finddocs.extractors.rtf import RtfExtractor, rtf_to_text
from finddocs.extractors.text import PlainTextExtractor
from finddocs.types import SupportLevel, TextOrigin

#: Tresc uzywana w wiekszosci testow plikow tekstowych.
SAMPLE_TEXT = (
    f"Notatka sluzbowa. {POLISH_SAMPLE}.\n"
    "\n"
    f"Drugi akapit notatki. {DISCLAIMER}\n"
    "Rachunek 00 1234 5678 9012 3456 7890 1234, kwota 1 234,56 PLN.\n"
)


# --- pliki czysto tekstowe -------------------------------------------------------


def test_txt_dzieli_tekst_na_akapity(
    make_text: Callable[..., Path], context: ExtractionContext
) -> None:
    """Pusta linia jest granica sekcji, a tresc zachowuje polskie znaki."""
    path = make_text("notatka.txt", SAMPLE_TEXT)

    result = PlainTextExtractor().extract(path, context)

    assert len(result.sections) == 2
    assert result.parser_name == "text"
    assert result.support_level is SupportLevel.FULL
    assert result.origin is TextOrigin.NATIVE
    assert result.needs_ocr is False
    assert_polish(result.all_text())
    assert "1 234,56 PLN" in result.all_text()


@pytest.mark.parametrize(
    ("encoding", "name"),
    [
        ("utf-8", "utf8.txt"),
        ("utf-8-sig", "utf8-bom.txt"),
        ("cp1250", "cp1250.txt"),
        ("iso-8859-2", "iso2.txt"),
        ("utf-16", "utf16.txt"),
    ],
)
def test_txt_kodowania(
    make_text: Callable[..., Path], context: ExtractionContext, encoding: str, name: str
) -> None:
    """Polskie znaki wracaja poprawnie z kazdego obslugiwanego kodowania."""
    path = make_text(name, f"{POLISH_SAMPLE}\n\n{POLISH_LETTERS}\n", encoding=encoding)

    result = PlainTextExtractor().extract(path, context)

    text = result.all_text()
    assert_polish(text)
    assert POLISH_LETTERS in text


def test_txt_znacznik_bom_nie_trafia_do_tresci(
    make_text: Callable[..., Path], context: ExtractionContext
) -> None:
    """Znak BOM nie moze pojawic sie w indeksowanym tekscie."""
    path = make_text("bom.txt", f"{POLISH_SAMPLE}\n", encoding="utf-8-sig")

    result = PlainTextExtractor().extract(path, context)

    assert codecs.BOM_UTF8.decode("utf-8") not in result.all_text()
    assert result.all_text().startswith(POLISH_SAMPLE)


def test_txt_pusty_plik_konczy_sie_wyjatkiem(
    make_text: Callable[..., Path], context: ExtractionContext
) -> None:
    """Plik bez tresci to nie jest blad parsera, tylko dokument pusty."""
    path = make_text("pusty.txt", "   \n\n\t\n")

    with pytest.raises(EmptyDocumentError):
        PlainTextExtractor().extract(path, context)


def test_txt_limit_znakow_konczy_sie_ostrzezeniem(
    make_text: Callable[..., Path],
) -> None:
    """Po przekroczeniu limitu parser tnie tresc i zglasza to w ostrzezeniach."""
    path = make_text("dlugi.txt", "\n\n".join(f"Akapit {i}. {POLISH_SAMPLE}." for i in range(400)))
    limited = ExtractionContext(max_chars=500)

    result = PlainTextExtractor().extract(path, limited)

    assert sum(len(section.text) for section in result.sections) <= 500
    assert any("limit" in warning for warning in result.warnings)


def test_txt_plik_bez_pustych_linii_dzieli_sie_na_bloki(
    make_text: Callable[..., Path], context: ExtractionContext
) -> None:
    """Tekst bez akapitow jest ciety na bloki, zawsze na granicy nowej linii."""
    path = make_text(
        "log.log", "\n".join(f"2024-03-15 wpis {i} {POLISH_SAMPLE}" for i in range(600))
    )

    result = PlainTextExtractor().extract(path, context)

    assert len(result.sections) > 1
    assert all(section.text for section in result.sections)


def test_txt_obsluguje_rozszerzenia_strukturalne() -> None:
    """Parser deklaruje rozszerzenia plikow konfiguracyjnych i danych."""
    extractor = PlainTextExtractor()

    for suffix in (".txt", ".log", ".md", ".json", ".xml", ".ini", ".yaml"):
        assert extractor.supports(Path(f"plik{suffix}"), None) is True
    assert extractor.supports(Path("plik.docx"), None) is False


# --- HTML ------------------------------------------------------------------------


def _html_document(body: str, *, charset: str = "utf-8", title: str = "Procedura") -> str:
    return (
        "<!DOCTYPE html><html lang='pl'><head>"
        f"<meta charset='{charset}'>"
        f"<title>{title}</title>"
        "<meta name='author' content='Łucja Żółw'>"
        "<meta name='description' content='Opis procedury'>"
        "<meta name='keywords' content='przelew, procedura'>"
        "<style>p { color: red; }</style>"
        "<script>var ukryte = 'nie indeksuj';</script>"
        f"</head><body>{body}</body></html>"
    )


def test_html_wyciaga_akapity_i_metadane(
    make_text: Callable[..., Path], context: ExtractionContext
) -> None:
    """Tytul, autor i slowa kluczowe trafiaja do metadanych, skrypty do kosza."""
    body = f"<h1>Naglowek</h1><p>{POLISH_SAMPLE}</p><p>{DISCLAIMER}</p>"
    path = make_text("strona.html", _html_document(body))

    result = HtmlExtractor().extract(path, context)

    assert result.metadata.title == "Procedura"
    assert result.metadata.author == "Łucja Żółw"
    assert result.metadata.keywords == "przelew, procedura"
    text = result.all_text()
    assert_polish(text)
    assert "nie indeksuj" not in text
    assert "color: red" not in text


def test_html_naglowek_jest_przypisany_do_akapitu(
    make_text: Callable[..., Path], context: ExtractionContext
) -> None:
    """Akapit pod naglowkiem pamieta, w jakiej sekcji dokumentu sie znajdowal."""
    body = (
        "<h1>Rozdzial pierwszy</h1>"
        f"<p>{POLISH_SAMPLE}</p>"
        "<h2>Rozdzial drugi</h2>"
        f"<p>{DISCLAIMER}</p>"
    )
    path = make_text("rozdzialy.html", _html_document(body))

    result = HtmlExtractor().extract(path, context)

    headings = [section.heading for section in result.sections if section.heading]
    assert "Rozdzial pierwszy" in headings
    assert "Rozdzial drugi" in headings


def test_html_tabela_zachowuje_komorki(
    make_text: Callable[..., Path], context: ExtractionContext
) -> None:
    """Komorki tabeli nie moga sie skleic w jeden ciag znakow."""
    body = (
        "<table><tr><th>Opis</th><th>Kwota</th></tr>"
        "<tr><td>Wpłata gotówkowa</td><td>1 234,56</td></tr></table>"
    )
    path = make_text("tabela.html", _html_document(body))

    result = HtmlExtractor().extract(path, context)

    text = result.all_text(" ")
    assert "Wpłata gotówkowa" in text
    assert "1 234,56" in text
    assert "gotówkowa1" not in text


def test_html_encje_sa_rozwijane(
    make_text: Callable[..., Path], context: ExtractionContext
) -> None:
    """Encje HTML zamieniaja sie na znaki, takze te spoza ASCII."""
    body = "<p>Za&#380;&oacute;&lstrok;&cacute; g&eogon;&sacute;l&aogon; ja&zacute;&nacute;</p>"
    path = make_text("encje.html", _html_document(body))

    result = HtmlExtractor().extract(path, context)

    assert_polish(result.all_text())


def test_html_cp1250_bez_deklaracji_meta(
    make_text: Callable[..., Path], context: ExtractionContext
) -> None:
    """Kodowanie zadeklarowane w naglowku meta jest respektowane."""
    document = _html_document(f"<p>{POLISH_SAMPLE}</p>", charset="windows-1250")
    path = make_text("cp1250.html", document, encoding="cp1250")

    result = HtmlExtractor().extract(path, context)

    assert_polish(result.all_text())


def test_html_pusty_dokument_konczy_sie_wyjatkiem(
    make_text: Callable[..., Path], context: ExtractionContext
) -> None:
    """Dokument zlozony z samych skryptow nie ma tresci do zaindeksowania."""
    path = make_text("pusty.html", _html_document("<script>var a = 1;</script>"))

    with pytest.raises(EmptyDocumentError):
        HtmlExtractor().extract(path, context)


def test_html_to_text_dziala_na_napisie() -> None:
    """Funkcja pomocnicza sluzy takze do czesci HTML wiadomosci e-mail."""
    text = html_to_text(f"<div><p>{POLISH_SAMPLE}</p><p>{DISCLAIMER}</p></div>")

    assert POLISH_SAMPLE in text
    assert DISCLAIMER in text


# --- RTF -------------------------------------------------------------------------


def test_rtf_odczytuje_tekst_w_cp1250(
    make_rtf: Callable[..., Path], context: ExtractionContext
) -> None:
    """Dokument zapisany w cp1250 wraca z poprawnymi polskimi znakami."""
    path = make_rtf()

    result = RtfExtractor().extract(path, context)

    assert result.parser_name == "rtf"
    assert result.support_level is SupportLevel.GOOD
    assert result.needs_ocr is False
    assert_polish(result.all_text())
    assert DISCLAIMER in result.all_text()


def test_rtf_kazdy_akapit_to_osobna_sekcja(
    make_rtf: Callable[..., Path], context: ExtractionContext
) -> None:
    """Akapity zrodla nie sklejaja sie w jeden blok tekstu."""
    akapity = [f"Akapit numer {index}. {POLISH_SAMPLE}." for index in range(1, 5)]
    path = make_rtf("wiele.rtf", paragraphs=akapity)

    result = RtfExtractor().extract(path, context)

    text = result.all_text("\n")
    for akapit in akapity:
        assert akapit in text


def test_rtf_pusty_dokument_konczy_sie_wyjatkiem(
    write_file: Callable[[str, bytes], Path], context: ExtractionContext
) -> None:
    """Plik RTF bez tresci jest zglaszany jako dokument pusty."""
    path = write_file("pusty.rtf", rb"{\rtf1\ansi\ansicpg1250\deff0}")

    with pytest.raises(EmptyDocumentError):
        RtfExtractor().extract(path, context)


def test_rtf_to_text_pomija_grupy_sterujace() -> None:
    """Grupy takie jak fonttbl i colortbl nie moga trafic do tekstu."""
    source = (
        r"{\rtf1\ansi\ansicpg1250\deff0"
        r"{\fonttbl{\f0\fnil Arial;}}"
        r"{\colortbl;\red0\green0\blue0;}"
        r"{\*\generator FindDocs test;}"
        r"Tresc wlasciwa dokumentu.\par}"
    )

    text = rtf_to_text(source.encode("cp1250"))

    assert "Tresc wlasciwa dokumentu." in text
    assert "fonttbl" not in text
    assert "Arial" not in text
    assert "FindDocs test" not in text

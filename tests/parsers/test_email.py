"""Testy regresyjne parserow wiadomosci e-mail: EML oraz Outlook MSG.

Wiadomosc jest dokumentem zlozonym: ma naglowek, tresc w jednej albo dwoch
wersjach (tekst i HTML) oraz zalaczniki, ktore aplikacja indeksuje jako osobne
dokumenty podrzedne. Testy sprawdzaja wszystkie trzy warstwy.
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Callable
from pathlib import Path

import pytest
from parser_data import (
    DISCLAIMER,
    POLISH_SAMPLE,
    assert_polish,
    build_uncompressed_rtf_stream,
    compress_rtf_lzfu,
)

from finddocs.errors import CorruptedFileError, EmptyDocumentError
from finddocs.extractors.base import ExtractionContext
from finddocs.extractors.eml import EmlExtractor
from finddocs.extractors.msg import MsgExtractor
from finddocs.types import SupportLevel, TextOrigin

#: Typy wlasciwosci MAPI uzywane przy budowie plikow MSG.
PT_UNICODE = 0x001F
PT_BINARY = 0x0102

#: Identyfikatory wlasciwosci MAPI uzywane w testach.
PID_SUBJECT = 0x0037
PID_DISPLAY_TO = 0x0E04
PID_SENDER_NAME = 0x0C1A
PID_BODY = 0x1000
PID_BODY_HTML = 0x1013
PID_RTF_COMPRESSED = 0x1009
PID_ATTACH_DATA = 0x3701
PID_ATTACH_LONG_FILENAME = 0x3707


def _unicode(value: str) -> bytes:
    return value.encode("utf-16-le")


# --- EML -------------------------------------------------------------------------


def test_eml_naglowek_tresc_i_metadane(
    make_eml: Callable[..., Path], context: ExtractionContext
) -> None:
    """Naglowek trafia do osobnej sekcji, a pola Od, Do i Temat do metadanych."""
    path = make_eml(plain=f"Dzien dobry.\n\n{POLISH_SAMPLE}\n\n{DISCLAIMER}\n")

    result = EmlExtractor().extract(path, context)

    assert result.parser_name == "eml"
    assert result.support_level is SupportLevel.FULL
    assert result.origin is TextOrigin.NATIVE
    assert result.sections[0].kind == "email_header"
    assert "Temat: Umowa: Zażółć gęślą jaźń" in result.sections[0].text
    assert result.metadata.title == "Umowa: Zażółć gęślą jaźń"
    assert result.metadata.author is not None
    assert "lucja@example.test" in result.metadata.author
    assert result.metadata.extra["to"] is not None
    assert isinstance(result.metadata.created_at, _dt.datetime)
    assert_polish(result.all_text())


def test_eml_tresc_tekstowa_ma_pierwszenstwo_przed_html(
    make_eml: Callable[..., Path], context: ExtractionContext
) -> None:
    """Gdy sa obie wersje tresci, indeksujemy tekst czysty, nie znaczniki HTML."""
    path = make_eml(
        plain=f"Wersja tekstowa. {POLISH_SAMPLE}\n",
        html=f"<html><body><p>Wersja HTML. {DISCLAIMER}</p></body></html>",
    )

    result = EmlExtractor().extract(path, context)

    text = result.all_text()
    assert "Wersja tekstowa." in text
    assert "<p>" not in text


def test_eml_sama_tresc_html_jest_zamieniana_na_tekst(
    make_eml: Callable[..., Path], context: ExtractionContext
) -> None:
    """Wiadomosc bez czesci tekstowej wciaz da sie zaindeksowac."""
    path = make_eml(
        "tylko-html.eml",
        html=f"<html><body><h1>Naglowek</h1><p>{POLISH_SAMPLE}</p></body></html>",
    )

    result = EmlExtractor().extract(path, context)

    text = result.all_text()
    assert_polish(text)
    assert "<h1>" not in text


def test_eml_zalaczniki_sa_wyciagane(
    make_eml: Callable[..., Path], context: ExtractionContext
) -> None:
    """Zalacznik trafia na liste do osobnego zaindeksowania i zostawia notatke."""
    path = make_eml(
        plain="W zalaczeniu przesylam dokumenty.\n",
        attachments=[
            ("zestawienie.csv", "text/csv", b"opis;kwota\nwplata;1234,56\n"),
            ("notatka.txt", "text/plain", f"{DISCLAIMER}\n".encode()),
        ],
    )

    result = EmlExtractor().extract(path, context)

    names = [attachment.name for attachment in result.attachments]
    assert names == ["zestawienie.csv", "notatka.txt"]
    assert result.attachments[0].mime_type == "text/csv"
    assert b"1234,56" in result.attachments[0].data
    notes = [s.text for s in result.sections if s.kind == "attachment_note"]
    assert any("zestawienie.csv" in note for note in notes)


def test_eml_zalaczniki_mozna_wylaczyc(make_eml: Callable[..., Path]) -> None:
    """Konfiguracja bez zalacznikow nie wyciaga ich z wiadomosci."""
    path = make_eml(
        plain="Tresc wiadomosci.\n",
        attachments=[("raport.txt", "text/plain", b"dane")],
    )
    bez_zalacznikow = ExtractionContext(extract_attachments=False)

    result = EmlExtractor().extract(path, bez_zalacznikow)

    assert result.attachments == []


def test_eml_wiadomosc_zagniezdzona_jest_zalacznikiem(
    make_eml: Callable[..., Path], context: ExtractionContext
) -> None:
    """Przekazana wiadomosc jest traktowana jak zalacznik, a nie gubiona."""
    path = make_eml("przekazana.eml", plain="Przekazuje dalej.\n", nested=True)

    result = EmlExtractor().extract(path, context)

    assert result.attachments
    assert any(b"Tre" in attachment.data for attachment in result.attachments)


def test_eml_bez_tresci_i_zalacznikow_konczy_sie_wyjatkiem(
    make_eml: Callable[..., Path], context: ExtractionContext
) -> None:
    """Wiadomosc bez tresci nie ma czego zaindeksowac."""
    path = make_eml("pusta.eml", plain="")

    with pytest.raises(EmptyDocumentError):
        EmlExtractor().extract(path, context)


def test_eml_polskie_znaki_w_temacie_sa_dekodowane(
    make_eml: Callable[..., Path], context: ExtractionContext
) -> None:
    """Temat zakodowany zgodnie z RFC 2047 wraca jako czytelny tekst."""
    path = make_eml("temat.eml", subject=f"Pismo: {POLISH_SAMPLE}", plain="Tresc.\n")

    result = EmlExtractor().extract(path, context)

    assert result.metadata.title == f"Pismo: {POLISH_SAMPLE}"


def test_eml_uszkodzony_plik_konczy_sie_wyjatkiem(
    write_file: Callable[[str, bytes], Path], context: ExtractionContext
) -> None:
    """Losowe bajty z rozszerzeniem eml nie sa poprawna wiadomoscia."""
    path = write_file("smieci.eml", bytes(range(256)) * 8)

    with pytest.raises((CorruptedFileError, EmptyDocumentError)):
        EmlExtractor().extract(path, context)


# --- MSG -------------------------------------------------------------------------


def test_msg_odczytuje_temat_nadawce_i_tresc(
    make_msg: Callable[..., Path], context: ExtractionContext
) -> None:
    """Podstawowe wlasciwosci MAPI trafiaja do naglowka i metadanych."""
    path = make_msg(
        properties={
            (PID_SUBJECT, PT_UNICODE): _unicode(f"Umowa: {POLISH_SAMPLE}"),
            (PID_DISPLAY_TO, PT_UNICODE): _unicode("Michał Wąsik"),
            (PID_SENDER_NAME, PT_UNICODE): _unicode("Łucja Żółw"),
            (PID_BODY, PT_UNICODE): _unicode(f"Dzien dobry.\n\n{POLISH_SAMPLE}\n{DISCLAIMER}\n"),
        }
    )

    result = MsgExtractor().extract(path, context)

    assert result.parser_name == "msg"
    assert result.support_level is SupportLevel.GOOD
    assert result.sections[0].kind == "email_header"
    assert result.metadata.title == f"Umowa: {POLISH_SAMPLE}"
    assert_polish(result.all_text())
    assert DISCLAIMER in result.all_text()


def test_msg_tresc_html_gdy_brak_wersji_tekstowej(
    make_msg: Callable[..., Path], context: ExtractionContext
) -> None:
    """Wiadomosc z sama wersja HTML jest zamieniana na tekst."""
    html = f"<html><body><p>{POLISH_SAMPLE}</p><p>{DISCLAIMER}</p></body></html>"
    path = make_msg(
        "html.msg",
        properties={
            (PID_SUBJECT, PT_UNICODE): _unicode("Wiadomosc HTML"),
            (PID_BODY_HTML, PT_BINARY): html.encode("utf-8"),
        },
    )

    result = MsgExtractor().extract(path, context)

    text = result.all_text()
    assert_polish(text)
    assert "<p>" not in text


@pytest.mark.parametrize("compressed", [False, True])
def test_msg_tresc_rtf_w_obu_wariantach_strumienia(
    make_msg: Callable[..., Path], context: ExtractionContext, compressed: bool
) -> None:
    """Strumien PR_RTF_COMPRESSED wystepuje w wersji spakowanej i nieskompresowanej."""
    rtf = (
        rb"{\rtf1\ansi\ansicpg1250\deff0 Tresc wiadomosci w formacie RTF. "
        rb"Numer sprawy 2015-07-24.\par}"
    )
    stream = compress_rtf_lzfu(rtf) if compressed else build_uncompressed_rtf_stream(rtf)
    path = make_msg(
        f"rtf-{compressed}.msg",
        properties={
            (PID_SUBJECT, PT_UNICODE): _unicode("Wiadomosc RTF"),
            (PID_RTF_COMPRESSED, PT_BINARY): stream,
        },
    )

    result = MsgExtractor().extract(path, context)

    assert "Tresc wiadomosci w formacie RTF." in result.all_text()


def test_msg_zalaczniki_sa_wyciagane(
    make_msg: Callable[..., Path], context: ExtractionContext
) -> None:
    """Zalacznik ze skladnicy __attach_version1.0_# trafia na liste wyniku."""
    path = make_msg(
        "z-zalacznikiem.msg",
        properties={
            (PID_SUBJECT, PT_UNICODE): _unicode("Wiadomosc z zalacznikiem"),
            (PID_BODY, PT_UNICODE): _unicode("W zalaczeniu przesylam zestawienie.\n"),
        },
        attachments=[
            {
                (PID_ATTACH_LONG_FILENAME, PT_UNICODE): _unicode("zestawienie.csv"),
                (PID_ATTACH_DATA, PT_BINARY): b"opis;kwota\nwplata;1234,56\n",
            }
        ],
    )

    result = MsgExtractor().extract(path, context)

    assert [attachment.name for attachment in result.attachments] == ["zestawienie.csv"]
    assert b"1234,56" in result.attachments[0].data


def test_msg_zalaczniki_mozna_wylaczyc(make_msg: Callable[..., Path]) -> None:
    """Wylaczone zalaczniki zostawiaja ostrzezenie, a nie ciche pominiecie."""
    path = make_msg(
        "bez-zalacznikow.msg",
        properties={
            (PID_SUBJECT, PT_UNICODE): _unicode("Wiadomosc"),
            (PID_BODY, PT_UNICODE): _unicode("Tresc wiadomosci.\n"),
        },
        attachments=[
            {
                (PID_ATTACH_LONG_FILENAME, PT_UNICODE): _unicode("raport.txt"),
                (PID_ATTACH_DATA, PT_BINARY): b"dane",
            }
        ],
    )

    result = MsgExtractor().extract(path, ExtractionContext(extract_attachments=False))

    assert result.attachments == []
    assert any("pominięte" in warning for warning in result.warnings)


def test_msg_plik_nie_bedacy_kontenerem_ole(
    write_file: Callable[[str, bytes], Path], context: ExtractionContext
) -> None:
    """Plik z rozszerzeniem msg, ktory nie jest OLE, jest zglaszany jako uszkodzony."""
    path = write_file("nie-ole.msg", b"To nie jest kontener OLE." * 40)

    with pytest.raises(CorruptedFileError):
        MsgExtractor().extract(path, context)


def test_msg_pusta_wiadomosc_konczy_sie_wyjatkiem(
    make_msg: Callable[..., Path], context: ExtractionContext
) -> None:
    """Brak tematu, tresci i zalacznikow to dokument pusty."""
    path = make_msg("pusta.msg", properties={})

    with pytest.raises((EmptyDocumentError, CorruptedFileError)):
        MsgExtractor().extract(path, context)

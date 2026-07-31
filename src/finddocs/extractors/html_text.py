"""Parser dokumentow HTML i XHTML oparty o ``html.parser`` z biblioteki standardowej.

Adapter nie dodaje zadnych zaleznosci. Zawartosc znacznikow ``script``, ``style``,
``head`` i ``noscript`` jest pomijana, a tekst dzielony na akapity wedlug typowych
znacznikow blokowych. Naglowki ``h1``..``h6`` sa zapamietywane i przypisywane
kolejnym akapitom jako pole ``heading``, dzieki czemu fragmentacja zachowuje kontekst.

Modul udostepnia takze funkcje ``html_to_text``, uzywana przez parser wiadomosci
e-mail dla czesci ``text/html``.
"""

from __future__ import annotations

import codecs
import re
from collections import Counter
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

from finddocs.errors import CorruptedFileError, EmptyDocumentError, ExtractionError
from finddocs.extractors.base import ExtractionContext, Extractor
from finddocs.extractors.encoding import DecodedText, decode_text
from finddocs.normalization.text import clean_text, looks_like_garbage
from finddocs.types import (
    DocumentMetadata,
    ExtractedSection,
    ExtractionResult,
    SupportLevel,
    TextOrigin,
)

#: Znaczniki, ktorych zawartosc nie jest tekstem dokumentu.
SKIPPED_TAGS: frozenset[str] = frozenset({"script", "style", "head", "noscript", "template"})

#: Znaczniki konczace akapit.
PARAGRAPH_TAGS: frozenset[str] = frozenset({"p", "div", "br", "li", "tr", "table", "section"})

#: Znaczniki naglowkow, ktore dodatkowo ustawiaja kontekst dla kolejnych akapitow.
HEADING_TAGS: frozenset[str] = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})

#: Znaczniki, ktore w obrebie jednego akapitu wymagaja odstepu miedzy tekstem.
SPACER_TAGS: frozenset[str] = frozenset({"td", "th"})

#: Nazwy znacznikow ``meta``, ktore trafiaja do metadanych dokumentu.
META_NAMES: frozenset[str] = frozenset({"author", "description", "keywords"})

#: Ile pierwszych bajtow pliku przeszukujemy w poszukiwaniu deklaracji kodowania.
CHARSET_SNIFF_BYTES: int = 4096

#: Co ile akapitow sprawdzamy anulowanie i limit czasu.
CHECKPOINT_EVERY: int = 16

_META_CHARSET_RE = re.compile(
    rb"""<meta[^>]{0,400}?charset\s*=\s*["']?\s*([A-Za-z0-9_.:+-]{2,40})""",
    re.IGNORECASE,
)
_XML_ENCODING_RE = re.compile(
    rb"""<\?xml[^>]{0,200}?encoding\s*=\s*["']([A-Za-z0-9_.:+-]{2,40})["']""",
    re.IGNORECASE,
)
_TAG_RE = re.compile(r"<[^>]*>")


@dataclass(slots=True)
class _Paragraph:
    """Pojedynczy akapit wraz z naglowkiem, pod ktorym wystapil."""

    text: str
    heading: str | None = None


class _HtmlTextParser(HTMLParser):
    """Zbiera akapity, tytul i metadane z dokumentu HTML.

    Parser jest odporny na niedomkniete znaczniki: licznik pomijanych sekcji nigdy
    nie schodzi ponizej zera, a poczatek ``body`` kasuje zalegle stany pomijania.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.paragraphs: list[_Paragraph] = []
        self.title: str | None = None
        self.meta: dict[str, str] = {}
        self._buffer: list[str] = []
        self._skipped: Counter[str] = Counter()
        self._in_title: bool = False
        self._title_parts: list[str] = []
        self._heading: str | None = None

    # --- stan wewnetrzny -------------------------------------------------------

    @property
    def _skipping(self) -> bool:
        """Czy biezacy tekst nalezy do pomijanej sekcji."""
        return any(count > 0 for count in self._skipped.values())

    def _flush_paragraph(self) -> None:
        """Zamyka biezacy akapit i dopisuje go do wyniku, jesli cos zawiera."""
        if not self._buffer:
            return
        text = clean_text("".join(self._buffer))
        self._buffer.clear()
        if text:
            self.paragraphs.append(_Paragraph(text=text, heading=self._heading))

    def _flush_heading(self) -> None:
        """Zamyka naglowek: staje sie akapitem i kontekstem dla kolejnych akapitow."""
        text = clean_text("".join(self._buffer))
        self._buffer.clear()
        if text:
            self._heading = text
            self.paragraphs.append(_Paragraph(text=text, heading=text))

    def _collect_meta(self, attrs: list[tuple[str, str | None]]) -> None:
        """Zapisuje wartosc znacznika ``meta``, gdy jego nazwa nas interesuje."""
        values = {key.lower(): (value or "") for key, value in attrs}
        name = values.get("name", "").strip().lower()
        if name not in META_NAMES:
            return
        content = clean_text(values.get("content", ""))
        if content and name not in self.meta:
            self.meta[name] = content

    # --- interfejs HTMLParser --------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower()
        if name == "meta":
            self._collect_meta(attrs)
            return
        if name == "title":
            self._in_title = True
            self._title_parts.clear()
            return
        if name == "body":
            self._skipped.clear()
            return
        if name in SKIPPED_TAGS:
            self._flush_paragraph()
            self._skipped[name] += 1
            return
        if self._skipping:
            return
        if name in HEADING_TAGS or name in PARAGRAPH_TAGS:
            self._flush_paragraph()
            return
        if name in SPACER_TAGS:
            self._buffer.append(" ")

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name == "title":
            self._in_title = False
            text = clean_text("".join(self._title_parts))
            self._title_parts.clear()
            if text and self.title is None:
                self.title = text
            return
        if name in SKIPPED_TAGS:
            if self._skipped[name] > 0:
                self._skipped[name] -= 1
            return
        if self._skipping:
            return
        if name in HEADING_TAGS:
            self._flush_heading()
            return
        if name in PARAGRAPH_TAGS:
            self._flush_paragraph()

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
            return
        if self._skipping:
            return
        self._buffer.append(data)

    def close(self) -> None:
        """Konczy parsowanie i zamyka ostatni, jeszcze otwarty akapit."""
        super().close()
        self._flush_paragraph()


def _is_known_codec(name: str) -> bool:
    """Czy Python zna kodowanie o tej nazwie."""
    try:
        codecs.lookup(name)
    except (LookupError, ValueError):
        return False
    return True


def _declared_charset(data: bytes) -> str | None:
    """Kodowanie zadeklarowane w naglowku dokumentu, o ile jest znane Pythonowi."""
    head = data[:CHARSET_SNIFF_BYTES]
    for pattern in (_XML_ENCODING_RE, _META_CHARSET_RE):
        match = pattern.search(head)
        if match is None:
            continue
        name = match.group(1).decode("ascii", "ignore").strip()
        if name and _is_known_codec(name):
            return name
    return None


def _decode_html_bytes(data: bytes) -> DecodedText:
    """Dekoduje bajty dokumentu HTML, respektujac deklaracje kodowania w pliku."""
    return decode_text(data, declared=_declared_charset(data))


def _parse_html(text: str) -> _HtmlTextParser:
    """Uruchamia parser na gotowym tekscie i tlumaczy bledy na wyjatki FindDocs."""
    parser = _HtmlTextParser()
    try:
        parser.feed(text)
        parser.close()
    except Exception as exc:
        raise CorruptedFileError(
            "Nie udało się przetworzyć struktury dokumentu HTML.",
            cause=exc,
        ) from exc
    return parser


def _read_html_bytes(path: Path, context: ExtractionContext) -> bytes:
    """Wczytuje plik z kontrola rozmiaru i tlumaczeniem bledow wejscia i wyjscia."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ExtractionError(
            f"Nie udało się odczytać pliku HTML: {path.name}.",
            details={"plik": path.name},
        ) from exc
    if size > context.max_bytes:
        raise ExtractionError(
            "Plik HTML jest większy niż dozwolony limit odczytu.",
            details={"plik": path.name, "rozmiar": size, "limit": context.max_bytes},
        )
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise CorruptedFileError(
            f"Nie udało się wczytać zawartości pliku HTML: {path.name}.",
            details={"plik": path.name},
        ) from exc
    if not data.strip():
        raise EmptyDocumentError(
            "Plik HTML jest pusty.",
            details={"plik": path.name},
        )
    return data


def html_to_text(html: str) -> str:
    """Zwraca sam tekst fragmentu HTML, z akapitami rozdzielonymi nowa linia.

    Funkcja jest odporna na niepoprawny kod: gdy parser zawiedzie, znaczniki sa
    usuwane wyrazeniem regularnym, a encje rozwijane. Uzywana przez parser
    wiadomosci e-mail dla czesci ``text/html``.
    """
    if not html or not html.strip():
        return ""
    parser = _HtmlTextParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return clean_text(unescape(_TAG_RE.sub(" ", html)))
    return "\n".join(paragraph.text for paragraph in parser.paragraphs)


class HtmlExtractor(Extractor):
    """Adapter dokumentow HTML, HTM i XHTML."""

    name = "html"
    extensions = (".html", ".htm", ".xhtml")
    mime_types = ("text/html", "application/xhtml+xml")
    support_level = SupportLevel.FULL
    priority = 100

    def extract(self, path: Path, context: ExtractionContext) -> ExtractionResult:
        """Wyciaga akapity tekstu i metadane z dokumentu HTML."""
        context.checkpoint()
        data = _read_html_bytes(path, context)
        decoded = _decode_html_bytes(data)
        context.checkpoint()
        parser = _parse_html(decoded.text)

        result = ExtractionResult(
            metadata=DocumentMetadata(
                title=parser.title,
                author=parser.meta.get("author"),
                subject=parser.meta.get("description"),
                keywords=parser.meta.get("keywords"),
                extra={"kodowanie": decoded.encoding},
            ),
            origin=TextOrigin.NATIVE,
            parser_name=self.name,
            support_level=self.support_level,
        )
        if decoded.replaced:
            result.warnings.append(
                "Nie udało się rozpoznać kodowania pliku, użyto UTF-8 z zamiana błędów."
            )

        total_chars = 0
        truncated = False
        for index, paragraph in enumerate(parser.paragraphs):
            if index % CHECKPOINT_EVERY == 0:
                context.checkpoint()
            if total_chars + len(paragraph.text) > context.max_chars:
                truncated = True
                break
            result.sections.append(
                ExtractedSection(
                    text=paragraph.text,
                    kind="text",
                    order=len(result.sections),
                    origin=TextOrigin.NATIVE,
                    heading=paragraph.heading,
                )
            )
            total_chars += len(paragraph.text)

        if truncated:
            result.warnings.append(
                "Dokument jest bardzo długi, tekst został obcięty do limitu znaków."
            )
        if not result.sections:
            raise EmptyDocumentError(
                "Dokument HTML nie zawiera tekstu możliwego do zaindeksowania.",
                details={"plik": path.name},
            )
        if looks_like_garbage(result.all_text(" ")):
            result.warnings.append(
                "Tekst po dekodowaniu wygląda na uszkodzony, sprawdź kodowanie pliku."
            )
        return result


__all__ = [
    "CHARSET_SNIFF_BYTES",
    "HEADING_TAGS",
    "META_NAMES",
    "PARAGRAPH_TAGS",
    "SKIPPED_TAGS",
    "HtmlExtractor",
    "html_to_text",
]

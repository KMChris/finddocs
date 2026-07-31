"""Parser wiadomosci e-mail w formacie EML oraz archiwow MHTML.

Modul korzysta wylacznie z biblioteki standardowej (pakiet ``email``). Wiadomosc jest
parsowana polityka ``email.policy.default``, dzieki czemu naglowki zakodowane
mechanizmem MIME sa dekodowane automatycznie.

Kolejnosc sekcji wyniku: naglowek wiadomosci, akapity tresci, notatki o zalacznikach.
Tresc zalacznikow nie jest tutaj rozpakowywana, robi to warstwa nadrzedna na podstawie
listy ``ExtractionResult.attachments``.
"""

from __future__ import annotations

import mimetypes
import re
from collections.abc import Iterator
from datetime import datetime
from email import policy as email_policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from pathlib import Path

from finddocs.errors import CorruptedFileError, EmptyDocumentError, ExtractionError
from finddocs.extractors.base import ExtractionContext, Extractor
from finddocs.normalization.text import clean_text, looks_like_garbage
from finddocs.types import (
    DocumentMetadata,
    ExtractedAttachment,
    ExtractedSection,
    ExtractionResult,
    SupportLevel,
    TextOrigin,
)

#: Maksymalna liczba zalacznikow wyciaganych z jednej wiadomosci.
MAX_ATTACHMENTS: int = 30

#: Maksymalny laczny rozmiar zalacznikow w bajtach.
MAX_ATTACHMENT_BYTES: int = 100 * 1024 * 1024

#: Co ile przetworzonych czesci wiadomosci sprawdzac anulowanie i limit czasu.
_CHECKPOINT_EVERY: int = 16

#: Naglowki tworzace sekcje naglowkowa: nazwa pola i etykieta po polsku.
_HEADER_FIELDS: tuple[tuple[str, str], ...] = (
    ("From", "Od"),
    ("To", "Do"),
    ("Cc", "DW"),
    ("Subject", "Temat"),
    ("Date", "Data"),
)

#: Znaki niedozwolone w nazwie pliku w systemie Windows.
_UNSAFE_NAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

#: Maksymalna dlugosc nazwy zalacznika, zeby nie przekroczyc limitow systemu plikow.
_MAX_NAME_LENGTH: int = 150


def _header_value(message: EmailMessage, name: str) -> str:
    """Zwraca zdekodowana wartosc naglowka sprowadzona do jednej linii."""
    try:
        raw = message.get(name)
        if raw is None:
            return ""
        text = str(raw)
    except (LookupError, UnicodeError, ValueError, TypeError):
        return ""
    return " ".join(clean_text(text).split())


def _message_date(message: EmailMessage) -> datetime | None:
    """Data wyslania wiadomosci. Bledny albo brakujacy naglowek daje None."""
    try:
        raw = message.get("Date")
        if raw is None:
            return None
        return parsedate_to_datetime(str(raw))
    except (LookupError, UnicodeError, ValueError, TypeError, OverflowError):
        return None


def _safe_name(raw: str, fallback: str) -> str:
    """Sprowadza nazwe zalacznika do bezpiecznej nazwy pliku bez elementow sciezki."""
    candidate = clean_text(raw).replace("\\", "/").rsplit("/", 1)[-1]
    candidate = _UNSAFE_NAME_RE.sub("_", candidate).strip(" .")
    if not candidate:
        return fallback
    return candidate[:_MAX_NAME_LENGTH]


def _iter_leaf_parts(part: EmailMessage) -> Iterator[EmailMessage]:
    """Przechodzi drzewo czesci wiadomosci bez wchodzenia do wiadomosci zagniezdzonych."""
    if part.get_content_type() == "message/rfc822":
        yield part
        return
    if part.is_multipart():
        for sub in part.iter_parts():
            if isinstance(sub, EmailMessage):
                yield from _iter_leaf_parts(sub)
        return
    yield part


def _part_text(part: EmailMessage) -> str:
    """Tekst czesci tekstowej. Nieznane kodowanie jest zastepowane odczytem z podmiana."""
    try:
        content = part.get_content()
        if isinstance(content, str):
            return content
    except (LookupError, UnicodeError, ValueError, KeyError, TypeError):
        content = None
    try:
        payload = part.get_payload(decode=True)
    except (LookupError, UnicodeError, ValueError, TypeError):
        return ""
    if not isinstance(payload, bytes):
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


class EmlExtractor(Extractor):
    """Adapter wiadomosci e-mail zapisanych jako EML oraz stron zapisanych jako MHTML."""

    name = "eml"
    extensions = (".eml", ".mht", ".mhtml")
    mime_types = ("message/rfc822", "multipart/related")
    support_level = SupportLevel.FULL
    priority = 120

    def extract(self, path: Path, context: ExtractionContext) -> ExtractionResult:
        """Buduje sekcje naglowka, tresci i notatek o zalacznikach dla jednej wiadomosci."""
        context.checkpoint()
        message = self._parse(path)

        result = ExtractionResult(
            origin=TextOrigin.NATIVE,
            parser_name=self.name,
            support_level=self.support_level,
        )
        sections: list[ExtractedSection] = []

        header_text = self._header_block(message)
        if header_text:
            sections.append(
                ExtractedSection(text=header_text, kind="email_header", order=len(sections))
            )

        body_part = self._find_body(message)
        paragraphs = self._body_paragraphs(message, body_part, context, result)
        for paragraph in paragraphs:
            sections.append(ExtractedSection(text=paragraph, kind="text", order=len(sections)))

        if context.extract_attachments:
            for attachment in self._collect_attachments(message, body_part, context, result):
                result.attachments.append(attachment)
                note = clean_text(f"Zalacznik: {attachment.name}")
                if note:
                    sections.append(
                        ExtractedSection(text=note, kind="attachment_note", order=len(sections))
                    )

        if not paragraphs and not result.attachments:
            raise EmptyDocumentError(
                "Wiadomosc e-mail nie zawiera tresci tekstowej ani zalacznikow.",
                details={"plik": path.name},
            )
        if not header_text and not result.attachments and looks_like_garbage("\n".join(paragraphs)):
            raise CorruptedFileError(
                "Plik nie zawiera poprawnej wiadomosci e-mail. Moze byc uszkodzony.",
                details={"plik": path.name},
            )

        result.sections = sections
        result.metadata = self._metadata(message)
        return result

    # --- parsowanie ------------------------------------------------------------

    def _parse(self, path: Path) -> EmailMessage:
        """Wczytuje plik i parsuje go do struktury wiadomosci."""
        try:
            with path.open("rb") as handle:
                parsed = BytesParser(EmailMessage, policy=email_policy.default).parse(handle)
        except OSError as exc:
            raise ExtractionError(
                f"Nie udalo sie odczytac pliku wiadomosci: {path.name}.",
                details={"plik": path.name},
                cause=exc,
            ) from exc
        except Exception as exc:
            raise CorruptedFileError(
                "Nie udalo sie sparsowac wiadomosci e-mail. Plik moze byc uszkodzony.",
                details={"plik": path.name},
                cause=exc,
            ) from exc
        return parsed

    # --- naglowki i metadane ---------------------------------------------------

    def _header_block(self, message: EmailMessage) -> str:
        """Sklada tekst sekcji naglowkowej z pol Od, Do, DW, Temat i Data."""
        lines = [
            f"{label}: {value}"
            for field_name, label in _HEADER_FIELDS
            if (value := _header_value(message, field_name))
        ]
        return clean_text("\n".join(lines))

    def _metadata(self, message: EmailMessage) -> DocumentMetadata:
        """Metadane dokumentu zbudowane z naglowkow wiadomosci."""
        metadata = DocumentMetadata(
            title=_header_value(message, "Subject") or None,
            author=_header_value(message, "From") or None,
            created_at=_message_date(message),
        )
        metadata.extra["to"] = _header_value(message, "To") or None
        metadata.extra["cc"] = _header_value(message, "Cc") or None
        metadata.extra["message_id"] = _header_value(message, "Message-ID") or None
        return metadata

    # --- tresc -----------------------------------------------------------------

    def _find_body(self, message: EmailMessage) -> EmailMessage | None:
        """Wybiera czesc z trescia, preferujac tekst czysty przed HTML."""
        try:
            body = message.get_body(preferencelist=("plain", "html"))
        except (LookupError, ValueError, TypeError, AttributeError):
            return None
        if isinstance(body, EmailMessage):
            return body
        return None

    def _body_paragraphs(
        self,
        message: EmailMessage,
        body: EmailMessage | None,
        context: ExtractionContext,
        result: ExtractionResult,
    ) -> list[str]:
        """Zwraca akapity tresci wiadomosci po oczyszczeniu."""
        raw = ""
        if body is not None:
            raw = _part_text(body)
            if body.get_content_type() == "text/html":
                raw = self._html_text(raw, result)
        if not raw.strip():
            raw = self._fallback_text(message, body, context, result)

        cleaned = clean_text(raw)
        if not cleaned:
            return []

        paragraphs: list[str] = []
        total_chars = 0
        for index, block in enumerate(cleaned.split("\n\n")):
            if index % _CHECKPOINT_EVERY == 0:
                context.checkpoint()
            piece = clean_text(block)
            if not piece:
                continue
            if total_chars + len(piece) > context.max_chars:
                result.warnings.append("Tresc wiadomosci zostala skrocona do limitu znakow.")
                break
            total_chars += len(piece)
            paragraphs.append(piece)
        return paragraphs

    def _fallback_text(
        self,
        message: EmailMessage,
        body: EmailMessage | None,
        context: ExtractionContext,
        result: ExtractionResult,
    ) -> str:
        """Zbiera tekst z czesci tekstowych, gdy wybor glownej tresci zawiodl."""
        pieces: list[str] = []
        for index, part in enumerate(_iter_leaf_parts(message)):
            if index % _CHECKPOINT_EVERY == 0:
                context.checkpoint()
            if part is body:
                continue
            if part.get_filename() or part.get_content_disposition() == "attachment":
                continue
            content_type = part.get_content_type()
            if content_type == "text/plain":
                pieces.append(_part_text(part))
            elif content_type == "text/html":
                pieces.append(self._html_text(_part_text(part), result))
        return "\n\n".join(piece for piece in pieces if piece.strip())

    def _html_text(self, html: str, result: ExtractionResult) -> str:
        """Zamienia tresc HTML na tekst przy uzyciu wspolnego modulu konwersji."""
        if not html.strip():
            return ""
        try:
            from finddocs.extractors.html_text import html_to_text

            return html_to_text(html)
        except Exception as exc:
            result.warnings.append(
                f"Nie udalo sie przeksztalcic tresci HTML wiadomosci ({type(exc).__name__})."
            )
            return ""

    # --- zalaczniki ------------------------------------------------------------

    def _collect_attachments(
        self,
        message: EmailMessage,
        body: EmailMessage | None,
        context: ExtractionContext,
        result: ExtractionResult,
    ) -> list[ExtractedAttachment]:
        """Wyciaga zalaczniki wiadomosci z zachowaniem limitu liczby i rozmiaru."""
        attachments: list[ExtractedAttachment] = []
        total_bytes = 0
        size_limit_reported = False
        for index, part in enumerate(_iter_leaf_parts(message)):
            if index % _CHECKPOINT_EVERY == 0:
                context.checkpoint()
            if part is body:
                continue
            candidate = self._as_attachment(part, index)
            if candidate is None:
                continue
            if len(attachments) >= MAX_ATTACHMENTS:
                result.warnings.append(
                    f"Wiadomosc ma wiecej niz {MAX_ATTACHMENTS} zalacznikow, "
                    "pozostale zostaly pominiete."
                )
                break
            if total_bytes + len(candidate.data) > MAX_ATTACHMENT_BYTES:
                if not size_limit_reported:
                    limit_mb = MAX_ATTACHMENT_BYTES // (1024 * 1024)
                    result.warnings.append(
                        f"Przekroczono laczny limit {limit_mb} MB zalacznikow, "
                        "czesc z nich zostala pominieta."
                    )
                    size_limit_reported = True
                continue
            total_bytes += len(candidate.data)
            attachments.append(candidate)
        return attachments

    def _as_attachment(self, part: EmailMessage, ordinal: int) -> ExtractedAttachment | None:
        """Zamienia czesc wiadomosci na zalacznik albo zwraca None, gdy to nie zalacznik."""
        content_type = part.get_content_type()
        if content_type == "message/rfc822":
            return self._nested_message(part, ordinal)

        try:
            filename = part.get_filename()
            disposition = part.get_content_disposition()
        except (LookupError, UnicodeError, ValueError, TypeError):
            return None
        if disposition != "attachment" and not filename:
            return None

        try:
            data = part.get_payload(decode=True)
        except (LookupError, UnicodeError, ValueError, TypeError):
            return None
        if not isinstance(data, bytes) or not data:
            return None

        extension = mimetypes.guess_extension(content_type) or ".bin"
        name = _safe_name(filename or "", f"zalacznik-{ordinal}{extension}")
        return ExtractedAttachment(name=name, mime_type=content_type, data=data)

    def _nested_message(self, part: EmailMessage, ordinal: int) -> ExtractedAttachment | None:
        """Traktuje zagniezdzona wiadomosc jako zalacznik z rozszerzeniem .eml."""
        payload = part.get_payload()
        nested = payload[0] if isinstance(payload, list) and payload else None
        if not isinstance(nested, EmailMessage):
            return None
        try:
            data = nested.as_bytes()
        except Exception:
            return None
        if not data:
            return None
        default_name = f"wiadomosc-{ordinal}"
        name = _safe_name(part.get_filename() or _header_value(nested, "Subject"), default_name)
        if not name.lower().endswith(".eml"):
            name = f"{name}.eml"
        return ExtractedAttachment(name=name, mime_type="message/rfc822", data=data)


__all__ = ["MAX_ATTACHMENTS", "MAX_ATTACHMENT_BYTES", "EmlExtractor"]

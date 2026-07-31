"""Kwalifikowanie dokumentow do OCR.

OCR na CPU jest najwolniejszym etapem indeksowania, wiec uruchamiamy go wylacznie
wtedy, gdy standardowa ekstrakcja nie dala uzytecznego tekstu. Decyzja opiera sie
na czterech przeslankach: parser sam zglosil brak warstwy tekstowej, plik jest
obrazem, tekstu jest za malo w stosunku do liczby stron, albo tekst wyglada na
uszkodzony.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from finddocs.config import OcrSettings
from finddocs.extractors.detect import FileTypeInfo
from finddocs.normalization.text import alpha_ratio, looks_like_garbage
from finddocs.types import ExtractionResult


class OcrReason(str, Enum):
    """Powod uruchomienia albo pominiecia OCR."""

    IMAGE_FILE = "plik_obrazu"
    NO_TEXT_LAYER = "brak_warstwy_tekstowej"
    TOO_FEW_CHARACTERS = "za_malo_znakow"
    GARBLED_TEXT = "tekst_uszkodzony"
    PARSER_REQUESTED = "parser_zglosil_potrzebe"
    EXTRACTION_FAILED = "ekstrakcja_nieudana"
    NOT_NEEDED = "nie_jest_potrzebny"
    DISABLED = "wylaczony_w_ustawieniach"
    UNSUPPORTED_FOR_OCR = "format_nie_da_sie_zrasteryzowac"


#: Formaty, ktore potrafimy zrasteryzowac i podac silnikowi OCR.
RASTERIZABLE_MIME_TYPES = frozenset(
    {
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/tiff",
        "image/bmp",
        "image/gif",
        "image/webp",
    }
)


@dataclass(frozen=True, slots=True)
class OcrDecision:
    """Decyzja o uruchomieniu OCR."""

    needed: bool
    reason: OcrReason
    detail: str = ""

    def describe(self) -> str:
        base = {
            OcrReason.IMAGE_FILE: "Plik jest obrazem, wiec tekst trzeba rozpoznac.",
            OcrReason.NO_TEXT_LAYER: "Dokument nie ma warstwy tekstowej.",
            OcrReason.TOO_FEW_CHARACTERS: "Warstwa tekstowa zawiera za malo znakow.",
            OcrReason.GARBLED_TEXT: "Odczytany tekst wyglada na uszkodzony.",
            OcrReason.PARSER_REQUESTED: "Parser zglosil potrzebe rozpoznania tekstu.",
            OcrReason.EXTRACTION_FAILED: "Standardowa ekstrakcja nie powiodla sie.",
            OcrReason.NOT_NEEDED: "Warstwa tekstowa jest wystarczajaca.",
            OcrReason.DISABLED: "OCR jest wylaczony w ustawieniach.",
            OcrReason.UNSUPPORTED_FOR_OCR: "Tego formatu nie da sie zrasteryzowac.",
        }[self.reason]
        return f"{base} {self.detail}".strip()


def can_rasterize(info: FileTypeInfo) -> bool:
    """Czy plik da sie zamienic na obrazy stron."""
    return info.mime_type in RASTERIZABLE_MIME_TYPES


def decide(
    result: ExtractionResult | None,
    info: FileTypeInfo,
    settings: OcrSettings,
    *,
    extraction_failed: bool = False,
) -> OcrDecision:
    """Ocenia, czy dokument wymaga OCR."""
    if not settings.enabled or settings.engine == "none":
        return OcrDecision(False, OcrReason.DISABLED)

    if not can_rasterize(info):
        if extraction_failed or result is None or result.needs_ocr:
            return OcrDecision(False, OcrReason.UNSUPPORTED_FOR_OCR, info.mime_type)
        return OcrDecision(False, OcrReason.NOT_NEEDED)

    if extraction_failed or result is None:
        return OcrDecision(True, OcrReason.EXTRACTION_FAILED)

    if info.is_image:
        return OcrDecision(True, OcrReason.IMAGE_FILE)

    text = result.all_text()
    stripped = "".join(text.split())
    pages = max(1, result.total_pages or 1)

    if not stripped:
        return OcrDecision(True, OcrReason.NO_TEXT_LAYER, f"stron: {pages}")

    per_page = len(stripped) / pages
    if per_page < settings.min_chars_per_page:
        return OcrDecision(
            True,
            OcrReason.TOO_FEW_CHARACTERS,
            f"{per_page:.0f} znakow na strone, prog {settings.min_chars_per_page}",
        )

    if looks_like_garbage(text, min_alpha_ratio=settings.min_alpha_ratio):
        return OcrDecision(
            True,
            OcrReason.GARBLED_TEXT,
            f"udzial znakow alfanumerycznych {alpha_ratio(text):.2f}",
        )

    if result.needs_ocr:
        return OcrDecision(True, OcrReason.PARSER_REQUESTED)

    return OcrDecision(False, OcrReason.NOT_NEEDED)


def pages_needing_ocr(
    result: ExtractionResult, settings: OcrSettings, *, total_pages: int
) -> list[int]:
    """Numery stron, ktore warto poddac OCR.

    Strona z sensowna iloscia tekstu nie jest przetwarzana ponownie. Dzieki temu
    dokument mieszany (kilka skanow wsrod stron tekstowych) kosztuje tyle, ile trzeba.
    """
    if total_pages <= 0:
        return []
    chars_by_page: dict[int, int] = {}
    for section in result.sections:
        if section.page is None:
            continue
        chars_by_page[section.page] = chars_by_page.get(section.page, 0) + len(
            "".join(section.text.split())
        )
    if not chars_by_page:
        return list(range(1, total_pages + 1))
    return [
        page
        for page in range(1, total_pages + 1)
        if chars_by_page.get(page, 0) < settings.min_chars_per_page
    ]


__all__ = [
    "RASTERIZABLE_MIME_TYPES",
    "OcrDecision",
    "OcrReason",
    "can_rasterize",
    "decide",
    "pages_needing_ocr",
]

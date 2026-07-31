"""Adapter plikow graficznych oparty na Pillow.

Obraz rastrowy nie ma warstwy tekstowej, wiec parser nie zwraca zadnych sekcji.
Zamiast tego odczytuje metadane techniczne i ustawia ``needs_ocr``, dzieki czemu
osobna warstwa OCR moze rozpoznac tresc. Sam OCR nie jest tutaj wykonywany.

Modul udostepnia tez dwie funkcje pomocnicze dla warstwy OCR:
``load_image_frames`` oraz ``image_frame_count``.
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageSequence, UnidentifiedImageError
from PIL.ExifTags import TAGS

from finddocs.errors import CorruptedFileError, ExtractionError
from finddocs.extractors.base import ExtractionContext, Extractor
from finddocs.types import DocumentMetadata, ExtractionResult, SupportLevel

#: Powyzej tej liczby pikseli obraz uznajemy za bardzo duzy i ostrzegamy o tym.
LARGE_IMAGE_PIXELS = 40_000_000

#: Domyslny limit klatek zwracanych warstwie OCR.
DEFAULT_MAX_FRAMES = 60

#: Identyfikator sub-IFD z danymi Exif wewnatrz glownego bloku metadanych.
_EXIF_IFD_TAG = 0x8769

#: Tryby Pillow, ktore dla potrzeb OCR najlepiej sprowadzic do skali szarosci.
_GRAYSCALE_SOURCE_MODES = frozenset(
    {"1", "L", "LA", "P", "PA", "I", "I;16", "I;16B", "I;16L", "I;16N", "F"}
)

#: Formaty daty spotykane w polach Exif.
_EXIF_DATE_FORMATS = ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S")


@dataclass(frozen=True, slots=True)
class _ImageInfo:
    """Podstawowe informacje odczytane z naglowka obrazu."""

    width: int
    height: int
    mode: str
    image_format: str
    frames: int
    exif: dict[str, Any] = field(default_factory=dict)


def _open_image(path: Path) -> Image.Image:
    """Otwiera obraz i tlumaczy bledy Pillow na wyjatki FindDocs."""
    try:
        return Image.open(path)
    except Image.DecompressionBombError as exc:
        raise ExtractionError(
            f"Obraz ma zbyt duza liczbe pikseli, aby go bezpiecznie otworzyc: {path.name}.",
            details={"plik": path.name},
            cause=exc,
        ) from exc
    except UnidentifiedImageError as exc:
        raise CorruptedFileError(
            f"Nie udalo sie rozpoznac formatu obrazu: {path.name}.",
            details={"plik": path.name},
            cause=exc,
        ) from exc
    except (OSError, ValueError) as exc:
        raise CorruptedFileError(
            f"Nie udalo sie otworzyc pliku obrazu: {path.name}.",
            details={"plik": path.name},
            cause=exc,
        ) from exc


def _frame_count(image: Image.Image) -> int:
    """Liczba klatek albo stron obrazu. Gdy formatu nie da sie odpytac, zwraca 1."""
    try:
        count = int(getattr(image, "n_frames", 1))
    except (AttributeError, EOFError, OSError, TypeError, ValueError):
        return 1
    return max(1, count)


def _exif_values(image: Image.Image) -> dict[str, Any]:
    """Zwraca mape nazwa tagu Exif na wartosc. Bledy odczytu sa ignorowane cicho."""
    values: dict[str, Any] = {}
    try:
        exif = image.getexif()
        for tag_id, value in exif.items():
            name = TAGS.get(tag_id)
            if name:
                values[name] = value
        for tag_id, value in exif.get_ifd(_EXIF_IFD_TAG).items():
            name = TAGS.get(tag_id)
            if name:
                values.setdefault(name, value)
    except Exception:  # blok Exif bywa uszkodzony, wtedy po prostu go pomijamy
        return values
    return values


def _exif_text(value: Any) -> str | None:
    """Sprowadza wartosc Exif do czystego tekstu albo zwraca None."""
    if isinstance(value, bytes):
        text = value.decode("utf-8", "ignore")
    elif isinstance(value, str):
        text = value
    else:
        return None
    return text.replace("\x00", " ").strip() or None


def _exif_datetime(value: Any) -> _dt.datetime | None:
    """Parsuje date Exif zapisana w formacie 'RRRR:MM:DD GG:MM:SS'."""
    text = _exif_text(value)
    if not text:
        return None
    for date_format in _EXIF_DATE_FORMATS:
        try:
            return _dt.datetime.strptime(text, date_format)
        except ValueError:
            continue
    return None


def _apply_exif(metadata: DocumentMetadata, values: dict[str, Any]) -> None:
    """Uzupelnia metadane dokumentu danymi z Exif, jesli sa dostepne."""
    created = _exif_datetime(values.get("DateTimeOriginal"))
    if created is None:
        created = _exif_datetime(values.get("DateTime"))
    if created is not None:
        metadata.created_at = created
    author = _exif_text(values.get("Artist"))
    if author:
        metadata.author = author
    producer = _exif_text(values.get("Software"))
    if producer:
        metadata.producer = producer


def _read_image_info(path: Path) -> _ImageInfo:
    """Odczytuje wymiary, tryb, format, liczbe klatek i Exif bez ladowania pikseli."""
    image = _open_image(path)
    try:
        with image:
            return _ImageInfo(
                width=int(image.width),
                height=int(image.height),
                mode=image.mode,
                image_format=image.format or "",
                frames=_frame_count(image),
                exif=_exif_values(image),
            )
    except Image.DecompressionBombError as exc:
        raise ExtractionError(
            f"Obraz ma zbyt duza liczbe pikseli, aby go bezpiecznie odczytac: {path.name}.",
            details={"plik": path.name},
            cause=exc,
        ) from exc
    except (OSError, ValueError) as exc:
        raise CorruptedFileError(
            f"Nie udalo sie odczytac naglowka obrazu: {path.name}.",
            details={"plik": path.name},
            cause=exc,
        ) from exc


def _fit_to_pixels(image: Image.Image, max_pixels: int) -> Image.Image:
    """Skaluje obraz proporcjonalnie, gdy przekracza limit pikseli."""
    width, height = image.size
    pixels = width * height
    if max_pixels <= 0 or pixels <= max_pixels:
        return image
    scale = (max_pixels / pixels) ** 0.5
    new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    try:
        return image.resize(new_size, Image.Resampling.LANCZOS)
    except (OSError, ValueError) as exc:
        raise CorruptedFileError(
            "Nie udalo sie przeskalowac obrazu do rozmiaru akceptowanego przez OCR.",
            details={"docelowy_rozmiar": list(new_size)},
            cause=exc,
        ) from exc


def _prepare_frame(frame: Image.Image, max_pixels: int) -> Image.Image:
    """Sprowadza klatke do trybu 'L' albo 'RGB' i dopasowuje ja do limitu pikseli."""
    target_mode = "L" if frame.mode in _GRAYSCALE_SOURCE_MODES else "RGB"
    try:
        prepared = frame.convert(target_mode)
    except (OSError, ValueError) as exc:
        raise CorruptedFileError(
            f"Nie udalo sie przeksztalcic klatki obrazu do trybu {target_mode}.",
            details={"tryb_zrodlowy": frame.mode},
            cause=exc,
        ) from exc
    return _fit_to_pixels(prepared, max_pixels)


def load_image_frames(
    path: Path,
    max_frames: int = DEFAULT_MAX_FRAMES,
    max_pixels: int = LARGE_IMAGE_PIXELS,
) -> Iterator[Image.Image]:
    """Zwraca kolejne klatki obrazu, przeskalowane gdy przekraczaja limit pikseli.

    Dla wielostronicowego TIFF albo animacji zwracane sa kolejne klatki, dla
    zwyklego obrazu dokladnie jedna. Kazda klatka jest niezalezna od pliku
    zrodlowego i ma tryb 'L' albo 'RGB'.
    """
    if max_frames <= 0:
        return
    image = _open_image(path)
    try:
        with image:
            for index, frame in enumerate(ImageSequence.Iterator(image)):
                if index >= max_frames:
                    break
                yield _prepare_frame(frame, max_pixels)
    except Image.DecompressionBombError as exc:
        raise ExtractionError(
            f"Obraz ma zbyt duza liczbe pikseli, aby go bezpiecznie odczytac: {path.name}.",
            details={"plik": path.name},
            cause=exc,
        ) from exc
    except (OSError, ValueError) as exc:
        raise CorruptedFileError(
            f"Nie udalo sie odczytac klatek obrazu: {path.name}.",
            details={"plik": path.name},
            cause=exc,
        ) from exc


def image_frame_count(path: Path) -> int:
    """Zwraca liczbe klatek albo stron obrazu, co najmniej 1."""
    with _open_image(path) as image:
        return _frame_count(image)


class ImageExtractor(Extractor):
    """Adapter obrazow rastrowych.

    Nie wyciaga tekstu, bo obraz go nie zawiera. Zwraca wynik bez sekcji,
    z ustawiona flaga ``needs_ocr`` i metadanymi obrazu. To jest poprawne
    zachowanie tego parsera, a nie blad odczytu.
    """

    name = "image"
    extensions = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp")
    mime_types = (
        "image/png",
        "image/jpeg",
        "image/tiff",
        "image/bmp",
        "image/gif",
        "image/webp",
    )
    support_level = SupportLevel.LIMITED
    priority = 100

    def extract(self, path: Path, context: ExtractionContext) -> ExtractionResult:
        """Odczytuje metadane obrazu i zglasza potrzebe rozpoznania tekstu."""
        context.checkpoint()
        info = _read_image_info(path)
        context.checkpoint()

        metadata = DocumentMetadata(page_count=info.frames)
        metadata.extra["width"] = info.width
        metadata.extra["height"] = info.height
        metadata.extra["mode"] = info.mode
        metadata.extra["format"] = info.image_format
        _apply_exif(metadata, info.exif)

        result = ExtractionResult(
            metadata=metadata,
            total_pages=info.frames,
            parser_name=self.name,
            support_level=self.support_level,
            needs_ocr=True,
        )
        if info.width * info.height > LARGE_IMAGE_PIXELS:
            result.warnings.append("Obraz bardzo duzy, OCR moze zostac ograniczony")
        if info.frames > DEFAULT_MAX_FRAMES:
            result.warnings.append(
                f"Liczba klatek obrazu: {info.frames}. OCR obejmie pierwsze {DEFAULT_MAX_FRAMES}."
            )
        return result


__all__ = [
    "DEFAULT_MAX_FRAMES",
    "LARGE_IMAGE_PIXELS",
    "ImageExtractor",
    "image_frame_count",
    "load_image_frames",
]

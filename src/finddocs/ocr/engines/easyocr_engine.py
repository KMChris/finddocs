"""Adapter EasyOCR, opcjonalny silnik z modelem dla jezyka polskiego.

EasyOCR instaluje sie przez pip i nie wymaga komponentu systemowego, ale ciagnie
za soba PyTorch, wiec nie jest instalowany domyslnie. Jest sensownym wyborem tam,
gdzie polityka firmy nie pozwala zainstalowac Tesseracta, a jakosc rozpoznawania
polskich znakow ma znaczenie.

Modele sa pobierane przy pierwszym uruchomieniu i zapisywane w katalogu danych
uzytkownika. Pobranie wymaga jawnej zgody, tak samo jak pobranie modelu embeddingow.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from finddocs.errors import OcrError
from finddocs.logging_setup import get_logger
from finddocs.ocr.base import OcrEngine, OcrLine, OcrPageResult
from finddocs.types import CancellationToken

if TYPE_CHECKING:  # pragma: no cover
    from PIL.Image import Image

log = get_logger(__name__)

ENGINE_NAME = "easyocr"

#: Mapowanie kodow jezyka uzywanych w konfiguracji na kody EasyOCR.
LANGUAGE_MAP: dict[str, str] = {"pol": "pl", "eng": "en", "deu": "de", "ces": "cs"}


class EasyOcrEngine(OcrEngine):
    """OCR przez EasyOCR na CPU."""

    name = ENGINE_NAME
    priority = 80
    supports_rotation = True
    provides_confidence = True

    def __init__(self, *, model_dir: Path | None = None, allow_download: bool = False) -> None:
        self._reader: Any | None = None
        self._available: bool | None = None
        self._reason = ""
        self._model_dir = model_dir
        self._allow_download = allow_download
        self._languages: list[str] = ["pl", "en"]

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            import easyocr  # noqa: F401
        except ImportError:
            self._available = False
            self._reason = (
                "Pakiet easyocr nie jest zainstalowany. Zainstaluj dodatek 'ocr-easy', "
                "jesli chcesz uzywac tego silnika."
            )
            return False
        self._available = True
        return True

    def unavailable_reason(self) -> str:
        self.is_available()
        return self._reason

    def version(self) -> str:
        if not self.is_available():
            return ""
        try:
            from importlib.metadata import version as pkg_version

            return pkg_version("easyocr")
        except Exception:
            return "nieznana"

    def supported_languages(self) -> list[str]:
        return ["pol", "eng"]

    def has_polish(self) -> bool:
        return True

    def _ensure_reader(self, languages: list[str]) -> Any:
        wanted = [LANGUAGE_MAP.get(code, code) for code in languages] or ["pl"]
        if "en" not in wanted:
            wanted.append("en")
        if self._reader is not None and wanted == self._languages:
            return self._reader
        if not self.is_available():
            raise OcrError(self.unavailable_reason())

        import easyocr

        kwargs: dict[str, Any] = {
            "gpu": False,
            "verbose": False,
            "download_enabled": self._allow_download,
        }
        if self._model_dir is not None:
            kwargs["model_storage_directory"] = str(self._model_dir)
            kwargs["user_network_directory"] = str(self._model_dir)
        try:
            self._reader = easyocr.Reader(wanted, **kwargs)
        except Exception as exc:
            raise OcrError(
                "Nie udało się zainicjować EasyOCR. Sprawdź, czy modele są pobrane.",
                cause=exc,
            ) from exc
        self._languages = wanted
        return self._reader

    def warmup(self) -> None:
        if self.is_available():
            self._ensure_reader(["pol"])

    def close(self) -> None:
        self._reader = None

    def recognize(
        self,
        image: Image,
        *,
        languages: list[str],
        page: int = 1,
        cancel: CancellationToken | None = None,
    ) -> OcrPageResult:
        if cancel is not None:
            cancel.raise_if_cancelled()
        reader = self._ensure_reader(languages)
        array = np.asarray(image.convert("RGB"))
        started = time.monotonic()
        try:
            raw = reader.readtext(array, detail=1, paragraph=False)
        except Exception as exc:
            raise OcrError(f"EasyOCR nie rozpoznał strony {page}.", cause=exc) from exc

        lines: list[OcrLine] = []
        confidences: list[float] = []
        for box, text, score in raw:
            value = str(text).strip()
            if not value:
                continue
            confidences.append(float(score))
            xs = [int(p[0]) for p in box]
            ys = [int(p[1]) for p in box]
            lines.append(
                OcrLine(
                    text=value,
                    confidence=float(score),
                    box=(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)),
                )
            )
        lines.sort(
            key=lambda line: (line.box[1] if line.box else 0, line.box[0] if line.box else 0)
        )
        return OcrPageResult(
            page=page,
            text="\n".join(line.text for line in lines),
            confidence=sum(confidences) / len(confidences) if confidences else None,
            lines=lines,
            engine=self.name,
            duration_seconds=time.monotonic() - started,
        )


__all__ = ["ENGINE_NAME", "LANGUAGE_MAP", "EasyOcrEngine"]

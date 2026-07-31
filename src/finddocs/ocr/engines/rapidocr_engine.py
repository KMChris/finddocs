"""Adapter RapidOCR (ONNX Runtime, instalowany przez pip).

Zaleta: dziala od razu po ``pip install``, bez instalatora systemowego, w calosci
lokalnie na CPU i na tej samej bibliotece ONNX Runtime, ktorej uzywaja embeddingi.

Ograniczenie: modele dolaczone do pakietu sa trenowane dla chinskiego i angielskiego.
Rozpoznaja litery lacinskie, ale gubia polskie znaki diakrytyczne. Adapter potrafi
zaladowac model rozpoznawania dla alfabetu lacinskiego (PP-OCR latin) razem z jego
slownikiem znakow, jesli zostal umieszczony w katalogu modeli. Wtedy jakosc dla
polskiego jest wyrazie lepsza. Bez tego modelu adapter dziala nadal, ale zglasza
ostrzezenie, a warstwa normalizacji sklada znaki diakrytyczne, wiec wyszukiwanie
i tak dziala.
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

ENGINE_NAME = "rapidocr"

#: Nazwa katalogu z opcjonalnym modelem dla alfabetu lacinskiego.
LATIN_MODEL_DIR = "rapidocr-latin"
LATIN_REC_MODEL = "latin_PP-OCRv3_rec_infer.onnx"
LATIN_DICT = "latin_dict.txt"


def _latin_model_paths() -> tuple[Path, Path] | None:
    """Znajduje opcjonalny model lacinski w katalogach modeli aplikacji."""
    from finddocs.app_paths import AppPaths

    roots = [
        AppPaths.default().models_dir / LATIN_MODEL_DIR,
        Path(__file__).resolve().parents[4] / "models" / LATIN_MODEL_DIR,
        Path(__file__).resolve().parents[2] / "resources" / "models" / LATIN_MODEL_DIR,
    ]
    for root in roots:
        model = root / LATIN_REC_MODEL
        dictionary = root / LATIN_DICT
        if model.exists() and dictionary.exists():
            return model, dictionary
    return None


class RapidOcrEngine(OcrEngine):
    """OCR przez RapidOCR na ONNX Runtime."""

    name = ENGINE_NAME
    priority = 60
    supports_rotation = True
    provides_confidence = True

    def __init__(self, *, use_angle_cls: bool = True, text_score: float = 0.5) -> None:
        self._engine: Any | None = None
        self._available: bool | None = None
        self._reason = ""
        self._version = ""
        self._latin = _latin_model_paths()
        self._use_angle_cls = use_angle_cls
        self._text_score = text_score

    # --- dostepnosc -------------------------------------------------------

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            import rapidocr_onnxruntime  # noqa: F401
        except ImportError as exc:
            self._available = False
            self._reason = (
                "Pakiet rapidocr-onnxruntime nie jest zainstalowany. "
                "Zainstaluj dodatek 'ocr-rapid'."
            )
            log.debug("ocr.rapidocr_missing", error_type=type(exc).__name__)
            return False
        self._available = True
        return True

    def unavailable_reason(self) -> str:
        self.is_available()
        return self._reason

    def version(self) -> str:
        if self._version:
            return self._version
        if not self.is_available():
            return ""
        try:
            from importlib.metadata import version as pkg_version

            self._version = pkg_version("rapidocr-onnxruntime")
        except Exception:
            self._version = "nieznana"
        if self._latin is not None:
            self._version = f"{self._version}+latin"
        return self._version

    def supported_languages(self) -> list[str]:
        if self._latin is not None:
            return ["lat", "pol", "eng"]
        return ["eng"]

    def has_polish(self) -> bool:
        return self._latin is not None

    # --- inicjalizacja ----------------------------------------------------

    def _ensure_engine(self) -> Any:
        if self._engine is not None:
            return self._engine
        if not self.is_available():
            raise OcrError(self.unavailable_reason())
        from rapidocr_onnxruntime import RapidOCR

        kwargs: dict[str, Any] = {
            "text_score": self._text_score,
            "use_cls": self._use_angle_cls,
            "det_use_cuda": False,
            "cls_use_cuda": False,
            "rec_use_cuda": False,
        }
        if self._latin is not None:
            model, dictionary = self._latin
            kwargs["rec_model_path"] = str(model)
            kwargs["rec_keys_path"] = str(dictionary)
        try:
            self._engine = RapidOCR(**kwargs)
        except TypeError:
            # starsze wersje pakietu nie znaja czesci parametrow
            fallback: dict[str, Any] = {}
            if self._latin is not None:
                model, dictionary = self._latin
                fallback["rec_model_path"] = str(model)
                fallback["rec_keys_path"] = str(dictionary)
            self._engine = RapidOCR(**fallback)
        except Exception as exc:
            raise OcrError("Nie udalo sie zainicjowac silnika RapidOCR.", cause=exc) from exc
        return self._engine

    def warmup(self) -> None:
        if self.is_available():
            self._ensure_engine()

    def close(self) -> None:
        self._engine = None

    # --- rozpoznawanie ----------------------------------------------------

    def recognize(
        self,
        image: Image,
        *,
        languages: list[str],
        page: int = 1,
        cancel: CancellationToken | None = None,
    ) -> OcrPageResult:
        del languages  # model jest wybierany przy inicjalizacji, nie per strona
        if cancel is not None:
            cancel.raise_if_cancelled()
        engine = self._ensure_engine()

        rgb = image.convert("RGB")
        array = np.asarray(rgb)[:, :, ::-1].copy()  # RapidOCR oczekuje BGR

        started = time.monotonic()
        try:
            result, _elapsed = engine(array)
        except Exception as exc:
            raise OcrError(f"RapidOCR nie rozpoznal strony {page}.", cause=exc) from exc

        lines: list[OcrLine] = []
        confidences: list[float] = []
        for entry in result or []:
            box, text, score = entry[0], str(entry[1]), float(entry[2])
            if not text.strip():
                continue
            confidences.append(score)
            xs = [int(p[0]) for p in box]
            ys = [int(p[1]) for p in box]
            lines.append(
                OcrLine(
                    text=text,
                    confidence=score,
                    box=(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)),
                )
            )

        lines.sort(
            key=lambda line: (line.box[1] if line.box else 0, line.box[0] if line.box else 0)
        )
        text_value = "\n".join(line.text for line in lines)
        average = sum(confidences) / len(confidences) if confidences else None
        return OcrPageResult(
            page=page,
            text=text_value,
            confidence=average,
            lines=lines,
            engine=self.name,
            duration_seconds=time.monotonic() - started,
        )


__all__ = ["ENGINE_NAME", "LATIN_DICT", "LATIN_MODEL_DIR", "LATIN_REC_MODEL", "RapidOcrEngine"]

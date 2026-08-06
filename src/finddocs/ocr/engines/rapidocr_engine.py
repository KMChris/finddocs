"""Adapter RapidOCR (ONNX Runtime, instalowany przez pip).

Zaleta: dziala od razu po ``pip install``, bez instalatora systemowego, w calosci
lokalnie na CPU i na tej samej bibliotece ONNX Runtime, ktorej uzywaja embeddingi.

Dodatek ocr-rapid instaluje jeden z dwoch pakietow tego samego projektu:
``rapidocr-onnxruntime`` 1.4.4 dla Pythona do 3.12 (nowszych wydan nie ma,
a 1.4.4 deklaruje ``requires-python < 3.13``) albo jego nastepce ``rapidocr``
dla Pythona od 3.13. Pakiety roznia sie konstruktorem i formatem wyniku,
dlatego adapter wykrywa zainstalowany wariant i obsluguje oba. Oba maja
domyslne modele wbudowane w pakiet, wiec dzialaja bez pobierania z sieci.

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


def _import_rapidocr() -> tuple[str, Any] | None:
    """Zwraca (nazwa dystrybucji, klasa RapidOCR) zainstalowanego wariantu."""
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        pass
    else:
        return "rapidocr-onnxruntime", RapidOCR
    try:
        from rapidocr import RapidOCR
    except ImportError:
        return None
    return "rapidocr", RapidOCR


def _extract_entries(raw: Any) -> list[tuple[Any, str, float]]:
    """Sprowadza wynik obu wariantow API do listy (ramka, tekst, pewnosc).

    rapidocr-onnxruntime zwraca krotke (lista wpisow [ramka, tekst, pewnosc],
    czasy etapow), a rapidocr obiekt RapidOCROutput z polami boxes, txts, scores.
    """
    if hasattr(raw, "txts"):
        texts = raw.txts or ()
        scores = raw.scores or ()
        boxes = raw.boxes if raw.boxes is not None else []
        entries: list[tuple[Any, str, float]] = []
        for index, text in enumerate(texts):
            box = boxes[index] if index < len(boxes) else []
            score = float(scores[index]) if index < len(scores) else 0.0
            entries.append((box, str(text), score))
        return entries
    result = raw[0] if isinstance(raw, tuple) else raw
    return [(entry[0], str(entry[1]), float(entry[2])) for entry in result or []]


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
        self._backend: tuple[str, Any] | None = None
        self._reason = ""
        self._version = ""
        self._latin = _latin_model_paths()
        self._use_angle_cls = use_angle_cls
        self._text_score = text_score

    # --- dostepnosc -------------------------------------------------------

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        self._backend = _import_rapidocr()
        if self._backend is None:
            self._available = False
            self._reason = (
                "Pakiet rapidocr-onnxruntime (Python do 3.12) ani rapidocr "
                "(Python od 3.13) nie jest zainstalowany. Zainstaluj dodatek 'ocr-rapid'."
            )
            log.debug("ocr.rapidocr_missing")
            return False
        self._available = True
        return True

    def unavailable_reason(self) -> str:
        self.is_available()
        return self._reason

    def version(self) -> str:
        if self._version:
            return self._version
        if not self.is_available() or self._backend is None:
            return ""
        try:
            from importlib.metadata import version as pkg_version

            self._version = pkg_version(self._backend[0])
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
        if not self.is_available() or self._backend is None:
            raise OcrError(self.unavailable_reason())
        dist_name, engine_cls = self._backend
        if dist_name == "rapidocr-onnxruntime":
            self._engine = self._create_legacy_engine(engine_cls)
        else:
            self._engine = self._create_modern_engine(engine_cls)
        return self._engine

    def _create_legacy_engine(self, engine_cls: Any) -> Any:
        """Inicjalizuje rapidocr-onnxruntime (plaskie argumenty konstruktora)."""
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
            return engine_cls(**kwargs)
        except TypeError:
            # starsze wersje pakietu nie znaja czesci parametrow
            fallback: dict[str, Any] = {}
            if self._latin is not None:
                model, dictionary = self._latin
                fallback["rec_model_path"] = str(model)
                fallback["rec_keys_path"] = str(dictionary)
            return engine_cls(**fallback)
        except Exception as exc:
            raise OcrError("Nie udało się zainicjować silnika RapidOCR.", cause=exc) from exc

    def _create_modern_engine(self, engine_cls: Any) -> Any:
        """Inicjalizuje pakiet rapidocr (slownik params z kluczami z kropka)."""
        params: dict[str, Any] = {
            "Global.text_score": self._text_score,
            "Global.use_cls": self._use_angle_cls,
            "Global.log_level": "warning",
            # Twarda zasada projektu: wylacznie CPU.
            "EngineConfig.onnxruntime.use_cuda": False,
            "EngineConfig.onnxruntime.use_dml": False,
        }
        if self._latin is not None:
            model, dictionary = self._latin
            params["Rec.model_path"] = str(model)
            params["Rec.rec_keys_path"] = str(dictionary)
        try:
            return engine_cls(params=params)
        except Exception as exc:
            raise OcrError("Nie udało się zainicjować silnika RapidOCR.", cause=exc) from exc

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
            raw = engine(array)
        except Exception as exc:
            raise OcrError(f"RapidOCR nie rozpoznał strony {page}.", cause=exc) from exc

        lines: list[OcrLine] = []
        confidences: list[float] = []
        for box, text, score in _extract_entries(raw):
            if not text.strip():
                continue
            confidences.append(score)
            xs = [int(point[0]) for point in box] if box is not None and len(box) else []
            ys = [int(point[1]) for point in box] if box is not None and len(box) else []
            rect = (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)) if xs else None
            lines.append(OcrLine(text=text, confidence=score, box=rect))

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

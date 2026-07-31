"""Adapter Tesseract OCR.

Tesseract z modelem ``pol`` daje najlepsza jakosc dla polskich dokumentow drukowanych,
ale wymaga instalacji komponentu systemowego. Adapter wykrywa jego obecnosc i nie
zaklada, ze jest dostepny. Gdy brakuje Tesseracta, aplikacja uzywa silnika
pip-owalnego, ktory nie wymaga instalatora.

Wywolanie odbywa sie przez proces potomny, bez pytesseract, zeby nie dokladac
zaleznosci i miec pelna kontrole nad limitem czasu.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
import winreg
from pathlib import Path
from typing import TYPE_CHECKING

from finddocs.errors import OcrError
from finddocs.logging_setup import get_logger
from finddocs.ocr.base import OcrEngine, OcrLine, OcrPageResult
from finddocs.types import CancellationToken

if TYPE_CHECKING:  # pragma: no cover
    from PIL.Image import Image

log = get_logger(__name__)

ENGINE_NAME = "tesseract"

#: Typowe lokalizacje instalacji na Windows.
WINDOWS_CANDIDATES: tuple[str, ...] = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)

DEFAULT_TIMEOUT = 120.0
PSM_AUTO_OSD = "1"
OEM_LSTM = "3"


def _from_registry() -> str | None:
    """Odczytuje sciezke instalacji z rejestru Windows."""
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for subkey in (r"SOFTWARE\Tesseract-OCR", r"SOFTWARE\WOW6432Node\Tesseract-OCR"):
            try:
                with winreg.OpenKey(root, subkey) as key:
                    value, _ = winreg.QueryValueEx(key, "Path")
            except OSError:
                continue
            candidate = Path(str(value)) / "tesseract.exe"
            if candidate.exists():
                return str(candidate)
    return None


def find_tesseract(explicit_path: str = "") -> str | None:
    """Znajduje plik wykonywalny Tesseracta."""
    if explicit_path:
        candidate = Path(explicit_path)
        if candidate.is_file():
            return str(candidate)
        nested = candidate / "tesseract.exe"
        if nested.is_file():
            return str(nested)
    found = shutil.which("tesseract")
    if found:
        return found
    for path in WINDOWS_CANDIDATES:
        if Path(path).is_file():
            return path
    env_path = os.environ.get("TESSERACT_PATH", "")
    if env_path and Path(env_path).is_file():
        return env_path
    return _from_registry()


class TesseractEngine(OcrEngine):
    """OCR przez zainstalowany lokalnie Tesseract."""

    name = ENGINE_NAME
    priority = 100
    supports_rotation = True
    provides_confidence = True

    def __init__(self, executable: str = "", timeout: float = DEFAULT_TIMEOUT) -> None:
        self._explicit = executable
        self._timeout = timeout
        self._path: str | None = None
        self._version: str = ""
        self._languages: list[str] = []
        self._probed = False

    # --- wykrywanie -------------------------------------------------------

    def _probe(self) -> None:
        if self._probed:
            return
        self._probed = True
        self._path = find_tesseract(self._explicit)
        if not self._path:
            return
        try:
            out = subprocess.run(  # noqa: S603 - sciezka pochodzi z wykrywania, nie od uzytkownika
                [self._path, "--version"],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            match = re.search(r"tesseract\s+v?([\d.]+)", out.stdout, re.IGNORECASE)
            self._version = match.group(1) if match else out.stdout.strip().splitlines()[0]
            langs = subprocess.run(  # noqa: S603
                [self._path, "--list-langs"],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            lines = [line.strip() for line in langs.stdout.splitlines()[1:] if line.strip()]
            self._languages = lines
        except (OSError, subprocess.SubprocessError, IndexError) as exc:
            log.warning("ocr.tesseract_probe_failed", error_type=type(exc).__name__)
            self._path = None

    def is_available(self) -> bool:
        self._probe()
        return bool(self._path)

    def unavailable_reason(self) -> str:
        self._probe()
        if self._path:
            return ""
        return (
            "Nie znaleziono programu Tesseract OCR. Zainstaluj go razem z modelem "
            "jezyka polskiego albo wskaz sciezke w ustawieniach."
        )

    def version(self) -> str:
        self._probe()
        return self._version

    def supported_languages(self) -> list[str]:
        self._probe()
        return list(self._languages)

    def has_polish(self) -> bool:
        return "pol" in self.supported_languages()

    # --- rozpoznawanie ----------------------------------------------------

    def recognize(
        self,
        image: Image,
        *,
        languages: list[str],
        page: int = 1,
        cancel: CancellationToken | None = None,
    ) -> OcrPageResult:
        self._probe()
        if not self._path:
            raise OcrError(self.unavailable_reason())
        if cancel is not None:
            cancel.raise_if_cancelled()

        available = set(self.supported_languages())
        requested = [lang for lang in languages if lang in available] or ["pol", "eng"]
        lang_arg = "+".join(dict.fromkeys(requested))

        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="fd-ocr-") as tmp:
            image_path = Path(tmp) / "page.png"
            image.save(image_path, format="PNG")
            output_base = Path(tmp) / "out"
            command = [
                self._path,
                str(image_path),
                str(output_base),
                "-l",
                lang_arg,
                "--psm",
                PSM_AUTO_OSD,
                "--oem",
                OEM_LSTM,
                "tsv",
            ]
            try:
                completed = subprocess.run(  # noqa: S603
                    command,
                    capture_output=True,
                    text=True,
                    timeout=self._timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise OcrError(
                    f"Rozpoznawanie strony {page} przekroczylo limit czasu.", cause=exc
                ) from exc
            except OSError as exc:
                raise OcrError("Nie udalo sie uruchomic programu Tesseract.", cause=exc) from exc

            tsv_path = output_base.with_suffix(".tsv")
            if completed.returncode != 0 or not tsv_path.exists():
                raise OcrError(
                    f"Tesseract zakonczyl prace bledem dla strony {page}.",
                    details={"returncode": completed.returncode},
                )
            lines, confidence = _parse_tsv(tsv_path.read_text(encoding="utf-8", errors="replace"))

        text = "\n".join(line.text for line in lines if line.text.strip())
        return OcrPageResult(
            page=page,
            text=text,
            confidence=confidence,
            lines=lines,
            engine=self.name,
            duration_seconds=time.monotonic() - started,
        )


def _parse_tsv(content: str) -> tuple[list[OcrLine], float | None]:
    """Zamienia wyjscie TSV Tesseracta na linie tekstu i srednia pewnosc."""
    rows = content.splitlines()
    if not rows:
        return [], None
    header = rows[0].split("\t")
    try:
        idx_text = header.index("text")
        idx_conf = header.index("conf")
        idx_line = header.index("line_num")
        idx_par = header.index("par_num")
        idx_block = header.index("block_num")
        idx_left = header.index("left")
        idx_top = header.index("top")
        idx_width = header.index("width")
        idx_height = header.index("height")
    except ValueError:
        return [], None

    grouped: dict[tuple[str, str, str], list[tuple[str, float, tuple[int, int, int, int]]]] = {}
    for raw in rows[1:]:
        parts = raw.split("\t")
        if len(parts) <= idx_text:
            continue
        word = parts[idx_text].strip()
        if not word:
            continue
        try:
            confidence = float(parts[idx_conf])
        except ValueError:
            confidence = -1.0
        if confidence < 0:
            continue
        try:
            box = (
                int(parts[idx_left]),
                int(parts[idx_top]),
                int(parts[idx_width]),
                int(parts[idx_height]),
            )
        except ValueError:
            box = (0, 0, 0, 0)
        key = (parts[idx_block], parts[idx_par], parts[idx_line])
        grouped.setdefault(key, []).append((word, confidence, box))

    lines: list[OcrLine] = []
    all_confidences: list[float] = []
    for words in grouped.values():
        text = " ".join(w for w, _, _ in words)
        confidences = [c for _, c, _ in words]
        all_confidences.extend(confidences)
        left = min(b[0] for _, _, b in words)
        top = min(b[1] for _, _, b in words)
        right = max(b[0] + b[2] for _, _, b in words)
        bottom = max(b[1] + b[3] for _, _, b in words)
        lines.append(
            OcrLine(
                text=text,
                confidence=sum(confidences) / len(confidences) / 100.0,
                box=(left, top, right - left, bottom - top),
            )
        )
    average = (sum(all_confidences) / len(all_confidences) / 100.0) if all_confidences else None
    return lines, average


__all__ = ["ENGINE_NAME", "WINDOWS_CANDIDATES", "TesseractEngine", "find_tesseract"]

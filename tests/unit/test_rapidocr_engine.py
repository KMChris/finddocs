"""Testy adaptera RapidOCR: obsluga starego i nowego pakietu.

Stary pakiet rapidocr-onnxruntime (Python do 3.12) zwraca krotke z lista wpisow,
nowy pakiet rapidocr (Python od 3.13) obiekt z polami txts, scores, boxes.
Testy podstawiaja falszywe moduly, wiec dzialaja bez zainstalowanego OCR.
"""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from finddocs.ocr.engines import rapidocr_engine
from finddocs.ocr.engines.rapidocr_engine import RapidOcrEngine, _extract_entries

QUAD_TOP = [[0, 0], [40, 0], [40, 10], [0, 10]]
QUAD_BOTTOM = [[5, 20], [30, 20], [30, 32], [5, 32]]


def test_extract_entries_stare_api() -> None:
    raw = ([[QUAD_TOP, "Faktura", 0.91]], [0.1, 0.2, 0.3])
    entries = _extract_entries(raw)
    assert entries == [(QUAD_TOP, "Faktura", 0.91)]


def test_extract_entries_stare_api_bez_wynikow() -> None:
    assert _extract_entries((None, [0.0])) == []


def test_extract_entries_nowe_api() -> None:
    raw = SimpleNamespace(
        txts=("Alfa", "Beta"),
        scores=(0.9, 0.8),
        boxes=np.array([QUAD_TOP, QUAD_BOTTOM]),
    )
    entries = _extract_entries(raw)
    assert [(text, score) for _box, text, score in entries] == [("Alfa", 0.9), ("Beta", 0.8)]
    assert np.array_equal(entries[0][0], np.array(QUAD_TOP))


def test_extract_entries_nowe_api_bez_wynikow() -> None:
    raw = SimpleNamespace(txts=None, scores=None, boxes=None)
    assert _extract_entries(raw) == []


def _fake_module(name: str, engine_cls: type) -> types.ModuleType:
    module = types.ModuleType(name)
    module.RapidOCR = engine_cls  # type: ignore[attr-defined]
    return module


def _obraz() -> Image.Image:
    return Image.new("RGB", (60, 40), "white")


def test_recognize_przez_stary_pakiet(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeLegacyRapidOcr:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def __call__(self, array: np.ndarray) -> tuple[list[list[object]], list[float]]:
            assert array.shape == (40, 60, 3)
            return [[QUAD_TOP, "Umowa najmu", 0.93]], [0.1]

    fake = _fake_module("rapidocr_onnxruntime", FakeLegacyRapidOcr)
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", fake)
    engine = RapidOcrEngine()
    result = engine.recognize(_obraz(), languages=["pol"])

    assert captured["det_use_cuda"] is False
    assert captured["rec_use_cuda"] is False
    assert result.text == "Umowa najmu"
    assert result.lines[0].box == (0, 0, 40, 10)
    assert result.confidence == pytest.approx(0.93)
    assert result.engine == "rapidocr"


def test_recognize_przez_nowy_pakiet(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeModernRapidOcr:
        def __init__(self, params: dict[str, object]) -> None:
            captured.update(params)

        def __call__(self, array: np.ndarray) -> SimpleNamespace:
            assert array.shape == (40, 60, 3)
            return SimpleNamespace(
                txts=("Alfa", "Beta"),
                scores=(0.9, 0.8),
                boxes=np.array([QUAD_BOTTOM, QUAD_TOP]),
            )

    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", None)
    monkeypatch.setitem(sys.modules, "rapidocr", _fake_module("rapidocr", FakeModernRapidOcr))
    engine = RapidOcrEngine(text_score=0.6, use_angle_cls=False)
    result = engine.recognize(_obraz(), languages=["pol"])

    assert captured["Global.text_score"] == 0.6
    assert captured["Global.use_cls"] is False
    assert captured["EngineConfig.onnxruntime.use_cuda"] is False
    assert captured["EngineConfig.onnxruntime.use_dml"] is False
    # linie sa sortowane wg polozenia, wiec Alfa (dolna ramka) jest druga
    assert result.text == "Beta\nAlfa"
    assert result.confidence == pytest.approx(0.85)
    assert result.lines[0].box == (0, 0, 40, 10)


def test_brak_obu_pakietow_daje_czytelny_powod(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", None)
    monkeypatch.setitem(sys.modules, "rapidocr", None)
    engine = RapidOcrEngine()
    assert engine.is_available() is False
    assert "ocr-rapid" in engine.unavailable_reason()
    assert engine.version() == ""


def test_wykrywa_stary_pakiet_przed_nowym(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeLegacy:
        pass

    monkeypatch.setitem(
        sys.modules, "rapidocr_onnxruntime", _fake_module("rapidocr_onnxruntime", FakeLegacy)
    )
    backend = rapidocr_engine._import_rapidocr()
    assert backend is not None
    assert backend[0] == "rapidocr-onnxruntime"

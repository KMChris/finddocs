"""Testy doboru urzadzen obliczen dla lokalnego dostawcy ONNX.

Dobor providerow nie tworzy sesji, wiec testy dzialaja bez GPU: dostepnosc
srodowiska jest podstawiana przez monkeypatch na onnxruntime.
"""

from __future__ import annotations

import onnxruntime
import pytest

from finddocs.errors import ConfigurationError
from finddocs.providers.onnx_local import (
    ALLOWED_EXECUTION_PROVIDERS,
    CPU_EXECUTION_PROVIDERS,
    available_devices,
    resolve_execution_providers,
)


def _set_available(monkeypatch: pytest.MonkeyPatch, providers: list[str]) -> None:
    monkeypatch.setattr(onnxruntime, "get_available_providers", lambda: list(providers))


def test_domyslny_cpu_zawsze_dostepny(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_available(monkeypatch, ["CPUExecutionProvider"])
    providers, device = resolve_execution_providers("cpu")
    assert providers == ["CPUExecutionProvider"]
    assert device == "cpu"


def test_dml_dostepny_konczy_sie_rezerwa_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_available(monkeypatch, ["DmlExecutionProvider", "CPUExecutionProvider"])
    providers, device = resolve_execution_providers("dml")
    assert providers == ["DmlExecutionProvider", "CPUExecutionProvider"]
    assert device == "dml"


def test_cuda_dostepny(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_available(monkeypatch, ["CUDAExecutionProvider", "CPUExecutionProvider"])
    providers, device = resolve_execution_providers("cuda")
    assert providers == ["CUDAExecutionProvider", "CPUExecutionProvider"]
    assert device == "cuda"


def test_niedostepne_gpu_spada_na_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_available(monkeypatch, ["CPUExecutionProvider"])
    providers, device = resolve_execution_providers("dml")
    assert providers == ["CPUExecutionProvider"]
    assert device == "cpu"


def test_auto_woli_dml_przed_cuda(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_available(
        monkeypatch,
        ["CUDAExecutionProvider", "DmlExecutionProvider", "CPUExecutionProvider"],
    )
    providers, device = resolve_execution_providers("auto")
    assert device == "dml"
    assert providers[0] == "DmlExecutionProvider"


def test_auto_bez_gpu_wybiera_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_available(monkeypatch, ["CPUExecutionProvider"])
    providers, device = resolve_execution_providers("auto")
    assert providers == ["CPUExecutionProvider"]
    assert device == "cpu"


def test_azure_nigdy_nie_trafia_do_listy(monkeypatch: pytest.MonkeyPatch) -> None:
    """AzureExecutionProvider wysyla dane poza komputer i jest zawsze pomijany."""
    _set_available(monkeypatch, ["AzureExecutionProvider", "CPUExecutionProvider"])
    for requested in ("cpu", "auto", "dml", "cuda"):
        providers, _ = resolve_execution_providers(requested)
        assert "AzureExecutionProvider" not in providers
        assert set(providers) <= set(ALLOWED_EXECUTION_PROVIDERS)


def test_nieznane_urzadzenie_zglasza_blad_konfiguracji() -> None:
    with pytest.raises(ConfigurationError):
        resolve_execution_providers("tpu")


def test_available_devices_mapuje_providery(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_available(monkeypatch, ["DmlExecutionProvider", "CPUExecutionProvider"])
    devices = available_devices()
    assert devices == {"cpu": True, "dml": True, "cuda": False}


def test_lista_dozwolonych_nie_zawiera_azure() -> None:
    assert "AzureExecutionProvider" not in ALLOWED_EXECUTION_PROVIDERS
    assert CPU_EXECUTION_PROVIDERS == ("CPUExecutionProvider",)

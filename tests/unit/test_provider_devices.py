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
    preload_cuda_libraries,
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


def test_auto_woli_cuda_przed_dml(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_available(
        monkeypatch,
        ["DmlExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider"],
    )
    providers, device = resolve_execution_providers("auto")
    assert device == "cuda"
    assert providers[0] == "CUDAExecutionProvider"


def test_auto_bez_cuda_wybiera_dml(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_available(monkeypatch, ["DmlExecutionProvider", "CPUExecutionProvider"])
    providers, device = resolve_execution_providers("auto")
    assert device == "dml"
    assert providers == ["DmlExecutionProvider", "CPUExecutionProvider"]


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


def test_preload_cuda_wola_api_onnxruntime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Biblioteki NVIDIA z pip wymagaja preload_dlls, inaczej CUDA nie wstanie."""
    calls: list[bool] = []
    monkeypatch.setattr(onnxruntime, "preload_dlls", lambda: calls.append(True), raising=False)
    preload_cuda_libraries()
    assert calls == [True]


def test_preload_cuda_bez_api_nie_zglasza_bledu(monkeypatch: pytest.MonkeyPatch) -> None:
    """Starsze wydania onnxruntime nie maja preload_dlls; to nie jest blad."""
    monkeypatch.delattr(onnxruntime, "preload_dlls", raising=False)
    preload_cuda_libraries()

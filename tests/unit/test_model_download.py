"""Testy pobierania modeli z Hugging Face na atrapie transportu httpx.

Zadne polaczenie nie wychodzi poza proces: httpx.MockTransport podaje
przygotowane odpowiedzi. Osobno sprawdzana jest polityka sieciowa, ktora
musi blokowac pobieranie przy wylaczonej kategorii model_download.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from finddocs.errors import DownloadError, ModelNotAvailableError, NetworkPolicyError
from finddocs.providers.model_download import (
    DownloadPlan,
    RepoFile,
    RepoInfo,
    download_files,
    download_repo,
    fetch_repo_info,
    select_download_files,
)
from finddocs.security.network import EgressCategory, NetworkPolicy

REPO = "org/model-testowy"

_FILE_PAYLOADS: dict[str, bytes] = {
    "config.json": json.dumps({"model_type": "bert", "hidden_size": 8}).encode(),
    "tokenizer.json": b"{}",
    "1_Pooling/config.json": json.dumps({"pooling_mode_mean_tokens": True}).encode(),
    "onnx/model.onnx": b"onnx-fp32-bajty",
    "onnx/model_quantized.onnx": b"onnx-int8-bajty",
    "model.safetensors": b"wagi-safetensors",
}


def _tree_entry(path: str, *, lfs: bool = False) -> dict[str, object]:
    payload = _FILE_PAYLOADS[path]
    entry: dict[str, object] = {"type": "file", "path": path, "size": len(payload)}
    if lfs:
        entry["lfs"] = {"oid": hashlib.sha256(payload).hexdigest(), "size": len(payload)}
    return entry


def _transport(*, tree: list[dict[str, object]], corrupt: str = "") -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith(f"https://huggingface.co/api/models/{REPO}/tree/main"):
            return httpx.Response(200, json=tree)
        if url == f"https://huggingface.co/api/models/{REPO}":
            return httpx.Response(200, json={"cardData": {"license": "mit"}, "tags": []})
        marker = f"/{REPO}/resolve/main/"
        if marker in url:
            name = url.split(marker, 1)[1]
            if name in _FILE_PAYLOADS:
                payload = b"zepsute" if name == corrupt else _FILE_PAYLOADS[name]
                return httpx.Response(200, content=payload)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _policy() -> NetworkPolicy:
    return NetworkPolicy(enabled_categories={EgressCategory.MODEL_DOWNLOAD})


def _onnx_tree() -> list[dict[str, object]]:
    return [
        _tree_entry("config.json"),
        _tree_entry("tokenizer.json"),
        _tree_entry("1_Pooling/config.json"),
        _tree_entry("onnx/model.onnx", lfs=True),
        _tree_entry("onnx/model_quantized.onnx", lfs=True),
    ]


# --- dobor plikow ---------------------------------------------------------------


def _info(paths: list[str]) -> RepoInfo:
    files = {p: RepoFile(path=p, size=len(_FILE_PAYLOADS.get(p, b"x"))) for p in paths}
    return RepoInfo(repo_id=REPO, license_name="mit", files=files)


def test_select_preferuje_gotowy_eksport_onnx() -> None:
    info = _info(["config.json", "tokenizer.json", "onnx/model.onnx", "model.safetensors"])
    plan = select_download_files(
        info, torch_available=True, can_quantize_locally=True, quantize=True
    )
    assert plan.strategy == "onnx"
    assert "onnx/model.onnx" in plan.paths
    assert "model.safetensors" not in plan.paths


def test_select_bierze_gotowy_int8_gdy_brak_kwantyzacji_lokalnej() -> None:
    info = _info(["tokenizer.json", "onnx/model.onnx", "onnx/model_quantized.onnx"])
    plan = select_download_files(
        info, torch_available=False, can_quantize_locally=False, quantize=True
    )
    assert "onnx/model_quantized.onnx" in plan.paths
    assert any("INT8" in note for note in plan.notes)

    plan_local = select_download_files(
        info, torch_available=False, can_quantize_locally=True, quantize=True
    )
    assert "onnx/model_quantized.onnx" not in plan_local.paths


def test_select_wagi_wymagaja_torch() -> None:
    info = _info(["config.json", "tokenizer.json", "model.safetensors"])
    plan = select_download_files(
        info, torch_available=True, can_quantize_locally=True, quantize=True
    )
    assert plan.strategy == "weights"
    assert "model.safetensors" in plan.paths

    with pytest.raises(ModelNotAvailableError, match="finddocs\\[export\\]"):
        select_download_files(
            info, torch_available=False, can_quantize_locally=False, quantize=True
        )


def test_select_wymaga_tokenizera_i_modelu() -> None:
    with pytest.raises(ModelNotAvailableError, match=r"tokenizer\.json"):
        select_download_files(
            _info(["config.json", "onnx/model.onnx"]),
            torch_available=True,
            can_quantize_locally=True,
            quantize=True,
        )
    with pytest.raises(ModelNotAvailableError, match="ani wag"):
        select_download_files(
            _info(["config.json", "tokenizer.json"]),
            torch_available=True,
            can_quantize_locally=True,
            quantize=True,
        )


# --- API i pobieranie -----------------------------------------------------------


def test_fetch_repo_info_czyta_licencje_i_sumy() -> None:
    info = fetch_repo_info(REPO, policy=_policy(), transport=_transport(tree=_onnx_tree()))
    assert info.license_name == "mit"
    assert info.files["onnx/model.onnx"].sha256
    assert info.files["tokenizer.json"].sha256 == ""


def test_fetch_repo_info_nieistniejace_repo() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with pytest.raises(ModelNotAvailableError, match="nie istnieje"):
        fetch_repo_info(REPO, policy=_policy(), transport=httpx.MockTransport(handler))


def test_polityka_blokuje_pobieranie_bez_zgody() -> None:
    with pytest.raises(NetworkPolicyError):
        fetch_repo_info(
            REPO, policy=NetworkPolicy.offline(), transport=_transport(tree=_onnx_tree())
        )


def test_download_repo_zapisuje_pliki_i_weryfikuje_sumy(tmp_path: Path) -> None:
    result = download_repo(
        REPO,
        tmp_path / "pobrane",
        policy=_policy(),
        transport=_transport(tree=_onnx_tree()),
        torch_available=False,
        can_quantize_locally=False,
    )
    assert result.strategy == "onnx"
    assert (tmp_path / "pobrane" / "onnx" / "model.onnx").read_bytes() == b"onnx-fp32-bajty"
    assert (tmp_path / "pobrane" / "1_Pooling" / "config.json").exists()
    assert result.license_name == "mit"


def test_download_wykrywa_przeklamana_sume(tmp_path: Path) -> None:
    info = fetch_repo_info(
        REPO, policy=_policy(), transport=_transport(tree=_onnx_tree(), corrupt="onnx/model.onnx")
    )
    plan = DownloadPlan(strategy="onnx", paths=["onnx/model.onnx"], total_bytes=64)
    with pytest.raises(DownloadError, match="Suma kontrolna"):
        download_files(
            info,
            plan,
            tmp_path / "pobrane",
            policy=_policy(),
            transport=_transport(tree=_onnx_tree(), corrupt="onnx/model.onnx"),
        )
    assert not (tmp_path / "pobrane" / "onnx" / "model.onnx").exists()


def test_download_odrzuca_zbyt_male_wolne_miejsce(tmp_path: Path) -> None:
    info = _info(["tokenizer.json"])
    plan = DownloadPlan(strategy="onnx", paths=["tokenizer.json"], total_bytes=1 << 60)
    with pytest.raises(DownloadError, match="miejsca"):
        download_files(info, plan, tmp_path / "pobrane", policy=_policy())

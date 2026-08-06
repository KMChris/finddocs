"""Testy magazynu modeli: rozpoznawanie zrodel, import, lista i usuwanie.

Testy nie korzystaja z sieci ani z prawdziwych modeli ONNX. Probny przebieg
modelu i walidacje dostawcy zastepuja atrapy, bo tu sprawdzamy mechanike
importu, a nie sam ONNX Runtime (to robi test integracyjny requires_model).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from finddocs.app_paths import AppPaths
from finddocs.errors import ModelNotAvailableError
from finddocs.providers import model_store
from finddocs.providers.model_export import detect_pad_token, write_manifest
from finddocs.providers.model_manifest import (
    LocalModelManifest,
    describe_models,
    find_model_dir,
)
from finddocs.providers.model_store import (
    ImportOptions,
    classify_local_source,
    detect_pooling,
    import_local_model,
    looks_like_repo_id,
    remove_model,
    sanitize_model_key,
)

pytestmark = pytest.mark.usefixtures("tmp_home")


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def make_onnx_source(
    root: Path,
    *,
    fp32: bool = True,
    quantized_name: str = "",
    nested: bool = False,
    pooling_cls: bool | None = True,
) -> Path:
    """Buduje katalog udajacy gotowy eksport ONNX (pliki-atrapy)."""
    source = root / "zrodlo"
    model_dir = source / "onnx" if nested else source
    model_dir.mkdir(parents=True, exist_ok=True)
    if fp32:
        (model_dir / "model.onnx").write_bytes(b"onnx-fp32")
    if quantized_name:
        (model_dir / quantized_name).write_bytes(b"onnx-int8")
    (source / "tokenizer.json").write_text("{}", encoding="utf-8")
    _write_json(
        source / "config.json",
        {"model_type": "bert", "hidden_size": 8, "max_position_embeddings": 130},
    )
    if pooling_cls is not None:
        _write_json(
            source / "1_Pooling" / "config.json",
            {
                "pooling_mode_cls_token": pooling_cls,
                "pooling_mode_mean_tokens": not pooling_cls,
            },
        )
    return source


@pytest.fixture
def fake_runtime(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Zastepuje probny przebieg ONNX i walidacje dostawcy atrapami."""
    calls: dict[str, Any] = {"probe": 0, "validate": 0}

    def fake_probe(directory: Path) -> dict[str, Any]:
        calls["probe"] += 1
        name = "model.int8.onnx" if (directory / "model.int8.onnx").exists() else "model.onnx"
        return {"dimension": 8, "rank": 3, "model_file": name}

    def fake_validate(directory: Path, *, expected_dimension: int) -> None:
        calls["validate"] += 1
        assert expected_dimension == 8

    monkeypatch.setattr(model_store, "probe_onnx_model", fake_probe)
    monkeypatch.setattr(model_store, "_validate_with_provider", fake_validate)
    return calls


# --- rozpoznawanie --------------------------------------------------------------


def test_sanitize_model_key() -> None:
    assert sanitize_model_key("sdadas/mmlw base") == "sdadas-mmlw-base"
    assert sanitize_model_key("Model_1.2") == "Model_1.2"
    with pytest.raises(ModelNotAvailableError):
        sanitize_model_key("...")


def test_looks_like_repo_id() -> None:
    assert looks_like_repo_id("sdadas/mmlw-retrieval-roberta-base")
    assert looks_like_repo_id("intfloat/multilingual-e5-small")
    assert not looks_like_repo_id("C:\\modele\\mmlw")
    assert not looks_like_repo_id("mmlw")
    assert not looks_like_repo_id("a/b/c")


def test_classify_local_source_wykrywa_rodzaje(tmp_path: Path) -> None:
    flat = make_onnx_source(tmp_path / "flat")
    kind, resolved = classify_local_source(flat)
    assert kind == "onnx" and resolved == flat

    nested = make_onnx_source(tmp_path / "nested", nested=True)
    kind, resolved = classify_local_source(nested)
    assert kind == "onnx" and resolved == nested / "onnx"

    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    _write_json(checkpoint / "config.json", {"model_type": "bert"})
    (checkpoint / "model.safetensors").write_bytes(b"wagi")
    kind, resolved = classify_local_source(checkpoint)
    assert kind == "checkpoint" and resolved == checkpoint


def test_classify_local_source_bez_tokenizera(tmp_path: Path) -> None:
    source = tmp_path / "bez-tokenizera"
    source.mkdir()
    (source / "model.onnx").write_bytes(b"onnx")
    with pytest.raises(ModelNotAvailableError, match=r"tokenizer\.json"):
        classify_local_source(source)


def test_classify_local_source_pusty_katalog(tmp_path: Path) -> None:
    empty = tmp_path / "pusty"
    empty.mkdir()
    with pytest.raises(ModelNotAvailableError, match="nie wygląda na model"):
        classify_local_source(empty)


def test_detect_pooling(tmp_path: Path) -> None:
    cls_dir = make_onnx_source(tmp_path / "cls", pooling_cls=True)
    mean_dir = make_onnx_source(tmp_path / "mean", pooling_cls=False)
    none_dir = make_onnx_source(tmp_path / "none", pooling_cls=None)
    assert detect_pooling(cls_dir) == "cls"
    assert detect_pooling(mean_dir) == "mean"
    assert detect_pooling(none_dir) is None


def test_detect_pad_token(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    _write_json(plain / "special_tokens_map.json", {"pad_token": "[PAD]"})
    assert detect_pad_token(plain) == "[PAD]"

    nested = tmp_path / "nested"
    _write_json(nested / "special_tokens_map.json", {"pad_token": {"content": "<pad>"}})
    assert detect_pad_token(nested) == "<pad>"

    config_only = tmp_path / "config-only"
    _write_json(config_only / "tokenizer_config.json", {"pad_token": "<pad>"})
    assert detect_pad_token(config_only) == "<pad>"

    assert detect_pad_token(tmp_path / "brak") == ""


# --- import ---------------------------------------------------------------------


def test_import_normalizuje_kwantyzowany_eksport(
    tmp_path: Path, tmp_home: AppPaths, fake_runtime: dict[str, Any]
) -> None:
    source = make_onnx_source(tmp_path, quantized_name="model_quantized.onnx")
    imported = import_local_model(source, ImportOptions(name="wlasny"), paths=tmp_home)

    assert imported.key == "wlasny"
    assert imported.directory == tmp_home.models_dir / "wlasny" / "onnx"
    assert imported.model_files == ["model.int8.onnx"]
    assert not (imported.directory / "model.onnx").exists()
    assert fake_runtime["probe"] == 1 and fake_runtime["validate"] == 1

    manifest = LocalModelManifest.load(imported.directory)
    assert manifest.model_key == "wlasny"
    assert manifest.pooling == "cls"
    assert manifest.dimension == 8
    assert manifest.quantized is True
    assert manifest.max_sequence_length == 128
    assert "model.int8.onnx" in manifest.files


def test_import_zachowuje_fp32_na_zyczenie(
    tmp_path: Path, tmp_home: AppPaths, fake_runtime: dict[str, Any]
) -> None:
    source = make_onnx_source(tmp_path, quantized_name="model.int8.onnx")
    imported = import_local_model(source, ImportOptions(name="oba", keep_fp32=True), paths=tmp_home)
    assert sorted(imported.model_files) == ["model.int8.onnx", "model.onnx"]


def test_import_bez_kwantyzacji_zostawia_fp32_z_uwaga(
    tmp_path: Path, tmp_home: AppPaths, fake_runtime: dict[str, Any]
) -> None:
    source = make_onnx_source(tmp_path)
    imported = import_local_model(source, ImportOptions(name="fp32"), paths=tmp_home)
    assert imported.model_files == ["model.onnx"]
    assert any("kwantyzacj" in note.lower() for note in imported.notes)


def test_import_nieznanego_modelu_ostrzega_o_przedrostkach(
    tmp_path: Path, tmp_home: AppPaths, fake_runtime: dict[str, Any]
) -> None:
    source = make_onnx_source(tmp_path)
    imported = import_local_model(source, ImportOptions(name="obcy"), paths=tmp_home)
    assert imported.query_prefix == "" and imported.passage_prefix == ""
    assert any("przedrostk" in note.lower() for note in imported.notes)


def test_import_z_flagami_przedrostkow(
    tmp_path: Path, tmp_home: AppPaths, fake_runtime: dict[str, Any]
) -> None:
    options = ImportOptions(name="e5", query_prefix="query: ", passage_prefix="passage: ")
    imported = import_local_model(make_onnx_source(tmp_path), options, paths=tmp_home)
    assert imported.query_prefix == "query: "
    assert imported.passage_prefix == "passage: "
    manifest = LocalModelManifest.load(imported.directory)
    assert manifest.query_prefix == "query: "
    assert not any("przedrostk" in note.lower() for note in imported.notes)


def test_import_kolizja_nazwy_wymaga_force(
    tmp_path: Path, tmp_home: AppPaths, fake_runtime: dict[str, Any]
) -> None:
    source = make_onnx_source(tmp_path)
    import_local_model(source, ImportOptions(name="powtorka"), paths=tmp_home)
    with pytest.raises(ModelNotAvailableError, match="--force"):
        import_local_model(source, ImportOptions(name="powtorka"), paths=tmp_home)
    imported = import_local_model(
        source, ImportOptions(name="powtorka", force=True), paths=tmp_home
    )
    assert imported.directory.exists()


def test_import_checkpointu_bez_torch_daje_wskazowke(
    tmp_path: Path, tmp_home: AppPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    _write_json(checkpoint / "config.json", {"model_type": "bert"})
    (checkpoint / "model.safetensors").write_bytes(b"wagi")
    (checkpoint / "tokenizer.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(model_store, "missing_export_packages", lambda: ["torch"])
    with pytest.raises(ModelNotAvailableError, match="finddocs\\[export\\]"):
        import_local_model(checkpoint, ImportOptions(name="ck"), paths=tmp_home)


def test_import_model_z_gotowym_wektorem_ma_pooling_none(
    tmp_path: Path, tmp_home: AppPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_probe(directory: Path) -> dict[str, Any]:
        return {"dimension": 8, "rank": 2, "model_file": "model.onnx"}

    monkeypatch.setattr(model_store, "probe_onnx_model", fake_probe)
    monkeypatch.setattr(model_store, "_validate_with_provider", lambda d, expected_dimension: None)
    imported = import_local_model(
        make_onnx_source(tmp_path), ImportOptions(name="pooled"), paths=tmp_home
    )
    assert imported.pooling == "none"


# --- lista i usuwanie -----------------------------------------------------------


def _install_fake_model(tmp_home: AppPaths, key: str) -> Path:
    directory = tmp_home.models_dir / key / "onnx"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "model.int8.onnx").write_bytes(b"onnx")
    (directory / "tokenizer.json").write_text("{}", encoding="utf-8")
    write_manifest(
        directory,
        model_key=key,
        source="https://example.invalid/model",
        license_name="MIT",
        architecture="bert",
        dimension=8,
        max_sequence_length=128,
        pooling="mean",
        normalize=True,
        query_prefix="query: ",
        passage_prefix="",
        opset=14,
        quantized=True,
        pad_token="[PAD]",
        display_name="Model testowy",
    )
    return directory


def test_describe_models_zawiera_zaimportowany_model(tmp_home: AppPaths) -> None:
    directory = _install_fake_model(tmp_home, "wlasny-model")
    rows = {row["klucz"]: row for row in describe_models()}
    assert "wlasny-model" in rows
    row = rows["wlasny-model"]
    assert row["zainstalowany"] is True
    assert row["nazwa"] == "Model testowy"
    assert row["katalog"] == str(directory)
    assert rows["mmlw-retrieval-roberta-base"]["domyślny"] is True


def test_find_model_dir_znajduje_zaimportowany_model(tmp_home: AppPaths) -> None:
    directory = _install_fake_model(tmp_home, "wlasny-model")
    assert find_model_dir("wlasny-model") == directory


def test_manifest_bez_nowych_pol_wczytuje_sie(tmp_home: AppPaths) -> None:
    directory = _install_fake_model(tmp_home, "stary")
    data = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    del data["pad_token"]
    del data["display_name"]
    (directory / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
    manifest = LocalModelManifest.load(directory)
    assert manifest.pad_token == ""
    assert manifest.display_name == ""


def test_remove_model(tmp_home: AppPaths) -> None:
    _install_fake_model(tmp_home, "do-usuniecia")
    removed = remove_model("do-usuniecia", paths=tmp_home)
    assert removed == tmp_home.models_dir / "do-usuniecia"
    assert not removed.exists()
    with pytest.raises(ModelNotAvailableError):
        remove_model("do-usuniecia", paths=tmp_home)

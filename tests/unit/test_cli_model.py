"""Testy polecen CLI run.py model na tymczasowym katalogu danych."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from finddocs.app_paths import AppPaths
from finddocs.cli import EXIT_ERROR, EXIT_OK, main
from finddocs.config import load_config
from finddocs.providers import model_store
from finddocs.providers.model_export import write_manifest

pytestmark = pytest.mark.usefixtures("tmp_home")


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
        max_sequence_length=200,
        pooling="mean",
        normalize=True,
        query_prefix="query: ",
        passage_prefix="passage: ",
        opset=14,
        quantized=True,
    )
    return directory


def test_model_list_json(tmp_home: AppPaths, capsys: pytest.CaptureFixture[str]) -> None:
    _install_fake_model(tmp_home, "wlasny")
    assert main(["--json", "model", "list"]) == EXIT_OK
    rows = json.loads(capsys.readouterr().out)
    by_key = {row["klucz"]: row for row in rows}
    assert by_key["mmlw-retrieval-roberta-base"]["aktywny"] is True
    assert by_key["wlasny"]["zainstalowany"] is True


def test_model_use_synchronizuje_konfiguracje(tmp_home: AppPaths) -> None:
    _install_fake_model(tmp_home, "wlasny")
    assert main(["model", "use", "wlasny"]) == EXIT_OK
    config = load_config(tmp_home.config_file)
    assert config.embedding.model_key == "wlasny"
    assert config.embedding.query_prefix == "query: "
    assert config.embedding.passage_prefix == "passage: "
    assert config.embedding.max_sequence_length == 200
    assert config.embedding.quantized is True


def test_model_use_niezainstalowany(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["model", "use", "nie-ma"]) == EXIT_ERROR
    assert "nie jest zainstalowany" in capsys.readouterr().err


def test_model_import_zle_zrodlo(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["model", "import", "X:\\nie\\ma\\katalogu", "--yes"]) == EXIT_ERROR
    assert "organizacja/nazwa" in capsys.readouterr().err


def test_model_import_lokalny_przez_cli(
    tmp_path: Path, tmp_home: AppPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "zrodlo"
    source.mkdir()
    (source / "model.onnx").write_bytes(b"onnx")
    (source / "tokenizer.json").write_text("{}", encoding="utf-8")

    def fake_probe(directory: Path) -> dict[str, Any]:
        return {"dimension": 8, "rank": 3, "model_file": "model.onnx"}

    monkeypatch.setattr(model_store, "probe_onnx_model", fake_probe)
    monkeypatch.setattr(model_store, "_validate_with_provider", lambda d, expected_dimension: None)
    assert main(["model", "import", str(source), "--name", "importowany", "--use"]) == EXIT_OK
    config = load_config(tmp_home.config_file)
    assert config.embedding.model_key == "importowany"
    assert (tmp_home.models_dir / "importowany" / "onnx" / "manifest.json").exists()


def test_model_remove_wymaga_potwierdzenia(tmp_home: AppPaths) -> None:
    directory = _install_fake_model(tmp_home, "do-kasacji")
    assert main(["model", "remove", "do-kasacji"]) == EXIT_ERROR
    assert directory.exists()
    assert main(["model", "remove", "do-kasacji", "--yes"]) == EXIT_OK
    assert not directory.parent.exists()

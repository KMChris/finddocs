"""Testy polecen CLI finddocs model na tymczasowym katalogu danych."""

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


def test_model_api_domyslnie_bez_zgody_na_http(
    tmp_home: AppPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--json", "model", "api"]) == EXIT_OK
    assert json.loads(capsys.readouterr().out)["http_do_localhost"] is False
    assert load_config(tmp_home.config_file).allow_plain_http_localhost is False


def test_model_api_zgoda_na_http_do_localhost(
    tmp_home: AppPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    kod = main(
        [
            "model",
            "api",
            "--url",
            "http://127.0.0.1:11434/v1",
            "--model",
            "qwen3-embedding:8b",
            "--dimension",
            "4096",
            "--allow-http-localhost",
            "--enable",
        ]
    )

    assert kod == EXIT_OK
    out = capsys.readouterr().out
    assert "tylko dla tego komputera" in out
    config = load_config(tmp_home.config_file)
    assert config.allow_plain_http_localhost is True
    assert config.embedding.provider == "internal_api"
    assert config.embedding.internal_api_dimension == 4096

    assert main(["model", "api", "--no-allow-http-localhost"]) == EXIT_OK
    assert "Wymagane jest https" in capsys.readouterr().out
    assert load_config(tmp_home.config_file).allow_plain_http_localhost is False


def test_doctor_pokazuje_faktyczna_polityke_sieciowa(
    tmp_home: AppPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    """Opis polityki nie moze pokazywac offline, gdy konfiguracja wypuszcza ruch."""
    kod = main(
        [
            "model",
            "api",
            "--url",
            "http://127.0.0.1:11434/v1",
            "--model",
            "model-zdalny",
            "--dimension",
            "8",
            "--allow-http-localhost",
            "--enable",
        ]
    )
    assert kod == EXIT_OK
    capsys.readouterr()

    assert main(["doctor"]) == EXIT_OK
    out = capsys.readouterr().out

    assert "'kategorie_wlaczone': ['internal_api']" in out
    assert "'http_do_localhost': True" in out
    assert "'internal_api': ['127.0.0.1']" in out


def test_model_context_pokazuje_stan_domyslny(
    tmp_home: AppPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--json", "model", "context"]) == EXIT_OK
    data = json.loads(capsys.readouterr().out)
    assert data["wzbogacenie_kontekstem"] is False


def test_model_context_enable_zapisuje_i_ostrzega(
    tmp_home: AppPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["model", "context", "--enable"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "przebudowy" in out
    assert load_config(tmp_home.config_file).embedding.enrich_context is True

    # Ponowne wlaczenie niczego nie zmienia i nie straszy przebudowa.
    assert main(["model", "context", "--enable"]) == EXIT_OK
    assert "przebudowy" not in capsys.readouterr().out

    assert main(["model", "context", "--disable"]) == EXIT_OK
    assert load_config(tmp_home.config_file).embedding.enrich_context is False

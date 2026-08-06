"""Test integracyjny importu prawdziwego modelu ONNX.

Korzysta z lokalnego modelu MMLW z katalogu models/ repozytorium. Przechodzi
pelna sciezke: kopiowanie, probny przebieg ONNX Runtime, zapis manifestu,
walidacje dostawcy i uzycie zaimportowanego modelu do policzenia embeddingu.
"""

from __future__ import annotations

import pytest

from finddocs.app_paths import AppPaths
from finddocs.providers.model_manifest import describe_models, find_model_dir
from finddocs.providers.model_store import ImportOptions, import_local_model
from finddocs.providers.onnx_local import create_local_provider


@pytest.mark.slow
@pytest.mark.requires_model
def test_import_prawdziwego_modelu(tmp_home: AppPaths) -> None:
    source = find_model_dir("mmlw-retrieval-roberta-base")
    if source is None:
        pytest.skip("Brak lokalnego modelu embeddingow w katalogu models/.")

    imported = import_local_model(source, ImportOptions(name="model-testowy"), paths=tmp_home)
    assert imported.dimension == 768
    assert imported.pooling == "cls"
    assert imported.quantized is True
    assert imported.directory == tmp_home.models_dir / "model-testowy" / "onnx"

    rows = {row["klucz"]: row for row in describe_models()}
    assert rows["model-testowy"]["zainstalowany"] is True

    provider = create_local_provider("model-testowy")
    try:
        vector = provider.embed_query("procedura przelewów")
        assert vector.shape == (768,)
        assert provider.info.query_prefix == "zapytanie: "
    finally:
        provider.close()

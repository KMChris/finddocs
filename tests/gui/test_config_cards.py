"""Testy kart konfiguracji wyszukiwania semantycznego i magazynu wektorow.

Import prawdziwych modeli sprawdza test integracyjny magazynu modeli. Tutaj
testujemy okablowanie kart: wypelnianie pol, panele warunkowe, zapis
konfiguracji i manifestu oraz sygnaly, ktorymi karty informuja widok zrodel
o zmianach.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox

from finddocs.config import EmbeddingProfile, ensure_profiles, load_config
from finddocs.gui import i18n
from finddocs.gui.config_cards import (
    ComputeCard,
    ModelCard,
    ProfileCard,
    SemanticCard,
    VectorStoreCard,
)
from finddocs.gui.context import AppContext
from finddocs.gui.model_dialog import ModelImportDialog
from finddocs.gui.sources_view import SourcesView
from finddocs.providers import model_store
from finddocs.providers.model_export import write_manifest
from finddocs.providers.model_manifest import LocalModelManifest
from finddocs.providers.model_store import ImportedModel

FAKE_KEY = "model-testowy-karty"


def _install_fake_model(context: AppContext, key: str = FAKE_KEY) -> Path:
    directory = context.paths.models_dir / key / "onnx"
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
        passage_prefix="passage: ",
        opset=14,
        quantized=True,
        display_name="Model testowy karty",
    )
    return directory


@pytest.fixture
def card_context(gui_context: AppContext) -> AppContext:
    """Kontekst bez dodatkowej sciezki modelu, zeby wyszukiwanie bylo standardowe."""
    gui_context.config.embedding.model_path = ""
    return gui_context


def _select_model(card: ModelCard, key: str) -> None:
    position = card.model_combo.findData(key)
    assert position >= 0
    card.model_combo.setCurrentIndex(position)


# --- karta semantyki -------------------------------------------------------------


@pytest.mark.gui
def test_wylaczenie_semantyki_dziala_od_razu(qtbot: object, card_context: AppContext) -> None:
    """Wlacznik nie ma przycisku Zastosuj: przelaczenie zapisuje konfiguracje."""
    card = SemanticCard(card_context)
    qtbot.addWidget(card)  # type: ignore[attr-defined]
    assert card.semantic_check.isChecked()
    zgloszenia: list[bool] = []
    card.applied.connect(zgloszenia.append)

    card.semantic_check.setChecked(False)

    assert zgloszenia == [True]
    assert card_context.config.embedding.semantic_enabled is False
    zapisana = load_config(card_context.paths.config_file)
    assert zapisana.embedding.semantic_enabled is False


@pytest.mark.gui
def test_opis_stanu_odroznia_wylaczenie_od_braku_modelu(
    qtbot: object, card_context: AppContext
) -> None:
    card = SemanticCard(card_context)
    qtbot.addWidget(card)  # type: ignore[attr-defined]
    assert card.status_label.text() == i18n.MODEL_MISSING

    card_context.config.embedding.semantic_enabled = False
    card.refresh()

    assert card.status_label.text() == i18n.MODEL_SEMANTIC_DISABLED
    assert not card.semantic_check.isChecked()


@pytest.mark.gui
def test_wlaczenie_wzbogacenia_zapisuje_konfiguracje_i_ostrzega(
    qtbot: object, card_context: AppContext, message_boxes: list[QMessageBox]
) -> None:
    """Przelacznik wzbogacenia uniewaznia wektory, wiec pokazuje uwage o przebudowie."""
    card = SemanticCard(card_context)
    qtbot.addWidget(card)  # type: ignore[attr-defined]
    assert not card.context_check.isChecked()
    zgloszenia: list[bool] = []
    card.applied.connect(zgloszenia.append)

    card.context_check.setChecked(True)

    assert zgloszenia == [True]
    assert card_context.config.embedding.enrich_context is True
    zapisana = load_config(card_context.paths.config_file)
    assert zapisana.embedding.enrich_context is True
    assert any(i18n.MODEL_REBUILD_REQUIRED in box.text() for box in message_boxes)


@pytest.mark.gui
def test_refresh_uzgadnia_przelacznik_wzbogacenia(qtbot: object, card_context: AppContext) -> None:
    card = SemanticCard(card_context)
    qtbot.addWidget(card)  # type: ignore[attr-defined]
    zgloszenia: list[bool] = []
    card.applied.connect(zgloszenia.append)

    card_context.config.embedding.enrich_context = True
    card.refresh()

    # Uzgodnienie stanu nie moze wyzwolic zapisu ani sygnalu applied.
    assert card.context_check.isChecked()
    assert zgloszenia == []


# --- karta modelu: przedrostki ------------------------------------------------


@pytest.mark.gui
def test_prefiksy_znanego_modelu_pochodza_z_rejestru(
    qtbot: object, card_context: AppContext
) -> None:
    card = ModelCard(card_context)
    qtbot.addWidget(card)  # type: ignore[attr-defined]

    _select_model(card, "multilingual-e5-small")

    assert card.query_edit.text() == "query: "
    assert card.passage_edit.text() == "passage: "


@pytest.mark.gui
def test_prefiksy_zainstalowanego_modelu_pochodza_z_manifestu(
    qtbot: object, card_context: AppContext
) -> None:
    _install_fake_model(card_context)
    card = ModelCard(card_context)
    qtbot.addWidget(card)  # type: ignore[attr-defined]

    _select_model(card, FAKE_KEY)

    assert card.query_edit.text() == "query: "
    assert card.passage_edit.text() == "passage: "
    # Manifest mowi tez, ze model jest skwantyzowany.
    assert card.quantized_check.isChecked()


@pytest.mark.gui
def test_zmiana_prefiksow_aktywnego_modelu_trafia_do_manifestu_i_konfiguracji(
    qtbot: object, card_context: AppContext, message_boxes: list[QMessageBox]
) -> None:
    directory = _install_fake_model(card_context)
    card_context.config.embedding.model_key = FAKE_KEY
    card = ModelCard(card_context)
    qtbot.addWidget(card)  # type: ignore[attr-defined]
    zgloszenia: list[bool] = []
    card.applied.connect(zgloszenia.append)

    card.query_edit.setText("pytanie: ")
    card.passage_edit.setText("")
    card.apply_settings()

    manifest = LocalModelManifest.load(directory)
    assert manifest.query_prefix == "pytanie: "
    assert manifest.passage_prefix == ""
    assert card_context.config.embedding.query_prefix == "pytanie: "
    assert card_context.config.embedding.passage_prefix == ""
    assert zgloszenia == [True]
    assert any(i18n.MODEL_REBUILD_REQUIRED in box.text() for box in message_boxes)


@pytest.mark.gui
def test_zastosowanie_modelu_synchronizuje_przedrostki(
    qtbot: object, card_context: AppContext, message_boxes: list[QMessageBox]
) -> None:
    """Zmiana modelu przepisuje jego parametry do konfiguracji, jak finddocs model use."""
    card = ModelCard(card_context)
    qtbot.addWidget(card)  # type: ignore[attr-defined]
    zgloszenia: list[bool] = []
    card.applied.connect(zgloszenia.append)

    _select_model(card, "multilingual-e5-small")
    card.apply_settings()

    embedding = card_context.config.embedding
    assert embedding.model_key == "multilingual-e5-small"
    assert embedding.query_prefix == "query: "
    assert embedding.passage_prefix == "passage: "
    assert zgloszenia == [True]
    assert any(i18n.MODEL_REBUILD_REQUIRED in box.text() for box in message_boxes)


@pytest.mark.gui
def test_zmiana_kwantyzacji_wymaga_przebudowy(
    qtbot: object, card_context: AppContext, message_boxes: list[QMessageBox]
) -> None:
    _install_fake_model(card_context)
    card_context.config.embedding.model_key = FAKE_KEY
    card_context.config.embedding.quantized = True
    card = ModelCard(card_context)
    qtbot.addWidget(card)  # type: ignore[attr-defined]

    card.quantized_check.setChecked(False)
    card.apply_settings()

    assert card_context.config.embedding.quantized is False
    assert any(i18n.MODEL_REBUILD_REQUIRED in box.text() for box in message_boxes)


# --- karta obliczen ---------------------------------------------------------------


@pytest.mark.gui
def test_panel_zdalny_jest_ukryty_dla_dostawcy_lokalnego(
    qtbot: object, card_context: AppContext
) -> None:
    """Pola sieciowe nie zaciemniaja karty, dopoki dostawca zdalny nie jest wybrany."""
    card = ComputeCard(card_context)
    qtbot.addWidget(card)  # type: ignore[attr-defined]

    assert not card.remote_selected()
    assert not card.local_panel.isHidden()
    assert card.remote_panel.isHidden()

    card.set_provider(True)

    assert card.local_panel.isHidden()
    assert not card.remote_panel.isHidden()


@pytest.mark.gui
def test_zmiana_urzadzenia_i_batcha_zapisuje_konfiguracje(
    qtbot: object, card_context: AppContext
) -> None:
    card = ComputeCard(card_context)
    qtbot.addWidget(card)  # type: ignore[attr-defined]
    zgloszenia: list[bool] = []
    card.applied.connect(zgloszenia.append)

    position = card.device_combo.findData("dml")
    assert position >= 0
    card.device_combo.setCurrentIndex(position)
    card.batch_spin.setValue(64)
    card.batch_docs_spin.setValue(16)
    card.apply_settings()

    assert zgloszenia == [True]
    zapisana = load_config(card_context.paths.config_file)
    assert zapisana.embedding.device == "dml"
    assert zapisana.embedding.batch_size == 64
    assert zapisana.indexing.embed_batch_documents == 16


@pytest.mark.gui
def test_wlaczenie_zdalnego_api_bez_adresu_daje_ostrzezenie(
    qtbot: object, card_context: AppContext, message_boxes: list[QMessageBox]
) -> None:
    card = ComputeCard(card_context)
    qtbot.addWidget(card)  # type: ignore[attr-defined]
    zgloszenia: list[bool] = []
    card.applied.connect(zgloszenia.append)

    card.set_provider(True)
    card.apply_settings()

    assert zgloszenia == []
    assert [box.text() for box in message_boxes] == [i18n.MODEL_REMOTE_URL_REQUIRED]
    assert card_context.config.embedding.provider == "local_onnx"


@pytest.mark.gui
def test_wlaczenie_zdalnego_api_przelacza_dostawce(
    qtbot: object, card_context: AppContext, message_boxes: list[QMessageBox]
) -> None:
    card = ComputeCard(card_context)
    qtbot.addWidget(card)  # type: ignore[attr-defined]
    zgloszenia: list[bool] = []
    card.applied.connect(zgloszenia.append)

    card.set_provider(True)
    card.remote_url_edit.setText("https://embeddingi.example.com/v1")
    position = card.remote_protocol_combo.findData("openai")
    assert position >= 0
    card.remote_protocol_combo.setCurrentIndex(position)
    card.remote_model_edit.setText("model-zdalny")
    card.remote_dimension_spin.setValue(1024)
    card.apply_settings()

    assert zgloszenia == [True]
    zapisana = load_config(card_context.paths.config_file)
    assert zapisana.embedding.provider == "internal_api"
    assert zapisana.embedding.internal_api_enabled is True
    assert zapisana.embedding.internal_api_url == "https://embeddingi.example.com/v1"
    assert zapisana.embedding.internal_api_protocol == "openai"
    assert zapisana.embedding.internal_api_model == "model-zdalny"
    assert zapisana.embedding.internal_api_dimension == 1024
    assert any(i18n.MODEL_REBUILD_REQUIRED in box.text() for box in message_boxes)


@pytest.mark.gui
def test_wylaczenie_zdalnego_api_wraca_do_modelu_lokalnego(
    qtbot: object, card_context: AppContext, message_boxes: list[QMessageBox]
) -> None:
    embedding = card_context.config.embedding
    embedding.provider = "internal_api"
    embedding.internal_api_enabled = True
    embedding.internal_api_url = "https://embeddingi.example.com/v1"

    card = ComputeCard(card_context)
    qtbot.addWidget(card)  # type: ignore[attr-defined]
    assert card.remote_selected()
    assert not card.remote_panel.isHidden()

    card.set_provider(False)
    card.apply_settings()

    zapisana = load_config(card_context.paths.config_file)
    assert zapisana.embedding.provider == "local_onnx"
    assert zapisana.embedding.internal_api_enabled is False


@pytest.mark.gui
def test_przedrostki_zdalnego_api_zapisuja_sie_i_wymagaja_przebudowy(
    qtbot: object, card_context: AppContext, message_boxes: list[QMessageBox]
) -> None:
    """Przy kontrakcie OpenAI przedrostki dokleja aplikacja, wiec sa czescia tozsamosci."""
    card = ComputeCard(card_context)
    qtbot.addWidget(card)  # type: ignore[attr-defined]

    card.set_provider(True)
    card.remote_url_edit.setText("https://embeddingi.example.com/v1")
    card.remote_query_prefix_edit.setText("query: ")
    card.remote_passage_prefix_edit.setText("passage: ")
    card.apply_settings()

    embedding = card_context.config.embedding
    assert embedding.query_prefix == "query: "
    assert embedding.passage_prefix == "passage: "
    assert any(i18n.MODEL_REBUILD_REQUIRED in box.text() for box in message_boxes)


@pytest.mark.gui
def test_zgoda_na_http_do_localhost_zapisuje_sie_i_wchodzi_do_polityki(
    qtbot: object, card_context: AppContext, message_boxes: list[QMessageBox]
) -> None:
    """Lokalny serwer modeli bez TLS wymaga jawnej zgody na karcie obliczeń."""
    from finddocs.security.network import EgressCategory, get_policy

    card = ComputeCard(card_context)
    qtbot.addWidget(card)  # type: ignore[attr-defined]
    assert not card.remote_allow_http_check.isChecked()

    card.set_provider(True)
    card.remote_url_edit.setText("http://127.0.0.1:11434/v1")
    card.remote_model_edit.setText("qwen3-embedding:8b")
    card.remote_dimension_spin.setValue(4096)
    card.remote_allow_http_check.setChecked(True)
    card.apply_settings()

    zapisana = load_config(card_context.paths.config_file)
    assert zapisana.allow_plain_http_localhost is True
    # Zapis karty przebudowuje polityke procesu, wiec adres jest juz dozwolony.
    host = get_policy().check("http://127.0.0.1:11434/v1/embeddings", EgressCategory.INTERNAL_API)
    assert host == "127.0.0.1"


@pytest.mark.gui
def test_cofniecie_zgody_na_http_zamyka_polityke(
    qtbot: object, card_context: AppContext, message_boxes: list[QMessageBox]
) -> None:
    from finddocs.errors import NetworkPolicyError
    from finddocs.security.network import EgressCategory, get_policy

    card_context.config.allow_plain_http_localhost = True
    card_context.config.embedding.internal_api_enabled = True
    card_context.config.embedding.internal_api_url = "http://127.0.0.1:11434/v1"

    card = ComputeCard(card_context)
    qtbot.addWidget(card)  # type: ignore[attr-defined]
    assert card.remote_allow_http_check.isChecked()

    card.remote_allow_http_check.setChecked(False)
    card.apply_settings()

    assert load_config(card_context.paths.config_file).allow_plain_http_localhost is False
    with pytest.raises(NetworkPolicyError):
        get_policy().check("http://127.0.0.1:11434/v1/embeddings", EgressCategory.INTERNAL_API)


# --- karta profili ----------------------------------------------------------------


@pytest.mark.gui
def test_karta_profili_tworzy_pierwszy_profil_z_ustawien(
    qtbot: object, card_context: AppContext
) -> None:
    """Stare konfiguracje bez profili dostaja profil zbudowany z biezacych ustawien."""
    card = ProfileCard(card_context)
    qtbot.addWidget(card)  # type: ignore[attr-defined]

    embedding = card_context.config.embedding
    assert len(embedding.profiles) == 1
    assert embedding.active_profile == embedding.profiles[0].name
    assert card.profile_combo.count() == 1
    # Zaznaczony jest profil aktywny, wiec aktywacja i usuwanie sa wylaczone.
    assert not card.activate_button.isEnabled()
    assert not card.remove_button.isEnabled()


@pytest.mark.gui
def test_zapis_biezacych_ustawien_jako_profil(
    qtbot: object, card_context: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QInputDialog

    monkeypatch.setattr(
        QInputDialog, "getText", staticmethod(lambda *args, **kwargs: ("Klaster GPU", True))
    )
    card = ProfileCard(card_context)
    qtbot.addWidget(card)  # type: ignore[attr-defined]

    card.save_current_as()

    embedding = card_context.config.embedding
    assert "Klaster GPU" in [p.name for p in embedding.profiles]
    assert embedding.active_profile == "Klaster GPU"
    zapisana = load_config(card_context.paths.config_file)
    assert "Klaster GPU" in [p.name for p in zapisana.embedding.profiles]


@pytest.mark.gui
def test_aktywacja_profilu_zdalnego_przelacza_dostawce(
    qtbot: object, card_context: AppContext, message_boxes: list[QMessageBox]
) -> None:
    embedding = card_context.config.embedding
    ensure_profiles(embedding)
    embedding.profiles.append(
        EmbeddingProfile(
            name="Klaster",
            provider="internal_api",
            internal_api_url="https://embeddingi.example.com/v1",
            internal_api_model="mmlw-duzy",
            internal_api_dimension=1024,
        )
    )
    card = ProfileCard(card_context)
    qtbot.addWidget(card)  # type: ignore[attr-defined]
    zgloszenia: list[bool] = []
    card.applied.connect(zgloszenia.append)

    position = card.profile_combo.findData("Klaster")
    assert position >= 0
    card.profile_combo.setCurrentIndex(position)
    card.activate_selected()

    assert zgloszenia == [True]
    assert embedding.provider == "internal_api"
    assert embedding.internal_api_enabled is True
    assert embedding.internal_api_dimension == 1024
    assert embedding.active_profile == "Klaster"
    zapisana = load_config(card_context.paths.config_file)
    assert zapisana.embedding.provider == "internal_api"
    assert zapisana.embedding.active_profile == "Klaster"
    assert any(i18n.MODEL_REBUILD_REQUIRED in box.text() for box in message_boxes)


@pytest.mark.gui
def test_aktywacja_profilu_lokalnego_wraca_ze_zdalnego_api(
    qtbot: object, card_context: AppContext
) -> None:
    embedding = card_context.config.embedding
    embedding.provider = "internal_api"
    embedding.internal_api_enabled = True
    embedding.internal_api_url = "https://embeddingi.example.com/v1"
    embedding.internal_api_model = "mmlw-duzy"
    ensure_profiles(embedding)
    embedding.profiles.append(
        EmbeddingProfile(
            name="Lokalny MMLW",
            provider="local_onnx",
            model_key="mmlw-retrieval-roberta-base",
        )
    )
    card = ProfileCard(card_context)
    qtbot.addWidget(card)  # type: ignore[attr-defined]

    position = card.profile_combo.findData("Lokalny MMLW")
    assert position >= 0
    card.profile_combo.setCurrentIndex(position)
    card.activate_selected()

    assert embedding.provider == "local_onnx"
    assert embedding.internal_api_enabled is False
    assert embedding.active_profile == "Lokalny MMLW"
    # Parametry modelu ida z wbudowanego rejestru, jak przy finddocs model use.
    assert embedding.query_prefix == "zapytanie: "


@pytest.mark.gui
def test_usuniecie_aktywnego_profilu_jest_blokowane(
    qtbot: object, card_context: AppContext, message_boxes: list[QMessageBox]
) -> None:
    card = ProfileCard(card_context)
    qtbot.addWidget(card)  # type: ignore[attr-defined]

    card.remove_selected()

    assert [box.text() for box in message_boxes] == [i18n.MODEL_PROFILE_REMOVE_ACTIVE]
    assert len(card_context.config.embedding.profiles) == 1


@pytest.mark.gui
def test_usuniecie_nieaktywnego_profilu(
    qtbot: object, card_context: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    import finddocs.gui.config_cards as config_cards_module

    monkeypatch.setattr(config_cards_module, "ask_yes_no", lambda *args, **kwargs: True)
    embedding = card_context.config.embedding
    ensure_profiles(embedding)
    embedding.profiles.append(EmbeddingProfile(name="Zbedny", provider="local_onnx"))
    card = ProfileCard(card_context)
    qtbot.addWidget(card)  # type: ignore[attr-defined]

    position = card.profile_combo.findData("Zbedny")
    assert position >= 0
    card.profile_combo.setCurrentIndex(position)
    card.remove_selected()

    assert "Zbedny" not in [p.name for p in embedding.profiles]
    zapisana = load_config(card_context.paths.config_file)
    assert "Zbedny" not in [p.name for p in zapisana.embedding.profiles]


# --- karta magazynu wektorow ---------------------------------------------------


@pytest.mark.gui
def test_panel_pgvector_jest_ukryty_dla_magazynu_faiss(
    qtbot: object, card_context: AppContext
) -> None:
    card = VectorStoreCard(card_context)
    qtbot.addWidget(card)  # type: ignore[attr-defined]

    assert card.selected_backend() == "faiss"
    assert card.pgvector_panel.isHidden()

    position = card.vector_backend_combo.findData("pgvector")
    card.vector_backend_combo.setCurrentIndex(position)

    assert not card.pgvector_panel.isHidden()


@pytest.mark.gui
def test_zapis_ustawien_magazynu_pgvector(
    qtbot: object, card_context: AppContext, message_boxes: list[QMessageBox]
) -> None:
    card = VectorStoreCard(card_context)
    qtbot.addWidget(card)  # type: ignore[attr-defined]
    zgloszenia: list[bool] = []
    card.applied.connect(zgloszenia.append)

    position = card.vector_backend_combo.findData("pgvector")
    assert position >= 0
    card.vector_backend_combo.setCurrentIndex(position)
    card.vector_host_edit.setText("baza.firma.local")
    card.vector_port_spin.setValue(5433)
    card.vector_database_edit.setText("wyszukiwarka")
    card.vector_user_edit.setText("finddocs")
    card.vector_table_edit.setText("wektory_zespolu")
    card.apply_settings()

    assert zgloszenia == [True]
    zapisana = load_config(card_context.paths.config_file)
    assert zapisana.vector_store.backend == "pgvector"
    assert zapisana.vector_store.pgvector_host == "baza.firma.local"
    assert zapisana.vector_store.pgvector_port == 5433
    assert zapisana.vector_store.pgvector_database == "wyszukiwarka"
    assert zapisana.vector_store.pgvector_user == "finddocs"
    assert zapisana.vector_store.pgvector_table == "wektory_zespolu"
    assert zapisana.vector_store.pgvector_sslmode == "require"
    assert any(i18n.MODEL_REBUILD_REQUIRED in box.text() for box in message_boxes)


@pytest.mark.gui
def test_wlaczenie_pgvector_bez_kompletu_danych_daje_ostrzezenie(
    qtbot: object, card_context: AppContext, message_boxes: list[QMessageBox]
) -> None:
    card = VectorStoreCard(card_context)
    qtbot.addWidget(card)  # type: ignore[attr-defined]
    zgloszenia: list[bool] = []
    card.applied.connect(zgloszenia.append)

    position = card.vector_backend_combo.findData("pgvector")
    assert position >= 0
    card.vector_backend_combo.setCurrentIndex(position)
    card.vector_host_edit.setText("baza.firma.local")
    card.apply_settings()

    assert zgloszenia == []
    assert [box.text() for box in message_boxes] == [i18n.MODEL_VECTOR_FIELDS_REQUIRED]
    assert card_context.config.vector_store.backend == "faiss"


@pytest.mark.gui
def test_powrot_do_faiss_nie_wymaga_danych_pgvector(
    qtbot: object, card_context: AppContext, message_boxes: list[QMessageBox]
) -> None:
    vector = card_context.config.vector_store
    vector.backend = "pgvector"
    vector.pgvector_host = "baza.firma.local"
    vector.pgvector_database = "wyszukiwarka"
    vector.pgvector_user = "finddocs"

    card = VectorStoreCard(card_context)
    qtbot.addWidget(card)  # type: ignore[attr-defined]
    assert card.selected_backend() == "pgvector"
    assert not card.pgvector_panel.isHidden()

    position = card.vector_backend_combo.findData("faiss")
    card.vector_backend_combo.setCurrentIndex(position)
    card.apply_settings()

    zapisana = load_config(card_context.paths.config_file)
    assert zapisana.vector_store.backend == "faiss"
    assert zapisana.vector_store.pgvector_host == "baza.firma.local"


# --- aktywacja i import ----------------------------------------------------------


@pytest.mark.gui
def test_aktywacja_modelu_synchronizuje_konfiguracje(
    qtbot: object, card_context: AppContext
) -> None:
    _install_fake_model(card_context)
    card = ModelCard(card_context)
    qtbot.addWidget(card)  # type: ignore[attr-defined]
    zgloszenia: list[bool] = []
    card.applied.connect(zgloszenia.append)

    card.activate_model(FAKE_KEY)

    embedding = card_context.config.embedding
    assert embedding.model_key == FAKE_KEY
    assert embedding.query_prefix == "query: "
    assert embedding.passage_prefix == "passage: "
    assert embedding.max_sequence_length == 128
    assert embedding.quantized is True
    assert zgloszenia == [True]
    assert card.selected_key() == FAKE_KEY
    assert card.query_edit.text() == "query: "


@pytest.mark.gui
def test_import_z_dysku_uruchamia_magazyn_i_zglasza_liste_modeli(
    qtbot: object,
    card_context: AppContext,
    monkeypatch: pytest.MonkeyPatch,
    drain_tasks: object,
) -> None:
    """Sciezka klikniecia: wybor katalogu, parametry, zadanie w tle, sygnal odswiezenia."""
    zrodlo = card_context.paths.root / "model-zrodlowy"
    zrodlo.mkdir(parents=True, exist_ok=True)
    wynik = ImportedModel(
        key="zaimportowany",
        directory=zrodlo,
        display_name="Zaimportowany",
        dimension=8,
        pooling="mean",
        quantized=True,
        query_prefix="",
        passage_prefix="",
        model_files=["model.int8.onnx"],
    )
    wywolania: list[tuple[Path, str]] = []

    def fake_import(source, options, *, paths=None, repo_id="", license_hint="", progress=None):
        wywolania.append((source, options.name))
        if progress is not None:
            progress("Kwantyzacja dynamiczna INT8")
        return wynik

    monkeypatch.setattr(model_store, "import_local_model", fake_import)
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", staticmethod(lambda *args, **kwargs: str(zrodlo))
    )
    monkeypatch.setattr(ModelImportDialog, "exec", lambda self: int(QDialog.DialogCode.Accepted))

    card = ModelCard(card_context)
    qtbot.addWidget(card)  # type: ignore[attr-defined]
    odswiezenia: list[None] = []
    card.models_changed.connect(lambda: odswiezenia.append(None))

    with qtbot.waitSignal(card.models_changed, timeout=15_000):  # type: ignore[attr-defined]
        card.import_from_disk()

    assert wywolania == [(zrodlo, "")]
    assert odswiezenia == [None]
    assert card.import_disk_button.isEnabled()
    assert card.apply_button.isEnabled()


# --- widok zrodel ----------------------------------------------------------------


@pytest.mark.gui
def test_widok_zrodel_sklada_karty_w_trzy_zakladki(qtbot: object, card_context: AppContext) -> None:
    """Konfiguracja jest podzielona tematycznie, a nie zebrana w jednym oknie."""
    view = SourcesView(card_context)
    qtbot.addWidget(view)  # type: ignore[attr-defined]

    labels = [view.tabs.tabText(i) for i in range(view.tabs.count())]
    assert labels == [
        i18n.SOURCES_TAB_SOURCES,
        i18n.SOURCES_TAB_SEMANTIC,
        i18n.SOURCES_TAB_STORAGE,
    ]
    assert view.tabs.currentIndex() == 0
    assert isinstance(view.semantic_card, SemanticCard)
    assert isinstance(view.profile_card, ProfileCard)
    assert isinstance(view.model_card, ModelCard)
    assert isinstance(view.compute_card, ComputeCard)
    assert isinstance(view.vector_card, VectorStoreCard)


@pytest.mark.gui
def test_karta_modelu_lokalnego_znika_przy_zdalnym_api(
    qtbot: object, card_context: AppContext
) -> None:
    """Model lokalny i zdalne API wykluczaja sie: widok pokazuje jeden z nich."""
    view = SourcesView(card_context)
    qtbot.addWidget(view)  # type: ignore[attr-defined]
    assert not view.model_card.isHidden()

    card_context.config.embedding.provider = "internal_api"
    view.refresh()
    assert view.model_card.isHidden()

    card_context.config.embedding.provider = "local_onnx"
    view.refresh()
    assert not view.model_card.isHidden()


@pytest.mark.gui
def test_zapis_karty_przekazuje_status_do_widoku(qtbot: object, card_context: AppContext) -> None:
    """Zapis bez przebudowy konczy sie komunikatem w pasku stanu, nie oknem."""
    view = SourcesView(card_context)
    qtbot.addWidget(view)  # type: ignore[attr-defined]
    komunikaty: list[str] = []
    view.status_message.connect(komunikaty.append)

    view.compute_card.apply_settings()

    assert i18n.SETTINGS_SAVED in komunikaty


@pytest.mark.gui
def test_pasek_stanu_odroznia_semantyke_wylaczona_od_braku_modelu(main_window) -> None:
    context = main_window.context

    main_window.refresh_index_status()
    assert "Tryb semantyczny niedostępny" in main_window.index_label.text()

    context.config.embedding.semantic_enabled = False
    main_window.refresh_index_status()
    assert "Tryb semantyczny wyłączony" in main_window.index_label.text()

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

from finddocs.config import load_config
from finddocs.gui import i18n
from finddocs.gui.config_cards import ComputeCard, ModelCard, SemanticCard, VectorStoreCard
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
    assert isinstance(view.model_card, ModelCard)
    assert isinstance(view.compute_card, ComputeCard)
    assert isinstance(view.vector_card, VectorStoreCard)


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

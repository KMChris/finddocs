"""Testy okna ustawien modelu: przedrostki, semantyka, import.

Import prawdziwych modeli sprawdza test integracyjny magazynu modeli. Tutaj
testujemy okablowanie okna: wypelnianie pol, zapis konfiguracji i manifestu
oraz sygnaly, ktorymi okno informuje widok zrodel o zmianach.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox

from finddocs.config import load_config
from finddocs.gui import i18n
from finddocs.gui.context import AppContext
from finddocs.gui.model_dialog import ModelImportDialog, ModelSettingsDialog
from finddocs.gui.sources_view import SourcesView
from finddocs.providers import model_store
from finddocs.providers.model_export import write_manifest
from finddocs.providers.model_manifest import LocalModelManifest
from finddocs.providers.model_store import ImportedModel

FAKE_KEY = "model-testowy-okna"


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
        display_name="Model testowy okna",
    )
    return directory


@pytest.fixture
def dialog_context(gui_context: AppContext) -> AppContext:
    """Kontekst bez dodatkowej sciezki modelu, zeby wyszukiwanie bylo standardowe."""
    gui_context.config.embedding.model_path = ""
    return gui_context


# --- wypelnianie pol -------------------------------------------------------------


@pytest.mark.gui
def test_prefiksy_znanego_modelu_pochodza_z_rejestru(
    qtbot: object, dialog_context: AppContext
) -> None:
    dialog = ModelSettingsDialog(dialog_context, model_key="multilingual-e5-small")
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]

    assert dialog.query_edit.text() == "query: "
    assert dialog.passage_edit.text() == "passage: "
    assert dialog.semantic_check.isChecked()


@pytest.mark.gui
def test_prefiksy_zainstalowanego_modelu_pochodza_z_manifestu(
    qtbot: object, dialog_context: AppContext
) -> None:
    _install_fake_model(dialog_context)
    dialog = ModelSettingsDialog(dialog_context, model_key=FAKE_KEY)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]

    assert dialog.query_edit.text() == "query: "
    assert dialog.passage_edit.text() == "passage: "


# --- zapis ustawien --------------------------------------------------------------


@pytest.mark.gui
def test_wylaczenie_semantyki_zapisuje_konfiguracje(
    qtbot: object, dialog_context: AppContext
) -> None:
    dialog = ModelSettingsDialog(dialog_context, model_key=FAKE_KEY)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    zgloszenia: list[bool] = []
    dialog.config_applied.connect(zgloszenia.append)

    dialog.semantic_check.setChecked(False)
    dialog.apply_settings()

    assert zgloszenia == [True]
    assert dialog.result() == int(QDialog.DialogCode.Accepted)
    assert dialog_context.config.embedding.semantic_enabled is False
    zapisana = load_config(dialog_context.paths.config_file)
    assert zapisana.embedding.semantic_enabled is False


@pytest.mark.gui
def test_zmiana_prefiksow_aktywnego_modelu_trafia_do_manifestu_i_konfiguracji(
    qtbot: object, dialog_context: AppContext, message_boxes: list[QMessageBox]
) -> None:
    directory = _install_fake_model(dialog_context)
    dialog_context.config.embedding.model_key = FAKE_KEY
    dialog = ModelSettingsDialog(dialog_context, model_key=FAKE_KEY)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    zgloszenia: list[bool] = []
    dialog.config_applied.connect(zgloszenia.append)

    dialog.query_edit.setText("pytanie: ")
    dialog.passage_edit.setText("")
    dialog.apply_settings()

    manifest = LocalModelManifest.load(directory)
    assert manifest.query_prefix == "pytanie: "
    assert manifest.passage_prefix == ""
    assert dialog_context.config.embedding.query_prefix == "pytanie: "
    assert dialog_context.config.embedding.passage_prefix == ""
    assert zgloszenia == [True]
    assert any(i18n.MODEL_REBUILD_REQUIRED in box.text() for box in message_boxes)


@pytest.mark.gui
def test_prefiksy_nieaktywnego_niezainstalowanego_modelu_daja_ostrzezenie(
    qtbot: object, dialog_context: AppContext, message_boxes: list[QMessageBox]
) -> None:
    dialog = ModelSettingsDialog(dialog_context, model_key="multilingual-e5-small")
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]

    dialog.query_edit.setText("inny: ")
    dialog.apply_settings()

    assert dialog.result() != int(QDialog.DialogCode.Accepted)
    assert [box.text() for box in message_boxes] == [i18n.MODEL_PREFIX_NOT_INSTALLED]


@pytest.mark.gui
def test_zmiana_urzadzenia_i_batcha_zapisuje_konfiguracje(
    qtbot: object, dialog_context: AppContext
) -> None:
    dialog = ModelSettingsDialog(dialog_context, model_key=FAKE_KEY)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    zgloszenia: list[bool] = []
    dialog.config_applied.connect(zgloszenia.append)

    position = dialog.device_combo.findData("dml")
    assert position >= 0
    dialog.device_combo.setCurrentIndex(position)
    dialog.batch_spin.setValue(64)
    dialog.batch_docs_spin.setValue(16)
    dialog.apply_settings()

    assert zgloszenia == [True]
    zapisana = load_config(dialog_context.paths.config_file)
    assert zapisana.embedding.device == "dml"
    assert zapisana.embedding.batch_size == 64
    assert zapisana.indexing.embed_batch_documents == 16


@pytest.mark.gui
def test_wlaczenie_zdalnego_api_bez_adresu_daje_ostrzezenie(
    qtbot: object, dialog_context: AppContext, message_boxes: list[QMessageBox]
) -> None:
    dialog = ModelSettingsDialog(dialog_context, model_key=FAKE_KEY)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]

    dialog.remote_enable_check.setChecked(True)
    dialog.apply_settings()

    assert dialog.result() != int(QDialog.DialogCode.Accepted)
    assert [box.text() for box in message_boxes] == [i18n.MODEL_REMOTE_URL_REQUIRED]
    assert dialog_context.config.embedding.provider == "local_onnx"


@pytest.mark.gui
def test_wlaczenie_zdalnego_api_przelacza_dostawce(
    qtbot: object, dialog_context: AppContext, message_boxes: list[QMessageBox]
) -> None:
    dialog = ModelSettingsDialog(dialog_context, model_key=FAKE_KEY)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    zgloszenia: list[bool] = []
    dialog.config_applied.connect(zgloszenia.append)

    dialog.remote_enable_check.setChecked(True)
    dialog.remote_url_edit.setText("https://embeddingi.example.com/v1")
    position = dialog.remote_protocol_combo.findData("openai")
    assert position >= 0
    dialog.remote_protocol_combo.setCurrentIndex(position)
    dialog.remote_model_edit.setText("model-zdalny")
    dialog.remote_dimension_spin.setValue(1024)
    dialog.apply_settings()

    assert zgloszenia == [True]
    zapisana = load_config(dialog_context.paths.config_file)
    assert zapisana.embedding.provider == "internal_api"
    assert zapisana.embedding.internal_api_enabled is True
    assert zapisana.embedding.internal_api_url == "https://embeddingi.example.com/v1"
    assert zapisana.embedding.internal_api_protocol == "openai"
    assert zapisana.embedding.internal_api_model == "model-zdalny"
    assert zapisana.embedding.internal_api_dimension == 1024
    assert any(i18n.MODEL_REBUILD_REQUIRED in box.text() for box in message_boxes)


@pytest.mark.gui
def test_wylaczenie_zdalnego_api_wraca_do_modelu_lokalnego(
    qtbot: object, dialog_context: AppContext, message_boxes: list[QMessageBox]
) -> None:
    embedding = dialog_context.config.embedding
    embedding.provider = "internal_api"
    embedding.internal_api_enabled = True
    embedding.internal_api_url = "https://embeddingi.example.com/v1"

    dialog = ModelSettingsDialog(dialog_context, model_key=FAKE_KEY)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    assert dialog.remote_enable_check.isChecked()

    dialog.remote_enable_check.setChecked(False)
    dialog.apply_settings()

    zapisana = load_config(dialog_context.paths.config_file)
    assert zapisana.embedding.provider == "local_onnx"
    assert zapisana.embedding.internal_api_enabled is False


# --- magazyn wektorow --------------------------------------------------------------


@pytest.mark.gui
def test_zapis_ustawien_magazynu_pgvector(
    qtbot: object, dialog_context: AppContext, message_boxes: list[QMessageBox]
) -> None:
    dialog = ModelSettingsDialog(dialog_context, model_key=FAKE_KEY)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    zgloszenia: list[bool] = []
    dialog.config_applied.connect(zgloszenia.append)

    position = dialog.vector_backend_combo.findData("pgvector")
    assert position >= 0
    dialog.vector_backend_combo.setCurrentIndex(position)
    dialog.vector_host_edit.setText("baza.firma.local")
    dialog.vector_port_spin.setValue(5433)
    dialog.vector_database_edit.setText("wyszukiwarka")
    dialog.vector_user_edit.setText("finddocs")
    dialog.vector_table_edit.setText("wektory_zespolu")
    dialog.apply_settings()

    assert zgloszenia == [True]
    zapisana = load_config(dialog_context.paths.config_file)
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
    qtbot: object, dialog_context: AppContext, message_boxes: list[QMessageBox]
) -> None:
    dialog = ModelSettingsDialog(dialog_context, model_key=FAKE_KEY)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]

    position = dialog.vector_backend_combo.findData("pgvector")
    assert position >= 0
    dialog.vector_backend_combo.setCurrentIndex(position)
    dialog.vector_host_edit.setText("baza.firma.local")
    dialog.apply_settings()

    assert dialog.result() != int(QDialog.DialogCode.Accepted)
    assert [box.text() for box in message_boxes] == [i18n.MODEL_VECTOR_FIELDS_REQUIRED]
    assert dialog_context.config.vector_store.backend == "faiss"


@pytest.mark.gui
def test_powrot_do_faiss_nie_wymaga_danych_pgvector(
    qtbot: object, dialog_context: AppContext, message_boxes: list[QMessageBox]
) -> None:
    vector = dialog_context.config.vector_store
    vector.backend = "pgvector"
    vector.pgvector_host = "baza.firma.local"
    vector.pgvector_database = "wyszukiwarka"
    vector.pgvector_user = "finddocs"

    dialog = ModelSettingsDialog(dialog_context, model_key=FAKE_KEY)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    assert dialog.vector_backend_combo.currentData() == "pgvector"

    position = dialog.vector_backend_combo.findData("faiss")
    dialog.vector_backend_combo.setCurrentIndex(position)
    dialog.apply_settings()

    zapisana = load_config(dialog_context.paths.config_file)
    assert zapisana.vector_store.backend == "faiss"
    assert zapisana.vector_store.pgvector_host == "baza.firma.local"


# --- aktywacja i import ----------------------------------------------------------


@pytest.mark.gui
def test_aktywacja_modelu_synchronizuje_konfiguracje(
    qtbot: object, dialog_context: AppContext
) -> None:
    _install_fake_model(dialog_context)
    dialog = ModelSettingsDialog(dialog_context, model_key=FAKE_KEY)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    zgloszenia: list[bool] = []
    dialog.config_applied.connect(zgloszenia.append)

    dialog.activate_model(FAKE_KEY)

    embedding = dialog_context.config.embedding
    assert embedding.model_key == FAKE_KEY
    assert embedding.query_prefix == "query: "
    assert embedding.passage_prefix == "passage: "
    assert embedding.max_sequence_length == 128
    assert embedding.quantized is True
    assert zgloszenia == [True]


@pytest.mark.gui
def test_import_z_dysku_uruchamia_magazyn_i_zglasza_liste_modeli(
    qtbot: object,
    dialog_context: AppContext,
    monkeypatch: pytest.MonkeyPatch,
    drain_tasks: object,
) -> None:
    """Sciezka klikniecia: wybor katalogu, parametry, zadanie w tle, sygnal odswiezenia."""
    zrodlo = dialog_context.paths.root / "model-zrodlowy"
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

    dialog = ModelSettingsDialog(dialog_context, model_key=FAKE_KEY)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    odswiezenia: list[None] = []
    dialog.models_changed.connect(lambda: odswiezenia.append(None))

    with qtbot.waitSignal(dialog.models_changed, timeout=15_000):  # type: ignore[attr-defined]
        dialog.import_from_disk()

    assert wywolania == [(zrodlo, "")]
    assert odswiezenia == [None]
    assert dialog.import_disk_button.isEnabled()


# --- widok zrodel ----------------------------------------------------------------


@pytest.mark.gui
def test_widok_zrodel_ma_przycisk_ustawien_modelu(
    qtbot: object, dialog_context: AppContext
) -> None:
    view = SourcesView(dialog_context)
    qtbot.addWidget(view)  # type: ignore[attr-defined]

    assert view.model_settings_button.text() == i18n.MODEL_SETTINGS_BUTTON


@pytest.mark.gui
def test_pasek_stanu_odroznia_semantyke_wylaczona_od_braku_modelu(main_window) -> None:
    context = main_window.context

    main_window.refresh_index_status()
    assert "Tryb semantyczny niedostępny" in main_window.index_label.text()

    context.config.embedding.semantic_enabled = False
    main_window.refresh_index_status()
    assert "Tryb semantyczny wyłączony" in main_window.index_label.text()


@pytest.mark.gui
def test_zastosowanie_modelu_synchronizuje_przedrostki(
    qtbot: object,
    dialog_context: AppContext,
    message_boxes: list[QMessageBox],
    drain_tasks: object,
) -> None:
    view = SourcesView(dialog_context)
    qtbot.addWidget(view)  # type: ignore[attr-defined]
    position = view.model_combo.findData("multilingual-e5-small")
    assert position >= 0
    view.model_combo.setCurrentIndex(position)

    view.apply_model()

    embedding = dialog_context.config.embedding
    assert embedding.model_key == "multilingual-e5-small"
    assert embedding.query_prefix == "query: "
    assert embedding.passage_prefix == "passage: "
    assert any(i18n.MODEL_REBUILD_REQUIRED in box.text() for box in message_boxes)

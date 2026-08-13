"""Testy konfiguracji aplikacji i skrotow zgodnosci indeksu.

Zmiana parametrow fragmentacji musi uniewaznic indeks pelnotekstowy, a zmiana
modelu tylko czesc wektorowa. Inaczej indeks stanie sie niespojny bez ostrzezenia.
"""

from __future__ import annotations

import json

import pytest

from finddocs.config import (
    CONFIG_FORMAT_VERSION,
    AppConfig,
    LocalDirSourceSettings,
    SharePointSourceSettings,
    SourceConfig,
    config_from_dict,
    config_to_dict,
    load_config,
    save_config,
)
from finddocs.errors import ConfigurationError
from finddocs.types import SourceKind


def zrodlo_lokalne() -> SourceConfig:
    return SourceConfig(
        source_id="lokalne",
        kind=SourceKind.LOCAL_DIR,
        label="Dysk lokalny",
        local=LocalDirSourceSettings(root_path="C:/dane/dokumenty"),
    )


def zrodlo_sharepoint() -> SourceConfig:
    return SourceConfig(
        source_id="sp",
        kind=SourceKind.SHAREPOINT,
        label="Finanse",
        sharepoint=SharePointSourceSettings(
            site_url="https://contoso.sharepoint.com/sites/Finanse",
            drive_name="Dokumenty",
            folder_path="/Raporty/2015/",
        ),
    )


# --- zapis i odczyt ------------------------------------------------------------


def test_zapis_i_odczyt_konfiguracji(tmp_home):
    config = AppConfig(data_root=str(tmp_home.root))
    config.sources.append(zrodlo_lokalne())
    config.ui.theme = "dark"
    config.ocr.languages = ["pol", "eng"]

    sciezka = save_config(config, tmp_home.config_file)
    odczytana = load_config(sciezka)

    assert odczytana.data_root == config.data_root
    assert odczytana.ui.theme == "dark"
    assert odczytana.ocr.languages == ["pol", "eng"]
    assert len(odczytana.sources) == 1
    assert odczytana.sources[0].kind is SourceKind.LOCAL_DIR
    assert odczytana.sources[0].local.root_path == "C:/dane/dokumenty"


def test_zgoda_na_http_do_localhost_przezywa_zapis_i_odczyt(tmp_home):
    config = AppConfig(data_root=str(tmp_home.root))
    assert config.allow_plain_http_localhost is False
    config.allow_plain_http_localhost = True

    odczytana = load_config(save_config(config, tmp_home.config_file))

    assert odczytana.allow_plain_http_localhost is True


def test_stara_konfiguracja_bez_zgody_na_http_dostaje_wylaczona():
    dane = config_to_dict(AppConfig())
    del dane["allow_plain_http_localhost"]

    assert config_from_dict(dane).allow_plain_http_localhost is False


def test_zgoda_na_http_nie_zmienia_skrotow_zgodnosci():
    """Zgoda dotyczy transportu, nie tresci wektorow: indeks zostaje wazny."""
    zmieniona = AppConfig()
    zmieniona.allow_plain_http_localhost = True

    assert zmieniona.index_compat_hash() == AppConfig().index_compat_hash()
    assert zmieniona.vector_compat_hash() == AppConfig().vector_compat_hash()


def test_zapis_jest_atomowy_i_nie_zostawia_pliku_tymczasowego(tmp_home):
    config = AppConfig(data_root=str(tmp_home.root))
    sciezka = save_config(config, tmp_home.config_file)

    pozostale = sorted(p.name for p in sciezka.parent.iterdir())
    assert pozostale == [sciezka.name]
    assert not any(p.suffix == ".tmp" for p in sciezka.parent.iterdir())


def test_zapis_podmienia_istniejacy_plik(tmp_home):
    config = AppConfig(data_root=str(tmp_home.root))
    save_config(config, tmp_home.config_file)
    config.ui.font_scale = 1.5
    sciezka = save_config(config, tmp_home.config_file)

    assert load_config(sciezka).ui.font_scale == 1.5
    assert len(list(sciezka.parent.iterdir())) == 1


def test_zapis_tworzy_brakujacy_katalog(tmp_path):
    cel = tmp_path / "nowy" / "glebiej" / "settings.json"
    save_config(AppConfig(), cel)
    assert cel.exists()


def test_load_config_gdy_pliku_nie_ma(tmp_path):
    config = load_config(tmp_path / "nie-ma.json")
    assert config.format_version == CONFIG_FORMAT_VERSION
    assert config.sources == []


def test_load_config_dla_uszkodzonego_pliku(tmp_path):
    plik = tmp_path / "settings.json"
    plik.write_text("{to nie jest json", encoding="utf-8")

    with pytest.raises(ConfigurationError):
        load_config(plik)


def test_load_config_dla_struktury_innej_niz_obiekt(tmp_path):
    plik = tmp_path / "settings.json"
    plik.write_text("[1, 2, 3]", encoding="utf-8")

    with pytest.raises(ConfigurationError):
        load_config(plik)


def test_plik_konfiguracyjny_nie_zawiera_poswiadczen(tmp_home):
    config = AppConfig(data_root=str(tmp_home.root))
    config.sources.append(zrodlo_sharepoint())
    sciezka = save_config(config, tmp_home.config_file)
    dane = json.loads(sciezka.read_text(encoding="utf-8"))

    tekst = json.dumps(dane).lower()
    assert "secret" not in tekst
    assert "access_token" not in tekst


def test_stary_limit_stron_ocr_jest_podnoszony_przy_wczytaniu():
    """Zapisane 60 stron to stara wartosc domyslna, nie wybor uzytkownika."""
    config = config_from_dict({"ocr": {"max_pages_per_document": 60}})
    assert config.ocr.max_pages_per_document == 1000


def test_wlasny_limit_stron_ocr_zostaje_po_wczytaniu():
    """Wartosc inna niz stara domyslna jest zachowywana bez zmian."""
    config = config_from_dict({"ocr": {"max_pages_per_document": 250}})
    assert config.ocr.max_pages_per_document == 250


# --- skroty zgodnosci ----------------------------------------------------------


def test_index_compat_hash_zmienia_sie_po_zmianie_fragmentacji():
    bazowa = AppConfig()
    for pole, wartosc in (
        ("target_chars", 900),
        ("overlap_chars", 42),
        ("min_chars", 60),
        ("max_chars", 3000),
        ("table_rows_per_chunk", 5),
        ("table_include_header", False),
    ):
        zmieniona = AppConfig()
        setattr(zmieniona.chunking, pole, wartosc)
        assert zmieniona.index_compat_hash() != bazowa.index_compat_hash(), pole


def test_index_compat_hash_jest_stabilny_dla_tej_samej_konfiguracji():
    assert AppConfig().index_compat_hash() == AppConfig().index_compat_hash()
    assert len(AppConfig().index_compat_hash()) == 32


def test_index_compat_hash_nie_zalezy_od_ustawien_nieistotnych():
    zmieniona = AppConfig()
    zmieniona.ui.theme = "dark"
    zmieniona.search.page_size = 50
    zmieniona.diagnostics.log_level = "DEBUG"

    assert zmieniona.index_compat_hash() == AppConfig().index_compat_hash()


def test_vector_compat_hash_zmienia_sie_po_zmianie_modelu():
    bazowa = AppConfig()
    zmieniona = AppConfig()
    zmieniona.embedding.model_key = "inny-model"

    assert zmieniona.vector_compat_hash() != bazowa.vector_compat_hash()
    # Model nie wplywa na indeks pelnotekstowy, wiec ten skrot zostaje bez zmian.
    assert zmieniona.index_compat_hash() == bazowa.index_compat_hash()


@pytest.mark.parametrize(
    ("pole", "wartosc"),
    [
        ("provider", "internal_api"),
        ("quantized", False),
        ("max_sequence_length", 256),
        ("query_prefix", ""),
        ("passage_prefix", "pasaz: "),
        ("normalize", False),
    ],
)
def test_vector_compat_hash_reaguje_na_parametry_modelu(pole, wartosc):
    bazowa = AppConfig()
    zmieniona = AppConfig()
    setattr(zmieniona.embedding, pole, wartosc)

    assert zmieniona.vector_compat_hash() != bazowa.vector_compat_hash()
    assert zmieniona.index_compat_hash() == bazowa.index_compat_hash()


def test_zmiana_fragmentacji_uniewaznia_takze_indeks_wektorowy():
    bazowa = AppConfig()
    zmieniona = AppConfig()
    zmieniona.chunking.target_chars = 900

    assert zmieniona.vector_compat_hash() != bazowa.vector_compat_hash()


def _konfiguracja_pgvector() -> AppConfig:
    config = AppConfig()
    config.vector_store.backend = "pgvector"
    config.vector_store.pgvector_host = "baza.firma.local"
    config.vector_store.pgvector_database = "wyszukiwarka"
    config.vector_store.pgvector_user = "finddocs"
    return config


def test_pola_pgvector_nie_zmieniaja_skrotu_przy_magazynie_faiss():
    """Sama obecnosc wpisanych danych polaczenia nie moze uniewaznic indeksu."""
    bazowa = AppConfig()
    zmieniona = AppConfig()
    zmieniona.vector_store.pgvector_host = "baza.firma.local"
    zmieniona.vector_store.pgvector_table = "inna_tabela"

    assert zmieniona.vector_compat_hash() == bazowa.vector_compat_hash()


def test_wlaczenie_pgvector_uniewaznia_indeks_wektorowy():
    bazowa = AppConfig()
    zmieniona = _konfiguracja_pgvector()

    assert zmieniona.vector_compat_hash() != bazowa.vector_compat_hash()
    assert zmieniona.index_compat_hash() == bazowa.index_compat_hash()


@pytest.mark.parametrize(
    ("pole", "wartosc"),
    [
        ("pgvector_host", "inny.serwer.local"),
        ("pgvector_port", 5433),
        ("pgvector_database", "inna_baza"),
        ("pgvector_schema", "inny_schemat"),
        ("pgvector_table", "inne_wektory"),
    ],
)
def test_tozsamosc_magazynu_pgvector_wchodzi_do_skrotu(pole, wartosc):
    bazowa = _konfiguracja_pgvector()
    zmieniona = _konfiguracja_pgvector()
    setattr(zmieniona.vector_store, pole, wartosc)

    assert zmieniona.vector_compat_hash() != bazowa.vector_compat_hash(), pole


@pytest.mark.parametrize(
    ("pole", "wartosc"),
    [
        ("pgvector_user", "inny_uzytkownik"),
        ("pgvector_sslmode", "verify-full"),
        ("pgvector_connect_timeout_seconds", 3.0),
        ("pgvector_statement_timeout_seconds", 15.0),
    ],
)
def test_parametry_polaczenia_pgvector_nie_wchodza_do_skrotu(pole, wartosc):
    """Zmiana danych logowania albo limitow czasu nie zmienia danych w tabeli."""
    bazowa = _konfiguracja_pgvector()
    zmieniona = _konfiguracja_pgvector()
    setattr(zmieniona.vector_store, pole, wartosc)

    assert zmieniona.vector_compat_hash() == bazowa.vector_compat_hash(), pole


def test_ustawienia_magazynu_wektorow_przezywaja_zapis_i_odczyt(tmp_home):
    config = _konfiguracja_pgvector()
    config.data_root = str(tmp_home.root)
    config.vector_store.pgvector_table = "wektory_zespolu"

    sciezka = save_config(config, tmp_home.config_file)
    odczytana = load_config(sciezka)

    assert odczytana.vector_store.backend == "pgvector"
    assert odczytana.vector_store.pgvector_host == "baza.firma.local"
    assert odczytana.vector_store.pgvector_table == "wektory_zespolu"
    assert odczytana.vector_store.pgvector_sslmode == "require"


def test_stara_konfiguracja_bez_sekcji_vector_store_dostaje_faiss():
    dane = config_to_dict(AppConfig())
    del dane["vector_store"]

    config = config_from_dict(dane)

    assert config.vector_store.backend == "faiss"


def test_plik_konfiguracyjny_pgvector_nie_zawiera_hasla(tmp_home):
    config = _konfiguracja_pgvector()
    config.data_root = str(tmp_home.root)
    sciezka = save_config(config, tmp_home.config_file)

    tekst = sciezka.read_text(encoding="utf-8").lower()
    assert "password" not in tekst
    assert "haslo" not in tekst


def test_wlaczenie_wzbogacenia_kontekstem_uniewaznia_indeks_wektorowy():
    """Naglowek z nazwa pliku zmienia teksty podawane modelowi, wiec i wektory."""
    bazowa = AppConfig()
    zmieniona = AppConfig()
    zmieniona.embedding.enrich_context = True

    assert zmieniona.vector_compat_hash() != bazowa.vector_compat_hash()
    assert zmieniona.index_compat_hash() == bazowa.index_compat_hash()


def test_wylaczone_wzbogacenie_kontekstem_nie_zmienia_skrotu():
    """Skrot konfiguracji sprzed wprowadzenia opcji musi zostac ten sam."""
    dane = config_to_dict(AppConfig())
    del dane["embedding"]["enrich_context"]

    stara = config_from_dict(dane)

    assert stara.embedding.enrich_context is False
    assert stara.vector_compat_hash() == AppConfig().vector_compat_hash()


def test_wzbogacenie_kontekstem_przezywa_zapis_i_odczyt(tmp_home):
    config = AppConfig(data_root=str(tmp_home.root))
    config.embedding.enrich_context = True

    sciezka = save_config(config, tmp_home.config_file)
    odczytana = load_config(sciezka)

    assert odczytana.embedding.enrich_context is True


def test_wylaczenie_semantyki_nie_uniewaznia_zadnego_indeksu():
    """Przelacznik semantyki nie moze wymuszac przebudowy po ponownym wlaczeniu.

    Brakujace wektory uzupelnia zwykle skanowanie, wiec skroty zgodnosci
    zostaja bez zmian.
    """
    bazowa = AppConfig()
    zmieniona = AppConfig()
    zmieniona.embedding.semantic_enabled = False

    assert zmieniona.index_compat_hash() == bazowa.index_compat_hash()
    assert zmieniona.vector_compat_hash() == bazowa.vector_compat_hash()


def test_stara_konfiguracja_bez_flagi_semantyki_ma_ja_wlaczona():
    dane = config_to_dict(AppConfig())
    del dane["embedding"]["semantic_enabled"]

    config = config_from_dict(dane)

    assert config.embedding.semantic_enabled is True


def test_flaga_semantyki_przezywa_zapis_i_odczyt(tmp_home):
    config = AppConfig(data_root=str(tmp_home.root))
    config.embedding.semantic_enabled = False

    sciezka = save_config(config, tmp_home.config_file)
    odczytana = load_config(sciezka)

    assert odczytana.embedding.semantic_enabled is False


# --- serializacja slownikowa ---------------------------------------------------


def test_config_from_dict_ignoruje_nieznane_klucze():
    dane = config_to_dict(AppConfig())
    dane["nieznany_klucz"] = "wartosc"
    dane["ui"]["nieznane_pole"] = 123

    config = config_from_dict(dane)

    assert config.ui.theme == "system"
    assert not hasattr(config, "nieznany_klucz")


def test_config_from_dict_uzupelnia_brakujace_klucze():
    config = config_from_dict({"data_root": "C:/dane"})

    assert config.data_root == "C:/dane"
    assert config.search.page_size == AppConfig().search.page_size
    assert config.ocr.enabled is True


def test_config_from_dict_odrzuca_nowszy_format():
    with pytest.raises(ConfigurationError) as blad:
        config_from_dict({"format_version": CONFIG_FORMAT_VERSION + 1})

    assert blad.value.code == "FD-1001"
    assert "nowszej wersji" in blad.value.user_message


def test_config_to_dict_zamienia_enum_na_napis():
    config = AppConfig()
    config.sources.append(zrodlo_lokalne())
    dane = config_to_dict(config)

    assert dane["sources"][0]["kind"] == "local_dir"
    json.dumps(dane)


def test_obieg_slownikowy_zachowuje_zrodla():
    config = AppConfig()
    config.sources.extend([zrodlo_lokalne(), zrodlo_sharepoint()])
    odtworzona = config_from_dict(config_to_dict(config))

    assert [s.source_id for s in odtworzona.sources] == ["lokalne", "sp"]
    assert odtworzona.source("sp").kind is SourceKind.SHAREPOINT
    assert odtworzona.source("sp").sharepoint.drive_name == "Dokumenty"


def test_source_zglasza_blad_dla_nieznanego_identyfikatora():
    with pytest.raises(ConfigurationError):
        AppConfig().source("nie-ma")


def test_with_source_podmienia_istniejace_zrodlo():
    config = AppConfig().with_source(zrodlo_lokalne())
    zmienione = SourceConfig(
        source_id="lokalne",
        kind=SourceKind.LOCAL_DIR,
        label="Inna nazwa",
        local=LocalDirSourceSettings(root_path="D:/inne"),
    )
    wynik = config.with_source(zmienione)

    assert len(wynik.sources) == 1
    assert wynik.source("lokalne").label == "Inna nazwa"


def test_enabled_sources_pomija_wylaczone():
    wylaczone = zrodlo_sharepoint()
    wylaczone.enabled = False
    config = AppConfig()
    config.sources.extend([zrodlo_lokalne(), wylaczone])

    assert [s.source_id for s in config.enabled_sources()] == ["lokalne"]


# --- opis lokalizacji zrodla ---------------------------------------------------


def test_describe_location_dla_katalogu_lokalnego():
    assert zrodlo_lokalne().describe_location() == "C:/dane/dokumenty"


def test_describe_location_dla_sharepoint():
    assert zrodlo_sharepoint().describe_location() == (
        "https://contoso.sharepoint.com/sites/Finanse / Dokumenty / Raporty/2015"
    )


def test_describe_location_gdy_brak_danych():
    lokalne = SourceConfig(source_id="a", kind=SourceKind.LOCAL_DIR, label="")
    sharepoint = SourceConfig(source_id="b", kind=SourceKind.SHAREPOINT, label="")

    assert lokalne.describe_location() == "(nie wskazano katalogu)"
    assert sharepoint.describe_location() == "(nie wskazano witryny)"


# --- katalogi danych -----------------------------------------------------------


def test_paths_bierze_katalog_z_konfiguracji(tmp_home, app_config):
    assert app_config.paths().root == tmp_home.root
    assert app_config.paths().config_file == tmp_home.config_file

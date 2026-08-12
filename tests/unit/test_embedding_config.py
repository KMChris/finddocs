"""Testy konfiguracji embeddingow: zgodnosc wektorow, round-trip, polityka sieciowa."""

from __future__ import annotations

import pytest

from finddocs.config import AppConfig, config_from_dict, config_to_dict
from finddocs.errors import NetworkPolicyError
from finddocs.security.network import EgressCategory, policy_from_config


def test_domyslny_skrot_nie_zawiera_pol_zdalnego_api() -> None:
    payload = AppConfig().vector_compat_payload()
    assert not any(key.startswith("internal_api") for key in payload)


def test_zmiana_urzadzenia_nie_zmienia_skrotu_wektorow() -> None:
    config = AppConfig()
    before = config.vector_compat_hash()
    config.embedding.device = "dml"
    config.embedding.batch_size = 64
    assert config.vector_compat_hash() == before


def test_przelaczenie_na_zdalne_api_zmienia_skrot_wektorow() -> None:
    config = AppConfig()
    before = config.vector_compat_hash()
    config.embedding.provider = "internal_api"
    after = config.vector_compat_hash()
    assert after != before
    payload = config.vector_compat_payload()
    assert payload["internal_api_protocol"] == "finddocs"
    assert payload["internal_api_dimension"] == 768


def test_zmiana_modelu_zdalnego_zmienia_skrot_wektorow() -> None:
    config = AppConfig()
    config.embedding.provider = "internal_api"
    before = config.vector_compat_hash()
    config.embedding.internal_api_model = "inny-model"
    assert config.vector_compat_hash() != before


def test_parametry_polaczenia_nie_wplywaja_na_skrot() -> None:
    """Adres, batch i limity czasu nie zmieniaja przestrzeni wektorow."""
    config = AppConfig()
    config.embedding.provider = "internal_api"
    before = config.vector_compat_hash()
    config.embedding.internal_api_url = "https://inny.example.com"
    config.embedding.internal_api_batch_size = 256
    config.embedding.internal_api_timeout_seconds = 90.0
    assert config.vector_compat_hash() == before


def test_round_trip_zachowuje_nowe_pola() -> None:
    config = AppConfig()
    config.embedding.device = "cuda"
    config.embedding.internal_api_enabled = True
    config.embedding.internal_api_url = "https://api.example.com/v1"
    config.embedding.internal_api_protocol = "openai"
    config.embedding.internal_api_model = "duzy-model"
    config.embedding.internal_api_dimension = 1024
    config.embedding.internal_api_key_header = "api-key"
    config.indexing.embed_batch_documents = 16
    config.indexing.embed_batch_chunks = 256

    loaded = config_from_dict(config_to_dict(config))

    assert loaded.embedding.device == "cuda"
    assert loaded.embedding.internal_api_url == "https://api.example.com/v1"
    assert loaded.embedding.internal_api_protocol == "openai"
    assert loaded.embedding.internal_api_model == "duzy-model"
    assert loaded.embedding.internal_api_dimension == 1024
    assert loaded.embedding.internal_api_key_header == "api-key"
    assert loaded.indexing.embed_batch_documents == 16
    assert loaded.indexing.embed_batch_chunks == 256


def test_stara_konfiguracja_bez_nowych_pol_dostaje_domyslne() -> None:
    data = config_to_dict(AppConfig())
    del data["embedding"]["device"]
    del data["embedding"]["internal_api_protocol"]
    del data["indexing"]["embed_batch_documents"]

    loaded = config_from_dict(data)

    assert loaded.embedding.device == "cpu"
    assert loaded.embedding.internal_api_protocol == "finddocs"
    assert loaded.indexing.embed_batch_documents == 8


# --- polityka sieciowa -----------------------------------------------------------


def test_polityka_domyslnie_offline() -> None:
    policy = policy_from_config(AppConfig())
    assert not policy.enabled_categories


def test_polityka_wlacza_zdalne_api_z_hostem_z_adresu() -> None:
    config = AppConfig()
    config.embedding.internal_api_enabled = True
    config.embedding.internal_api_url = "https://embeddingi.example.com/v1"

    policy = policy_from_config(config)

    assert policy.is_enabled(EgressCategory.INTERNAL_API)
    host = policy.check("https://embeddingi.example.com/v1/embeddings", EgressCategory.INTERNAL_API)
    assert host == "embeddingi.example.com"
    with pytest.raises(NetworkPolicyError):
        policy.check("https://inny.example.com/embeddings", EgressCategory.INTERNAL_API)


def test_polityka_bez_adresu_nie_wlacza_kategorii() -> None:
    config = AppConfig()
    config.embedding.internal_api_enabled = True
    config.embedding.internal_api_url = ""
    policy = policy_from_config(config)
    assert not policy.is_enabled(EgressCategory.INTERNAL_API)


def test_polityka_wymusza_https_dla_zdalnego_api() -> None:
    config = AppConfig()
    config.embedding.internal_api_enabled = True
    config.embedding.internal_api_url = "https://embeddingi.example.com"
    policy = policy_from_config(config)
    with pytest.raises(NetworkPolicyError):
        policy.check("http://embeddingi.example.com/embeddings", EgressCategory.INTERNAL_API)


def test_wylaczenie_api_wylacza_kategorie_w_nowej_polityce() -> None:
    config = AppConfig()
    config.embedding.internal_api_enabled = True
    config.embedding.internal_api_url = "https://a.example.com"
    first = policy_from_config(config)
    assert first.is_enabled(EgressCategory.INTERNAL_API)

    config.embedding.internal_api_enabled = False
    second = policy_from_config(config)
    assert not second.is_enabled(EgressCategory.INTERNAL_API)

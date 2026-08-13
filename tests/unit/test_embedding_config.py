"""Testy konfiguracji embeddingow: zgodnosc wektorow, round-trip, polityka sieciowa."""

from __future__ import annotations

import pytest

from finddocs.config import (
    AppConfig,
    EmbeddingProfile,
    EmbeddingSettings,
    apply_profile,
    config_from_dict,
    config_to_dict,
    ensure_profiles,
    save_profile,
    update_active_profile_marker,
)
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
    assert payload["internal_api_protocol"] == "openai"
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
    assert loaded.embedding.internal_api_protocol == "openai"
    assert loaded.indexing.embed_batch_documents == 8


# --- profile dostawcy ------------------------------------------------------------


def test_domyslny_kontrakt_zdalnego_api_to_openai() -> None:
    assert EmbeddingSettings().internal_api_protocol == "openai"
    assert EmbeddingProfile().internal_api_protocol == "openai"


def test_ensure_profiles_tworzy_pierwszy_profil_z_ustawien() -> None:
    embedding = EmbeddingSettings()
    assert ensure_profiles(embedding)
    assert len(embedding.profiles) == 1
    assert embedding.profiles[0].name == "mmlw-retrieval-roberta-base"
    assert embedding.active_profile == embedding.profiles[0].name
    assert not ensure_profiles(embedding)


def test_ensure_profiles_czysci_wskazanie_nieistniejacego_profilu() -> None:
    embedding = EmbeddingSettings()
    ensure_profiles(embedding)
    embedding.active_profile = "nie-ma-takiego"
    assert ensure_profiles(embedding)
    assert embedding.active_profile == ""


def test_apply_profile_przelacza_na_zdalne_api_i_wlacza_dostawce() -> None:
    embedding = EmbeddingSettings()
    remote = EmbeddingProfile(
        name="Klaster GPU",
        provider="internal_api",
        internal_api_url="https://embeddingi.example.com/v1",
        internal_api_model="mmlw-duzy",
        internal_api_dimension=1024,
    )
    apply_profile(embedding, remote)
    assert embedding.provider == "internal_api"
    assert embedding.internal_api_enabled is True
    assert embedding.active_profile == "Klaster GPU"
    assert embedding.internal_api_dimension == 1024


def test_apply_profile_lokalnego_wylacza_zdalne_api_i_zamyka_egress() -> None:
    config = AppConfig()
    embedding = config.embedding
    remote = EmbeddingProfile(
        name="api", provider="internal_api", internal_api_url="https://a.example.com"
    )
    local = EmbeddingProfile(name="lokalny", provider="local_onnx")
    apply_profile(embedding, remote)
    assert policy_from_config(config).is_enabled(EgressCategory.INTERNAL_API)
    apply_profile(embedding, local)
    assert embedding.provider == "local_onnx"
    assert embedding.internal_api_enabled is False
    assert not policy_from_config(config).is_enabled(EgressCategory.INTERNAL_API)


def test_zmiana_ustawien_odlacza_wskazanie_profilu_bez_nadpisania() -> None:
    """Zapis ustawien nie niszczy migawki: znika tylko wskazanie aktywnego."""
    embedding = EmbeddingSettings()
    ensure_profiles(embedding)
    embedding.device = "cuda"
    update_active_profile_marker(embedding)
    assert embedding.active_profile == ""
    assert embedding.profiles[0].device == "cpu"


def test_zgodne_ustawienia_zachowuja_wskazanie_profilu() -> None:
    embedding = EmbeddingSettings()
    ensure_profiles(embedding)
    update_active_profile_marker(embedding)
    assert embedding.active_profile == embedding.profiles[0].name


def test_save_profile_nadpisuje_w_miejscu_i_aktywuje() -> None:
    embedding = EmbeddingSettings()
    ensure_profiles(embedding)
    name = embedding.profiles[0].name
    embedding.profiles.append(EmbeddingProfile(name="drugi"))
    embedding.device = "cuda"

    save_profile(embedding, name)

    assert [p.name for p in embedding.profiles] == [name, "drugi"]
    assert embedding.profiles[0].device == "cuda"
    assert embedding.active_profile == name


def test_lista_profili_nie_wplywa_na_skrot_wektorow() -> None:
    config = AppConfig()
    before = config.vector_compat_hash()
    ensure_profiles(config.embedding)
    config.embedding.profiles.append(EmbeddingProfile(name="inny", provider="internal_api"))
    assert config.vector_compat_hash() == before


def test_round_trip_zachowuje_profile() -> None:
    config = AppConfig()
    ensure_profiles(config.embedding)
    config.embedding.profiles.append(
        EmbeddingProfile(
            name="Klaster",
            provider="internal_api",
            internal_api_url="https://a.example.com/v1",
            internal_api_dimension=1024,
        )
    )

    loaded = config_from_dict(config_to_dict(config))

    assert [p.name for p in loaded.embedding.profiles] == [
        p.name for p in config.embedding.profiles
    ]
    assert isinstance(loaded.embedding.profiles[0], EmbeddingProfile)
    assert loaded.embedding.profiles[1].internal_api_dimension == 1024
    assert loaded.embedding.active_profile == config.embedding.active_profile


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


def test_polityka_domyslnie_odrzuca_http_do_localhost() -> None:
    config = AppConfig()
    config.embedding.internal_api_enabled = True
    config.embedding.internal_api_url = "http://127.0.0.1:11434/v1"

    policy = policy_from_config(config)

    assert not policy.allow_plain_http_localhost
    with pytest.raises(NetworkPolicyError):
        policy.check("http://127.0.0.1:11434/v1/embeddings", EgressCategory.INTERNAL_API)


def test_zgoda_dopuszcza_http_do_localhost() -> None:
    config = AppConfig()
    config.allow_plain_http_localhost = True
    config.embedding.internal_api_enabled = True
    config.embedding.internal_api_url = "http://127.0.0.1:11434/v1"

    policy = policy_from_config(config)

    assert policy.check("http://127.0.0.1:11434/v1/embeddings", EgressCategory.INTERNAL_API) == (
        "127.0.0.1"
    )
    assert policy.check("http://localhost:11434/v1/embeddings", EgressCategory.INTERNAL_API) == (
        "localhost"
    )


def test_zgoda_na_localhost_nie_dotyczy_serwerow_zdalnych() -> None:
    """Zgoda na http obejmuje wylacznie ten komputer, nigdy hostow zdalnych."""
    config = AppConfig()
    config.allow_plain_http_localhost = True
    config.embedding.internal_api_enabled = True
    config.embedding.internal_api_url = "http://embeddingi.example.com/v1"

    policy = policy_from_config(config)

    with pytest.raises(NetworkPolicyError):
        policy.check("http://embeddingi.example.com/v1/embeddings", EgressCategory.INTERNAL_API)


def test_wylaczenie_api_wylacza_kategorie_w_nowej_polityce() -> None:
    config = AppConfig()
    config.embedding.internal_api_enabled = True
    config.embedding.internal_api_url = "https://a.example.com"
    first = policy_from_config(config)
    assert first.is_enabled(EgressCategory.INTERNAL_API)

    config.embedding.internal_api_enabled = False
    second = policy_from_config(config)
    assert not second.is_enabled(EgressCategory.INTERNAL_API)

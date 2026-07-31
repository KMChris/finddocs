"""Testy warstwy bezpieczenstwa: redakcja logow, polityka sieciowa, magazyn sekretow.

Do logow trafiaja fakty o przetwarzaniu, nigdy tresc dokumentu ani token. Ruch
wychodzacy jest domyslnie zablokowany i wymaga jawnego wlaczenia kategorii.
"""

from __future__ import annotations

import pytest

from finddocs.errors import NetworkPolicyError
from finddocs.security.credentials import MemoryCredentialStore
from finddocs.security.network import (
    EgressCategory,
    NetworkPolicy,
)
from finddocs.security.redaction import (
    REDACTED,
    redact_headers,
    redact_mapping,
    redact_text,
    safe_url,
)

TOKEN_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N"


# --- redakcja slownikow --------------------------------------------------------


def test_redact_mapping_usuwa_tokeny_i_hasla():
    wynik = redact_mapping(
        {
            "access_token": "abc123",
            "refresh_token": "def456",
            "password": "tajne",
            "client_secret": "sekret",
            "api_key": "klucz",
        }
    )
    assert set(wynik.values()) == {REDACTED}


def test_redact_mapping_usuwa_naglowek_autoryzacji():
    wynik = redact_mapping({"Authorization": f"Bearer {TOKEN_JWT}", "X-Request-Id": "42"})

    assert wynik["Authorization"] == REDACTED
    assert wynik["X-Request-Id"] == "42"


def test_redact_mapping_zamienia_tresc_na_dlugosc():
    wynik = redact_mapping({"text": "tresc dokumentu", "snippet": "fragment"})

    assert wynik["text"] == "<15 znaków>"
    assert wynik["snippet"] == "<8 znaków>"


def test_redact_mapping_zostawia_pola_diagnostyczne():
    wynik = redact_mapping({"doc_id": 12, "etap": "ekstrakcja", "czas_ms": 3.5, "ok": True})

    assert wynik == {"doc_id": 12, "etap": "ekstrakcja", "czas_ms": 3.5, "ok": True}


def test_redact_mapping_dziala_rekurencyjnie():
    wynik = redact_mapping({"naglowki": {"authorization": "Bearer abc", "x-id": "7"}})

    assert wynik["naglowki"]["authorization"] == REDACTED
    assert wynik["naglowki"]["x-id"] == "7"


def test_redact_headers():
    wynik = redact_headers({"Authorization": "Bearer abc", "X-Request-Id": "42"})

    assert wynik["Authorization"] == REDACTED
    assert wynik["X-Request-Id"] == "42"


# --- redakcja tekstu -----------------------------------------------------------


def test_redact_text_maskuje_bearer():
    wynik = redact_text("Authorization: Bearer abcdefghij1234567890")

    assert "abcdefghij1234567890" not in wynik
    assert wynik == f"Authorization: Bearer {REDACTED}"


def test_redact_text_maskuje_jwt():
    wynik = redact_text(f"odpowiedz zawiera {TOKEN_JWT} i nic wiecej")

    assert TOKEN_JWT not in wynik
    assert REDACTED in wynik


def test_redact_text_maskuje_dlugie_ciagi_szesnastkowe():
    skrot = "a1b2c3d4" * 6
    wynik = redact_text(f"skrot pliku {skrot} zapisany")

    assert skrot not in wynik
    assert REDACTED in wynik


def test_redact_text_maskuje_pary_klucz_wartosc():
    wynik = redact_text("client_secret=tajnahaslo123 oraz token: abcd1234")

    assert "tajnahaslo123" not in wynik
    assert "abcd1234" not in wynik


def test_redact_text_przycina_bardzo_dlugie_wartosci():
    wynik = redact_text("x" * 300)

    assert len(wynik) < 300
    assert wynik.endswith("znaków]")


def test_redact_text_nie_rusza_zwyklego_komunikatu():
    komunikat = "Zaindeksowano 12 dokumentow w 3 sekundy."
    assert redact_text(komunikat) == komunikat


# --- adresy URL ----------------------------------------------------------------


def test_safe_url_usuwa_parametry_zapytania():
    adres = "https://graph.microsoft.com/v1.0/drives/x/items/y/content?tempauth=SEKRET&a=1"
    wynik = safe_url(adres)

    assert "SEKRET" not in wynik
    assert wynik == "https://graph.microsoft.com/v1.0/drives/x/items/y/content?[parametry usunięte]"


def test_safe_url_usuwa_fragment_i_zostawia_adres_bez_parametrow():
    assert safe_url("https://graph.microsoft.com/v1.0/me#sekcja") == (
        "https://graph.microsoft.com/v1.0/me"
    )


# --- polityka sieciowa ---------------------------------------------------------


def test_domyslnie_wszystko_zablokowane():
    polityka = NetworkPolicy.offline()

    assert polityka.enabled_categories == set()
    for kategoria in EgressCategory:
        with pytest.raises(NetworkPolicyError):
            polityka.check("https://graph.microsoft.com/v1.0/me", kategoria)


def test_wlaczenie_kategorii_dopuszcza_host_z_listy():
    polityka = NetworkPolicy.offline()
    polityka.enable(EgressCategory.MICROSOFT_GRAPH)

    assert polityka.is_enabled(EgressCategory.MICROSOFT_GRAPH) is True
    graph = polityka.check("https://graph.microsoft.com/v1.0/me", EgressCategory.MICROSOFT_GRAPH)
    witryna = polityka.check(
        "https://contoso.sharepoint.com/sites/Finanse", EgressCategory.MICROSOFT_GRAPH
    )
    assert graph == "graph.microsoft.com"
    assert witryna == "contoso.sharepoint.com"


def test_wylaczenie_kategorii_ponownie_blokuje():
    polityka = NetworkPolicy.offline()
    polityka.enable(EgressCategory.MICROSOFT_GRAPH)
    polityka.disable(EgressCategory.MICROSOFT_GRAPH)

    with pytest.raises(NetworkPolicyError):
        polityka.check("https://graph.microsoft.com/v1.0/me", EgressCategory.MICROSOFT_GRAPH)


def test_odrzucenie_http():
    polityka = NetworkPolicy.offline()
    polityka.enable(EgressCategory.MICROSOFT_GRAPH)

    with pytest.raises(NetworkPolicyError) as blad:
        polityka.check("http://graph.microsoft.com/v1.0/me", EgressCategory.MICROSOFT_GRAPH)

    assert "https" in blad.value.user_message


def test_odrzucenie_hosta_spoza_listy():
    polityka = NetworkPolicy.offline()
    polityka.enable(EgressCategory.MICROSOFT_GRAPH)

    with pytest.raises(NetworkPolicyError) as blad:
        polityka.check("https://zly-host.example.com/dane", EgressCategory.MICROSOFT_GRAPH)

    assert "zly-host.example.com" in blad.value.user_message


def test_odrzucenie_adresu_bez_hosta():
    with pytest.raises(NetworkPolicyError):
        NetworkPolicy.offline().check("https://", EgressCategory.MICROSOFT_GRAPH)


def test_komunikaty_bledow_sa_po_polsku():
    polityka = NetworkPolicy.offline()

    with pytest.raises(NetworkPolicyError) as wylaczona:
        polityka.check("https://graph.microsoft.com/v1.0/me", EgressCategory.MICROSOFT_GRAPH)
    assert "jest wylaczona" in wylaczona.value.user_message
    assert wylaczona.value.code == "FD-1005"

    polityka.enable(EgressCategory.MICROSOFT_GRAPH)
    with pytest.raises(NetworkPolicyError) as zly_schemat:
        polityka.check("http://graph.microsoft.com/v1.0/me", EgressCategory.MICROSOFT_GRAPH)
    assert "Dozwolone jest wyłącznie połączenie https" in zly_schemat.value.user_message

    with pytest.raises(NetworkPolicyError) as zly_host:
        polityka.check("https://example.com/x", EgressCategory.MICROSOFT_GRAPH)
    assert "nie znajduje sie na liscie dozwolonych adresow" in zly_host.value.user_message


def test_dodatkowe_hosty_z_konfiguracji():
    polityka = NetworkPolicy(
        enabled_categories={EgressCategory.INTERNAL_API},
        extra_hosts={EgressCategory.INTERNAL_API: ("api.wewnetrzne.local",)},
    )
    assert polityka.check("https://api.wewnetrzne.local/embed", EgressCategory.INTERNAL_API) == (
        "api.wewnetrzne.local"
    )


def test_localhost_po_http_wymaga_jawnej_zgody():
    polityka = NetworkPolicy.offline()

    with pytest.raises(NetworkPolicyError):
        polityka.check("http://localhost:8080/x", EgressCategory.INTERNAL_API)

    polityka.allow_plain_http_localhost = True
    assert polityka.check("http://localhost:8080/x", EgressCategory.INTERNAL_API) == "localhost"


def test_describe_wymienia_kategorie_wlaczone_i_wylaczone():
    polityka = NetworkPolicy.offline()
    polityka.enable(EgressCategory.MODEL_DOWNLOAD)
    opis = polityka.describe()

    assert opis["kategorie_wlaczone"] == ["model_download"]
    assert "microsoft_graph" in opis["kategorie_wylaczone"]
    assert "huggingface.co" in opis["dozwolone_hosty"]["model_download"]


# --- magazyn poswiadczen w pamieci ---------------------------------------------


def test_memory_store_set_get_delete():
    magazyn = MemoryCredentialStore()
    magazyn.set_secret("klucz", "wartosc")

    assert magazyn.get_secret("klucz") == "wartosc"
    assert magazyn.get_secret("brak") is None

    magazyn.delete_secret("klucz")
    assert magazyn.get_secret("klucz") is None
    # Usuniecie nieistniejacego wpisu nie moze rzucac wyjatku.
    magazyn.delete_secret("klucz")


def test_memory_store_set_json_i_get_json():
    magazyn = MemoryCredentialStore()
    magazyn.set_json("cache", {"konto": "jan", "znaki": "łódka"})

    assert magazyn.get_json("cache") == {"konto": "jan", "znaki": "łódka"}
    assert magazyn.get_json("brak") is None


def test_memory_store_get_json_dla_uszkodzonego_wpisu():
    magazyn = MemoryCredentialStore()
    magazyn.set_secret("cache", "{to nie jest json")

    assert magazyn.get_json("cache") is None


def test_memory_store_nie_jest_trwaly():
    assert MemoryCredentialStore().persistent is False
    assert MemoryCredentialStore().name == "memory"

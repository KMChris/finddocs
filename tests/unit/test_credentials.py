"""Testy magazynu poswiadczen.

Aplikacja nie zapisuje sekretow jawnym tekstem na dysku. Kolejnosc preferencji to
menedzer poswiadczen Windows, DPAPI, a na koncu pamiec procesu. Ostatni wariant
istnieje po to, zeby aplikacja dzialala bez magazynu systemowego, i musi jasno
mowic, ze nie jest trwaly.

Testy DPAPI sa pomijane poza Windows albo gdy brakuje biblioteki ``pywin32``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from finddocs.errors import CredentialStoreError
from finddocs.security import credentials as store_module
from finddocs.security.credentials import (
    SERVICE_NAME,
    CredentialStore,
    DpapiCredentialStore,
    KeyringCredentialStore,
    MemoryCredentialStore,
    create_credential_store,
    token_cache_key,
)

#: Wartosc udajaca token. Nie jest zadnym prawdziwym sekretem.
SECRET = "wartosc-testowa-1234567890"


def _dpapi_available() -> bool:
    try:
        import win32crypt  # noqa: F401
    except ImportError:
        return False
    return True


dpapi_only = pytest.mark.skipif(not _dpapi_available(), reason="Brak biblioteki pywin32.")


# --- umowa wspolna dla wszystkich magazynow -------------------------------------


def _roundtrip(store: CredentialStore) -> None:
    assert store.get_secret("brak") is None

    store.set_secret("klucz", SECRET)
    assert store.get_secret("klucz") == SECRET

    store.set_secret("klucz", "inna-wartosc")
    assert store.get_secret("klucz") == "inna-wartosc"

    store.delete_secret("klucz")
    assert store.get_secret("klucz") is None

    store.delete_secret("klucz")


def test_magazyn_w_pamieci_spelnia_umowe() -> None:
    """Zapis, odczyt, nadpisanie i usuniecie dzialaja tak samo w kazdym magazynie."""
    _roundtrip(MemoryCredentialStore())


@dpapi_only
def test_magazyn_dpapi_spelnia_umowe(tmp_path: Path) -> None:
    _roundtrip(DpapiCredentialStore(tmp_path / "credentials.dat"))


def test_zapis_i_odczyt_struktury_json() -> None:
    """Pamiec podreczna tokenow MSAL jest slownikiem, wiec magazyn musi go obsluzyc."""
    store = MemoryCredentialStore()
    payload: dict[str, Any] = {"access_token": SECRET, "expires_in": 3600}

    store.set_json("cache", payload)

    assert store.get_json("cache") == payload
    assert store.get_json("brak") is None


def test_uszkodzony_wpis_json_nie_wywraca_aplikacji() -> None:
    """Niepoprawny JSON w magazynie daje None, a nie wyjatek."""
    store = MemoryCredentialStore()
    store.set_secret("cache", "{to nie jest json")

    assert store.get_json("cache") is None


def test_wpis_json_o_zlym_typie_jest_odrzucany() -> None:
    """Lista zamiast slownika to tez uszkodzony wpis."""
    store = MemoryCredentialStore()
    store.set_secret("cache", json.dumps([1, 2, 3]))

    assert store.get_json("cache") is None


def test_magazyn_w_pamieci_nie_jest_trwaly() -> None:
    """Flaga trwalosci pozwala aplikacji ostrzec uzytkownika."""
    assert MemoryCredentialStore().persistent is False
    assert MemoryCredentialStore().name == "memory"


# --- DPAPI ----------------------------------------------------------------------


@dpapi_only
def test_dpapi_nie_zapisuje_sekretu_jawnym_tekstem(tmp_path: Path) -> None:
    """Plik na dysku nie moze zawierac sekretu w postaci czytelnej."""
    target = tmp_path / "credentials.dat"
    store = DpapiCredentialStore(target)

    store.set_secret("token", SECRET)

    surowe = target.read_bytes()
    assert SECRET.encode("utf-8") not in surowe
    assert SECRET not in surowe.decode("utf-8", errors="ignore")


@dpapi_only
def test_dpapi_przezywa_ponowne_otwarcie(tmp_path: Path) -> None:
    """Sekret zapisany przez jedna instancje jest widoczny dla kolejnej."""
    target = tmp_path / "credentials.dat"
    DpapiCredentialStore(target).set_secret("token", SECRET)

    assert DpapiCredentialStore(target).get_secret("token") == SECRET


@dpapi_only
def test_dpapi_uszkodzony_plik_nie_wywraca_odczytu(tmp_path: Path) -> None:
    """Plik z niepoprawna trescia jest traktowany jak pusty magazyn."""
    target = tmp_path / "credentials.dat"
    target.write_text("to nie jest json", encoding="utf-8")

    assert DpapiCredentialStore(target).get_secret("token") is None


@dpapi_only
def test_dpapi_uszkodzona_wartosc_daje_none(tmp_path: Path) -> None:
    """Wartosc, ktorej nie da sie odszyfrowac, nie przerywa pracy aplikacji."""
    target = tmp_path / "credentials.dat"
    target.write_text(json.dumps({"token": "bez-sensu"}), encoding="utf-8")

    assert DpapiCredentialStore(target).get_secret("token") is None


@dpapi_only
def test_dpapi_tworzy_katalog_docelowy(tmp_path: Path) -> None:
    """Magazyn dziala takze wtedy, gdy katalogu jeszcze nie ma."""
    target = tmp_path / "nowy" / "katalog" / "credentials.dat"

    DpapiCredentialStore(target).set_secret("token", SECRET)

    assert target.exists()


# --- wybor magazynu --------------------------------------------------------------


def test_wybor_konczy_sie_na_pamieci_gdy_nic_nie_dziala(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Brak magazynu systemowego nie blokuje aplikacji, tylko odbiera trwalosc."""

    def zepsuty(*_args: object, **_kwargs: object) -> None:
        raise CredentialStoreError("Magazyn niedostepny w tescie.")

    monkeypatch.setattr(store_module, "KeyringCredentialStore", zepsuty)
    monkeypatch.setattr(store_module, "DpapiCredentialStore", zepsuty)

    store = create_credential_store(tmp_path)

    assert isinstance(store, MemoryCredentialStore)
    assert store.persistent is False


def test_wybor_preferuje_menedzer_poswiadczen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gdy keyring dziala, wygrywa on, bo jest magazynem systemu."""

    class Sztuczny(MemoryCredentialStore):
        name = "windows_credential_manager"
        persistent = True

    monkeypatch.setattr(store_module, "KeyringCredentialStore", Sztuczny)

    store = create_credential_store(tmp_path)

    assert store.name == "windows_credential_manager"
    assert store.persistent is True


def test_wymuszenie_pamieci(tmp_path: Path) -> None:
    """Jawny wybor magazynu jest respektowany."""
    store = create_credential_store(tmp_path, prefer="memory")

    assert isinstance(store, MemoryCredentialStore)


def test_wymuszenie_nieznanego_magazynu_schodzi_do_pamieci(tmp_path: Path) -> None:
    """Nieznana nazwa nie jest bledem krytycznym, kolejnym wyborem jest pamiec."""
    store = create_credential_store(tmp_path, prefer="cos-czego-nie-ma")

    assert isinstance(store, MemoryCredentialStore)


def test_wybrany_magazyn_dziala(tmp_path: Path) -> None:
    """Cokolwiek zostanie wybrane na tej maszynie, musi spelniac umowe."""
    store = create_credential_store(tmp_path, prefer="memory")

    _roundtrip(store)


# --- klucze ----------------------------------------------------------------------


def test_klucz_pamieci_tokenow_zawiera_zrodlo() -> None:
    """Dwa zrodla SharePoint nie moga sobie nadpisywac tokenow."""
    pierwszy = token_cache_key("finanse")
    drugi = token_cache_key("kadry")

    assert pierwszy != drugi
    assert "finanse" in pierwszy
    assert pierwszy.startswith("msal-token-cache::")


def test_nazwa_uslugi_jest_stala() -> None:
    """Nazwa uslugi trafia do menedzera poswiadczen Windows i nie moze sie zmieniac."""
    assert SERVICE_NAME == "FindDocs"


def test_keyring_odrzuca_zapasowy_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Backend o nazwie zawierajacej 'fail' nie jest prawdziwym magazynem."""
    keyring = pytest.importorskip("keyring")

    class FailBackend:
        pass

    FailBackend.__name__ = "FailKeyring"
    monkeypatch.setattr(keyring, "get_keyring", lambda: FailBackend())

    with pytest.raises(CredentialStoreError):
        KeyringCredentialStore()

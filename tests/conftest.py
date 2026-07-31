"""Wspolne fixture testow FindDocs.

Wszystkie testy pracuja na wlasnym katalogu danych. Zmienna FINDDOCS_HOME jest
ustawiana na katalog tymczasowy pytest, wiec zaden test nie dotyka prawdziwego
%LOCALAPPDATA%\\FindDocs uzytkownika.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from finddocs.app_paths import ENV_HOME, AppPaths
from finddocs.config import AppConfig
from finddocs.indexing.service import IndexService
from finddocs.providers.model_manifest import find_model_dir


@pytest.fixture(autouse=True)
def _interactive_dialogs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kasuje FINDDOCS_NO_DIALOG, zeby wynik testu nie zalezal od srodowiska.

    Zmienna wylacza okna modalne w tescie dymnym zbudowanej aplikacji. Gdyby
    zostala ustawiona w powloce, testy interfejsu przestalyby widziec komunikaty.
    Test sprawdzajacy samo wyciszenie ustawia ja sobie sam.
    """
    monkeypatch.delenv("FINDDOCS_NO_DIALOG", raising=False)


@pytest.fixture
def tmp_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AppPaths:
    """Katalog danych aplikacji przeniesiony do tmp_path. Zwraca gotowe AppPaths."""
    monkeypatch.setenv(ENV_HOME, str(tmp_path))
    return AppPaths.at(tmp_path).ensure()


@pytest.fixture
def app_config(tmp_home: AppPaths) -> AppConfig:
    """Konfiguracja domyslna wskazujaca na katalog danych z fixture tmp_home."""
    return AppConfig(data_root=str(tmp_home.root))


@pytest.fixture
def index_service(app_config: AppConfig) -> Iterator[IndexService]:
    """Otwarty IndexService bez dostawcy embeddingow (sam indeks pelnotekstowy)."""
    service = IndexService(app_config)
    service.open(load_provider=False)
    try:
        yield service
    finally:
        service.close()


@pytest.fixture
def index_with_model(app_config: AppConfig) -> Iterator[IndexService]:
    """IndexService z zaladowanym modelem embeddingow.

    Test korzystajacy z tej fixture nalezy oznaczyc markerem ``requires_model``.
    Gdy modelu nie ma na dysku, test jest pomijany zamiast konczyc sie bledem.
    """
    if find_model_dir(app_config.embedding.model_key) is None:
        pytest.skip("Brak lokalnego modelu embeddingow w katalogu models/.")
    service = IndexService(app_config)
    service.open(load_provider=True)
    if service.provider is None or service.vector_store is None:
        service.close()
        pytest.skip("Dostawca embeddingow nie zostal zaladowany.")
    try:
        yield service
    finally:
        service.close()


#: Zawartosc plikow zbioru przykladowego. Klucz to nazwa pliku.
_SAMPLE_FILES: dict[str, str] = {
    "notatka.txt": (
        "Notatka sluzbowa z dnia 24.07.2015.\n"
        "Procedura dotyczaca przelewow zostala zaktualizowana.\n"
        "Oddzial w miescie Łódź przyjmuje dyspozycje do godziny 16:00.\n"
    ),
    "transakcje.csv": (
        "data;rachunek;kwota;opis\n"
        "2015-07-24;01 2345 6789;314,00;platnosc karta ...384675\n"
        "2015-07-25;01 2345 6789;1 234,56;przelew wychodzacy\n"
    ),
    "umowa.txt": (
        "Umowa ramowa nr FV/2015/07/123 zawarta w dniu 5 maja 2007 r.\n"
        "Strony ustalaja wynagrodzenie w wysokosci 2.500,00 PLN.\n"
    ),
}


@pytest.fixture
def sample_docs(tmp_path: Path) -> Path:
    """Katalog z kilkoma malymi plikami tekstowymi po polsku."""
    root = tmp_path / "dokumenty"
    root.mkdir(parents=True, exist_ok=True)
    for name, content in _SAMPLE_FILES.items():
        (root / name).write_text(content, encoding="utf-8")
    return root

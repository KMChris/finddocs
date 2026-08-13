"""Testy integracyjne zdalnego OCR na prawdziwym serwerze PP-OCRv6.

Domyslnie pomijane: wymagaja dzialajacego serwera i zmiennej srodowiskowej.
Serwer do prob jest w repozytorium:

    docker compose -f deploy/ppocr/compose.yaml up -d --build

a potem:

    FINDDOCS_TEST_OCR_URL=http://127.0.0.1:8868 \
    .venv/Scripts/python.exe -m pytest tests/integration/test_remote_ocr_real.py -q

Testy sprawdzaja to, czego atrapa HTTP sprawdzic nie moze: zgodnosc kontraktu
z prawdziwym wdrozeniem PaddleX, rozpoznawanie polskich znakow diakrytycznych
oraz zachowanie uslugi OCR przy awarii serwera.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlparse

import pytest

from finddocs.config import OcrSettings
from finddocs.demo.generate import generate_demo_corpus
from finddocs.extractors.detect import detect_file_type
from finddocs.indexing.service import IndexService
from finddocs.ocr.engines.remote_api import ENGINE_NAME
from finddocs.ocr.service import OcrService, build_remote_engine
from finddocs.security.network import (
    EgressCategory,
    NetworkPolicy,
    get_policy,
    set_policy,
)

SERVER_URL = os.environ.get("FINDDOCS_TEST_OCR_URL", "")
MODEL = os.environ.get("FINDDOCS_TEST_OCR_MODEL", "PP-OCRv6_medium")

pytestmark = pytest.mark.skipif(
    not SERVER_URL,
    reason="Brak serwera OCR do prob. Ustaw FINDDOCS_TEST_OCR_URL.",
)


def allowing_policy() -> NetworkPolicy:
    """Polityka dopuszczajaca dokladnie host z konfiguracji testu."""
    host = (urlparse(SERVER_URL).hostname or "").lower()
    return NetworkPolicy(
        enabled_categories={EgressCategory.OCR_API},
        extra_hosts={EgressCategory.OCR_API: (host,)},
        allow_plain_http_localhost=True,
    )


@pytest.fixture(autouse=True)
def process_policy() -> Iterator[None]:
    """Ustawia polityke procesu na czas testu i przywraca poprzednia."""
    previous = get_policy()
    set_policy(allowing_policy())
    try:
        yield
    finally:
        set_policy(previous)


def make_settings(**overrides: object) -> OcrSettings:
    settings = OcrSettings(
        engine=ENGINE_NAME,
        remote_api_enabled=True,
        remote_api_url=SERVER_URL,
        remote_api_model=MODEL,
    )
    for name, value in overrides.items():
        setattr(settings, name, value)
    return settings


@pytest.fixture(scope="module")
def scan_files(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Zbior demonstracyjny ze skanami: obraz PNG i jednostronicowy PDF."""
    target = tmp_path_factory.mktemp("demo")
    generate_demo_corpus(target, include_scans=True)
    return {
        "png": target / "skany" / "skan-potwierdzenia-wplaty.png",
        "pdf": target / "skany" / "skan-umowy-o-wspolpracy.pdf",
    }


def recognize(path: Path, settings: OcrSettings | None = None) -> object:
    """Uruchamia OCR pojedynczego pliku i zamyka usluge."""
    service = OcrService(settings or make_settings())
    try:
        return service.run(path, detect_file_type(path))
    finally:
        service.close()


# --- polaczenie ------------------------------------------------------------------


def test_serwer_odpowiada_na_test_polaczenia() -> None:
    engine = build_remote_engine(make_settings())
    try:
        result = engine.ping()
    finally:
        engine.close()
    assert result["model"] == MODEL
    assert isinstance(result["czas_odpowiedzi_s"], float)


def test_silnik_jest_dostepny_dla_dzialajacego_serwera() -> None:
    engine = build_remote_engine(make_settings())
    try:
        assert engine.is_available() is True
        assert engine.unavailable_reason() == ""
    finally:
        engine.close()


def test_polityka_blokuje_host_spoza_listy() -> None:
    """Adres spoza polityki nie przechodzi, nawet gdy serwer dziala."""
    engine = build_remote_engine(
        make_settings(remote_api_url="https://obcy.serwer"),
        policy=allowing_policy(),
    )
    try:
        assert engine.is_available() is False
        assert "obcy.serwer" in engine.unavailable_reason()
    finally:
        engine.close()


# --- rozpoznawanie ---------------------------------------------------------------


def test_rozpoznaje_polskie_znaki_diakrytyczne(scan_files: dict[str, Path]) -> None:
    """Sedno wyboru PP-OCRv6: skan po polsku ma wracac z ogonkami i kreskami."""
    result = recognize(scan_files["png"])

    assert result.engine == ENGINE_NAME  # type: ignore[attr-defined]
    assert result.engine_version == MODEL  # type: ignore[attr-defined]
    text: str = result.text  # type: ignore[attr-defined]
    assert "POTWIERDZENIE WPŁATY GOTÓWKOWEJ" in text
    assert "Wpłacający" in text
    assert "opłata dodatkowa" in text
    assert "314 zł" in text
    confidence = result.confidence  # type: ignore[attr-defined]
    assert confidence is not None and confidence > 0.8


def test_rozpoznaje_numer_rachunku_ze_skanu(scan_files: dict[str, Path]) -> None:
    """Numery rachunkow sa w zbiorze demonstracyjnym celem wyszukiwania."""
    result = recognize(scan_files["png"])
    digits = "".join(ch for ch in result.text if ch.isdigit())  # type: ignore[attr-defined]
    assert "9987654321098765432109" in digits


def test_rozpoznaje_skan_w_pdf(scan_files: dict[str, Path]) -> None:
    """Sciezka PDF idzie przez rasteryzacje strony, a nie przez warstwe tekstowa."""
    service = OcrService(make_settings())
    path = scan_files["pdf"]
    try:
        result = service.run(path, detect_file_type(path))
        sections = service.to_sections(result)
    finally:
        service.close()

    assert result.page_count >= 1
    assert len(result.text) > 100
    assert sections and sections[0].page == 1


def test_wynik_trafia_do_pamieci_podrecznej(
    scan_files: dict[str, Path], index_service: IndexService
) -> None:
    """Drugi przebieg czyta wynik z bazy zamiast pytac serwer jeszcze raz.

    Klucz wpisu zawiera nazwe silnika i jego wersje, wiec obie proby musza uzyc
    tych samych ustawien. Przy trafieniu ``run`` konczy sie przed rasteryzacja
    strony: do serwera nie idzie zadne zadanie rozpoznawania.
    """
    path = scan_files["png"]
    settings = make_settings()
    digest = "skrot-testu-zdalnego-ocr"

    service = OcrService(settings, repository=index_service.repository)
    try:
        first = service.run(path, detect_file_type(path), content_sha256=digest)
    finally:
        service.close()
    assert first.from_cache is False
    assert first.engine_version == MODEL

    again = OcrService(settings, repository=index_service.repository)
    try:
        second = again.run(path, detect_file_type(path), content_sha256=digest)
    finally:
        again.close()
    assert second.from_cache is True
    assert second.text == first.text


def test_zmiana_modelu_uniewaznia_pamiec_podreczna(
    scan_files: dict[str, Path], index_service: IndexService
) -> None:
    """Podmiana modelu na serwerze ma dac nowe rozpoznanie, a nie stary wpis."""
    path = scan_files["png"]
    digest = "skrot-testu-zmiany-modelu"

    service = OcrService(make_settings(), repository=index_service.repository)
    try:
        service.run(path, detect_file_type(path), content_sha256=digest)
    finally:
        service.close()

    inny = OcrService(
        make_settings(remote_api_model="PP-OCRv6_small"),
        repository=index_service.repository,
    )
    try:
        result = inny.run(path, detect_file_type(path), content_sha256=digest)
    finally:
        inny.close()
    assert result.from_cache is False


# --- rezerwa lokalna -------------------------------------------------------------


def test_martwy_serwer_przechodzi_na_silnik_lokalny() -> None:
    """Awaria serwera nie zatrzymuje indeksowania, ale zostawia ostrzezenie."""
    settings = make_settings(remote_api_url="http://127.0.0.1:1")
    service = OcrService(settings)
    try:
        if not any(engine.is_available() for engine in service._engines[1:]):
            pytest.skip("Brak lokalnego silnika OCR do sprawdzenia rezerwy.")
        assert service.engine.name != ENGINE_NAME
        assert any("Zdalny serwer OCR jest niedostępny" in note for note in service.warnings)
    finally:
        service.close()

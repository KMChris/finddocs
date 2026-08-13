"""Testy uslugi OCR na sztucznym silniku.

Testy nie wymagaja zainstalowanego Tesseract ani zadnego innego silnika.
Podstawiamy wlasny silnik spelniajacy protokol ``OcrEngine``, dzieki czemu
sprawdzamy to, co nalezy do aplikacji: wybor silnika, przetwarzanie strona
po stronie, limity, anulowanie, prog pewnosci i pamiec podreczna.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from PIL import Image as PillowImage
from PIL.Image import Image

from finddocs.config import AppConfig, OcrSettings
from finddocs.errors import OcrCancelledError, OcrEngineUnavailableError, OcrError
from finddocs.extractors.detect import FileTypeInfo
from finddocs.indexing.service import IndexService
from finddocs.ocr import service as ocr_service
from finddocs.ocr.base import OcrEngine, OcrLine, OcrPageResult
from finddocs.ocr.service import (
    MAX_RENDER_DPI,
    MIN_RENDER_DPI,
    OcrService,
    describe_engines,
)
from finddocs.types import CancellationToken, TextOrigin

#: Informacja o typie pliku dla obrazu PNG.
PNG_INFO = FileTypeInfo(mime_type="image/png", extension=".png", detected_by="magic")

#: Informacja o typie pliku dla wielostronicowego TIFF.
TIFF_INFO = FileTypeInfo(mime_type="image/tiff", extension=".tif", detected_by="magic")


class FakeEngine(OcrEngine):
    """Silnik zwracajacy przewidywalny tekst dla kazdej strony."""

    name = "fake"
    priority = 999
    supports_rotation = True
    provides_confidence = True

    def __init__(
        self,
        *,
        available: bool = True,
        confidence: float | None = 0.92,
        polish: bool = True,
        fail_on: set[int] | None = None,
    ) -> None:
        self._available = available
        self._confidence = confidence
        self._polish = polish
        self._fail_on = fail_on or set()
        self.calls: list[int] = []
        self.closed = False

    def is_available(self) -> bool:
        return self._available

    def unavailable_reason(self) -> str:
        return "" if self._available else "Silnik testowy celowo wylaczony."

    def version(self) -> str:
        return "1.2.3"

    def supported_languages(self) -> list[str]:
        return ["pol", "eng"] if self._polish else ["eng"]

    def has_polish(self) -> bool:
        return self._polish

    def recognize(
        self,
        image: Image,
        *,
        languages: list[str],
        page: int = 1,
        cancel: CancellationToken | None = None,
    ) -> OcrPageResult:
        self.calls.append(page)
        if page in self._fail_on:
            raise OcrError(f"Celowy blad rozpoznawania strony {page}.")
        text = f"Tresc strony {page}. Zazolc gesla jazn."
        return OcrPageResult(
            page=page,
            text=text,
            confidence=self._confidence,
            lines=[OcrLine(text=text, confidence=self._confidence)],
            engine=self.name,
        )

    def close(self) -> None:
        self.closed = True


class Cancelled:
    """Token anulowania, ktory zglasza przerwanie po zadanej liczbie sprawdzen."""

    def __init__(self, after: int = 0) -> None:
        self.after = after
        self.checks = 0

    def is_cancelled(self) -> bool:
        self.checks += 1
        return self.checks > self.after

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled():
            raise OcrCancelledError()


@pytest.fixture
def ocr_settings() -> OcrSettings:
    return OcrSettings(enabled=True, engine="auto", languages=["pol"], render_dpi=200)


@pytest.fixture
def image_file(tmp_path: Path) -> Path:
    """Jednostronicowy obraz PNG."""
    target = tmp_path / "skan.png"
    PillowImage.new("RGB", (200, 120), (250, 250, 250)).save(target)
    return target


@pytest.fixture
def multipage_image(tmp_path: Path) -> Path:
    """Wielostronicowy TIFF, zeby sprawdzic przetwarzanie strona po stronie."""
    target = tmp_path / "skan.tif"
    pages = [PillowImage.new("RGB", (200, 120), (250, 250, 250)) for _ in range(5)]
    pages[0].save(target, format="TIFF", save_all=True, append_images=pages[1:])
    return target


@pytest.fixture
def service_with_fake(
    ocr_settings: OcrSettings, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[OcrService, FakeEngine]]:
    """Usluga OCR z podstawionym silnikiem testowym."""
    engine = FakeEngine()
    monkeypatch.setattr(
        ocr_service, "build_engines", lambda settings, model_dir=None, **kwargs: [engine]
    )
    service = OcrService(ocr_settings)
    try:
        yield service, engine
    finally:
        service.close()


# --- wybor silnika ---------------------------------------------------------------


def test_wybiera_pierwszy_dostepny_silnik(
    ocr_settings: OcrSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Silnik niedostepny jest pomijany, wybierany jest kolejny z listy."""
    niedostepny = FakeEngine(available=False)
    dostepny = FakeEngine()
    monkeypatch.setattr(
        ocr_service,
        "build_engines",
        lambda settings, model_dir=None, **kwargs: [niedostepny, dostepny],
    )

    service = OcrService(ocr_settings)

    assert service.engine is dostepny
    assert service.engine_name() == "fake"


def test_brak_silnika_konczy_sie_wyjatkiem(
    ocr_settings: OcrSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bez zadnego silnika aplikacja mowi wprost, ze OCR jest niedostepny."""
    monkeypatch.setattr(
        ocr_service,
        "build_engines",
        lambda settings, model_dir=None, **kwargs: [FakeEngine(available=False)],
    )
    service = OcrService(ocr_settings)

    assert service.engine_available is False
    assert service.engine_name() == ""
    with pytest.raises(OcrEngineUnavailableError):
        _ = service.engine


def test_silnik_bez_polskiego_daje_ostrzezenie(
    ocr_settings: OcrSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Brak modelu polskiego to ostrzezenie, a nie ciche pogorszenie jakosci."""
    monkeypatch.setattr(
        ocr_service,
        "build_engines",
        lambda settings, model_dir=None, **kwargs: [FakeEngine(polish=False)],
    )
    service = OcrService(ocr_settings)

    _ = service.engine

    assert any("polskiego" in warning for warning in service.warnings)


def test_opis_silnikow_dla_diagnostyki(ocr_settings: OcrSettings) -> None:
    """Ekran diagnostyki dostaje liste wszystkich silnikow, takze niedostepnych."""
    opisy = describe_engines(ocr_settings)

    assert opisy
    nazwy = {opis.name for opis in opisy}
    assert {"tesseract", "easyocr", "rapidocr"} >= nazwy
    for opis in opisy:
        assert opis.available or opis.reason


# --- przetwarzanie stron ---------------------------------------------------------


def test_rozpoznaje_jednostronicowy_obraz(
    service_with_fake: tuple[OcrService, FakeEngine], image_file: Path
) -> None:
    """Podstawowy przebieg: jedna strona, jeden wynik, wypelnione metadane."""
    service, engine = service_with_fake

    result = service.run(image_file, PNG_INFO)

    assert result.page_count == 1
    assert "Tresc strony 1" in result.text
    assert result.engine == "fake"
    assert result.engine_version == "1.2.3"
    assert result.dpi == 200
    assert result.confidence == pytest.approx(0.92)
    assert result.from_cache is False
    assert engine.calls == [1]


def test_przetwarza_kazda_klatke_osobno(
    service_with_fake: tuple[OcrService, FakeEngine], multipage_image: Path
) -> None:
    """Piec klatek to piec wywolan silnika, a nie jedno na calym pliku."""
    service, engine = service_with_fake

    result = service.run(multipage_image, TIFF_INFO)

    assert engine.calls == [1, 2, 3, 4, 5]
    assert result.page_count == 5


def test_limit_stron_przerywa_i_ostrzega(
    ocr_settings: OcrSettings, monkeypatch: pytest.MonkeyPatch, multipage_image: Path
) -> None:
    """Po osiagnieciu limitu wynik jest oznaczony jako przyciety."""
    engine = FakeEngine()
    monkeypatch.setattr(
        ocr_service, "build_engines", lambda settings, model_dir=None, **kwargs: [engine]
    )
    ocr_settings.max_pages_per_document = 2
    service = OcrService(ocr_settings)

    result = service.run(multipage_image, TIFF_INFO)

    assert result.page_count == 2
    assert result.truncated is True
    assert any("limit" in warning for warning in result.warnings)


def test_blad_jednej_strony_nie_przerywa_dokumentu(
    ocr_settings: OcrSettings, monkeypatch: pytest.MonkeyPatch, multipage_image: Path
) -> None:
    """Nieudana strona zostawia ostrzezenie, pozostale sa rozpoznawane."""
    engine = FakeEngine(fail_on={2})
    monkeypatch.setattr(
        ocr_service, "build_engines", lambda settings, model_dir=None, **kwargs: [engine]
    )
    service = OcrService(ocr_settings)

    result = service.run(multipage_image, TIFF_INFO)

    assert result.page_count == 4
    assert any("Strona 2" in warning for warning in result.warnings)
    assert "Tresc strony 3" in result.text


def test_anulowanie_przerywa_rozpoznawanie(
    service_with_fake: tuple[OcrService, FakeEngine], multipage_image: Path
) -> None:
    """Uzytkownik nie czeka na koniec pliku, przerwanie dziala od razu."""
    service, _engine = service_with_fake

    with pytest.raises(OcrCancelledError):
        service.run(
            multipage_image,
            TIFF_INFO,
            cancel=Cancelled(after=2),
        )


def test_niska_pewnosc_daje_ostrzezenie(
    ocr_settings: OcrSettings, monkeypatch: pytest.MonkeyPatch, image_file: Path
) -> None:
    """Wynik ponizej progu jest odnotowany, zeby dalo sie ocenic jakosc skanu."""
    monkeypatch.setattr(
        ocr_service,
        "build_engines",
        lambda settings, model_dir=None, **kwargs: [FakeEngine(confidence=0.1)],
    )
    ocr_settings.min_confidence_to_keep = 0.5
    service = OcrService(ocr_settings)

    result = service.run(image_file, PNG_INFO)

    assert any("niska pewnosc" in warning for warning in result.warnings)


@pytest.mark.parametrize(
    ("ustawione", "oczekiwane"),
    [(50, MIN_RENDER_DPI), (200, 200), (1200, MAX_RENDER_DPI)],
)
def test_rozdzielczosc_jest_ograniczana(
    ocr_settings: OcrSettings,
    monkeypatch: pytest.MonkeyPatch,
    image_file: Path,
    ustawione: int,
    oczekiwane: int,
) -> None:
    """Wartosc spoza zakresu jest przycinana, a nie przyjmowana na slepo."""
    monkeypatch.setattr(
        ocr_service, "build_engines", lambda settings, model_dir=None, **kwargs: [FakeEngine()]
    )
    ocr_settings.render_dpi = ustawione
    service = OcrService(ocr_settings)

    result = service.run(image_file, PNG_INFO)

    assert result.dpi == oczekiwane


class SizeCapturingEngine(FakeEngine):
    """Silnik zapisujacy rozmiary otrzymanych obrazow."""

    def __init__(self) -> None:
        super().__init__()
        self.sizes: list[tuple[int, int]] = []

    def recognize(
        self,
        image: Image,
        *,
        languages: list[str],
        page: int = 1,
        cancel: CancellationToken | None = None,
    ) -> OcrPageResult:
        self.sizes.append(image.size)
        return super().recognize(image, languages=languages, page=page, cancel=cancel)


def test_czysty_skan_nie_jest_renderowany_powyzej_wlasnej_rozdzielczosci(
    ocr_settings: OcrSettings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Strona PDF bedaca jednym obrazem trafia do silnika w skali obrazu.

    Obraz 420x594 px na stronie A4 to okolo 51 dpi. Rasteryzacja przy
    ustawionych 200 dpi tworzylaby prawie czterokrotnie wiekszy obraz bez
    zadnej nowej informacji, wiec render jest ograniczany do skali skanu.
    """
    import io

    from finddocs.demo.generate import build_image_pdf, render_scan_image

    image = render_scan_image(["Pierwsza linia skanu", "Druga linia"], width=420, height=594)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=80)
    target = tmp_path / "skan.pdf"
    target.write_bytes(build_image_pdf(buffer.getvalue(), width=image.width, height=image.height))

    engine = SizeCapturingEngine()
    monkeypatch.setattr(
        ocr_service, "build_engines", lambda settings, model_dir=None, **kwargs: [engine]
    )
    service = OcrService(ocr_settings)
    pdf_info = FileTypeInfo(mime_type="application/pdf", extension=".pdf", detected_by="magic")

    service.run(target, pdf_info)

    assert len(engine.sizes) == 1
    width, height = engine.sizes[0]
    # Rozmiar odpowiada obrazowi zrodlowemu (z zapasem na zaokraglenie skali),
    # a nie rasteryzacji 200 dpi (okolo 1653 px szerokosci).
    assert 415 <= width <= 440
    assert 585 <= height <= 620


def test_strona_tekstowa_renderuje_sie_w_ustawionym_dpi(
    ocr_settings: OcrSettings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Strona z warstwa tekstowa nie dostaje ograniczenia do skali obrazow."""
    import datetime as dt

    from finddocs.demo.generate import build_text_pdf

    target = tmp_path / "tekst.pdf"
    target.write_bytes(
        build_text_pdf("Tytul", ["Tresc " * 40], created=dt.datetime(2015, 1, 1, tzinfo=dt.UTC))
    )

    engine = SizeCapturingEngine()
    monkeypatch.setattr(
        ocr_service, "build_engines", lambda settings, model_dir=None, **kwargs: [engine]
    )
    service = OcrService(ocr_settings)
    pdf_info = FileTypeInfo(mime_type="application/pdf", extension=".pdf", detected_by="magic")

    service.run(target, pdf_info)

    assert len(engine.sizes) == 1
    width, _height = engine.sizes[0]
    # Strona A4 przy 200 dpi ma okolo 1653 px szerokosci.
    assert width > 1500


# --- sekcje ----------------------------------------------------------------------


def test_wynik_zamienia_sie_na_sekcje(
    service_with_fake: tuple[OcrService, FakeEngine], multipage_image: Path
) -> None:
    """Kazda strona z tekstem daje jedna sekcje oznaczona jako pochodzaca z OCR."""
    service, _engine = service_with_fake
    result = service.run(multipage_image, TIFF_INFO)

    sections = service.to_sections(result, start_order=3)

    assert len(sections) == 5
    assert sections[0].order == 3
    assert sections[0].page == 1
    assert all(section.origin is TextOrigin.OCR for section in sections)
    assert all(section.ocr_confidence == pytest.approx(0.92) for section in sections)


def test_puste_strony_nie_daja_sekcji(
    ocr_settings: OcrSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Strona bez tekstu nie trafia do indeksu jako pusty fragment."""
    monkeypatch.setattr(
        ocr_service, "build_engines", lambda settings, model_dir=None, **kwargs: [FakeEngine()]
    )
    service = OcrService(ocr_settings)
    from finddocs.ocr.base import OcrDocumentResult

    result = OcrDocumentResult(
        pages=[
            OcrPageResult(page=1, text="Tresc"),
            OcrPageResult(page=2, text="   "),
        ]
    )

    sections = service.to_sections(result)

    assert len(sections) == 1


# --- pamiec podreczna ------------------------------------------------------------


def test_pamiec_podreczna_omija_ponowne_rozpoznanie(
    ocr_settings: OcrSettings,
    monkeypatch: pytest.MonkeyPatch,
    image_file: Path,
    index_service: IndexService,
) -> None:
    """Drugie uruchomienie na tym samym pliku nie wola silnika."""
    engine = FakeEngine()
    monkeypatch.setattr(
        ocr_service, "build_engines", lambda settings, model_dir=None, **kwargs: [engine]
    )
    service = OcrService(ocr_settings, repository=index_service.repository)

    pierwszy = service.run(image_file, PNG_INFO, content_sha256="a" * 64)
    drugi = service.run(image_file, PNG_INFO, content_sha256="a" * 64)

    assert engine.calls == [1]
    assert pierwszy.from_cache is False
    assert drugi.from_cache is True
    assert drugi.text == pierwszy.text


def test_zmiana_rozdzielczosci_uniewaznia_pamiec_podreczna(
    ocr_settings: OcrSettings,
    monkeypatch: pytest.MonkeyPatch,
    image_file: Path,
    index_service: IndexService,
) -> None:
    """Klucz pamieci podrecznej zawiera dpi, wiec inna wartosc wymusza ponowny OCR."""
    engine = FakeEngine()
    monkeypatch.setattr(
        ocr_service, "build_engines", lambda settings, model_dir=None, **kwargs: [engine]
    )

    service = OcrService(ocr_settings, repository=index_service.repository)
    service.run(image_file, PNG_INFO, content_sha256="b" * 64)

    ocr_settings.render_dpi = 300
    inna = OcrService(ocr_settings, repository=index_service.repository)
    wynik = inna.run(image_file, PNG_INFO, content_sha256="b" * 64)

    assert wynik.from_cache is False
    assert len(engine.calls) == 2


def test_bez_skrotu_tresci_pamiec_podreczna_nie_dziala(
    ocr_settings: OcrSettings,
    monkeypatch: pytest.MonkeyPatch,
    image_file: Path,
    index_service: IndexService,
) -> None:
    """Bez klucza nie ma czego zapisac, wiec OCR uruchamia sie za kazdym razem."""
    engine = FakeEngine()
    monkeypatch.setattr(
        ocr_service, "build_engines", lambda settings, model_dir=None, **kwargs: [engine]
    )
    service = OcrService(ocr_settings, repository=index_service.repository)

    service.run(image_file, PNG_INFO)
    service.run(image_file, PNG_INFO)

    assert len(engine.calls) == 2


def test_wynik_obciety_limitem_nie_trafia_do_pamieci(
    ocr_settings: OcrSettings,
    monkeypatch: pytest.MonkeyPatch,
    multipage_image: Path,
    index_service: IndexService,
) -> None:
    """Podniesienie limitu stron dziala takze dla dokumentow juz rozpoznanych.

    Klucz pamieci podrecznej nie zawiera limitu stron, wiec zapisany wynik
    czesciowy maskowalby nowe ustawienie. Wynik obciety nie jest zapamietywany.
    """
    engine = FakeEngine()
    monkeypatch.setattr(
        ocr_service, "build_engines", lambda settings, model_dir=None, **kwargs: [engine]
    )
    ocr_settings.max_pages_per_document = 2
    service = OcrService(ocr_settings, repository=index_service.repository)

    pierwszy = service.run(multipage_image, TIFF_INFO, content_sha256="c" * 64)
    assert pierwszy.truncated is True
    assert len(pierwszy.pages) == 2

    ocr_settings.max_pages_per_document = 1000
    ponowny = OcrService(ocr_settings, repository=index_service.repository).run(
        multipage_image, TIFF_INFO, content_sha256="c" * 64
    )

    assert ponowny.from_cache is False
    assert len(ponowny.pages) == 5


def test_zamkniecie_zwalnia_silnik(
    service_with_fake: tuple[OcrService, FakeEngine], image_file: Path
) -> None:
    """Usluga zamyka wybrany silnik, zeby nie zostawiac otwartych zasobow."""
    service, engine = service_with_fake
    service.run(image_file, PNG_INFO)

    service.close()

    assert engine.closed is True


def test_ustawienia_z_konfiguracji_aplikacji() -> None:
    """Domyslna konfiguracja ma sensowne wartosci dla polskich dokumentow."""
    config = AppConfig()

    assert config.ocr.enabled is True
    assert config.ocr.languages == ["pol"]
    assert MIN_RENDER_DPI <= config.ocr.render_dpi <= MAX_RENDER_DPI
    assert config.ocr.auto_rotate is True

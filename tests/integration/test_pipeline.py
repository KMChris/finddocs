"""Testy przetwarzania pojedynczego dokumentu.

``DocumentPipeline`` jest miejscem, w ktorym spotykaja sie konektor, parser,
OCR, fragmentacja i zapis do indeksu. Umowa tej warstwy brzmi: metoda ``process``
nie rzuca wyjatkow poza anulowaniem zadania i brakiem miejsca na dysku. Kazdy
inny problem konczy sie wynikiem opisujacym, co poszlo nie tak.

Testy pilnuja tej umowy, izolacji bledow oraz obslugi zalacznikow.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from finddocs.config import AppConfig, LocalDirSourceSettings
from finddocs.connectors.local_dir import LocalDirectoryConnector
from finddocs.errors import (
    CorruptedFileError,
    ExtractionError,
    JobCancelledError,
    PasswordProtectedError,
    SourceUnavailableError,
    TransientConnectorError,
)
from finddocs.extractors.base import ExtractionContext
from finddocs.extractors.registry import ExtractorRegistry, build_default_registry
from finddocs.indexing.service import IndexService
from finddocs.jobs.control import JobControl
from finddocs.jobs.pipeline import DocumentPipeline, _safe_filename
from finddocs.ocr.service import OcrService
from finddocs.types import DocumentStatus, ExtractionResult, SourceItem, SourceKind

SOURCE_ID = "lokalne"


def _connector(root: Path) -> LocalDirectoryConnector:
    """Konektor katalogu lokalnego bez zadnych filtrow."""
    return LocalDirectoryConnector(
        source_id=SOURCE_ID,
        label="Katalog testowy",
        settings=LocalDirSourceSettings(root_path=str(root)),
        include_extensions=[],
        exclude_extensions=[],
        exclude_globs=[],
        max_file_size_mb=512,
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    target = tmp_path / "praca"
    target.mkdir(parents=True, exist_ok=True)
    return target


@pytest.fixture
def make_pipeline(
    index_service: IndexService,
) -> Callable[[AppConfig], DocumentPipeline]:
    """Zwraca funkcje budujaca potok na podanej konfiguracji."""

    def build(config: AppConfig) -> DocumentPipeline:
        return DocumentPipeline(
            config,
            index_service,
            build_default_registry(office_com_enabled=config.indexing.office_com_enabled),
            OcrService(config.ocr),
        )

    return build


@pytest.fixture
def run_document(
    index_service: IndexService,
    workspace: Path,
) -> Callable[..., object]:
    """Zwraca funkcje przetwarzajaca jeden plik i zwracajaca wynik."""

    def run(
        pipeline: DocumentPipeline,
        root: Path,
        name: str,
        *,
        control: JobControl | None = None,
    ) -> object:
        repository = index_service.repository
        repository.upsert_source(
            SOURCE_ID, SourceKind.LOCAL_DIR, "Test", location=str(root), enabled=True
        )
        scan_id = repository.next_scan_id()
        target = root / name
        item = SourceItem(
            source_id=SOURCE_ID,
            external_id=name,
            name=name,
            logical_path=name,
            size=target.stat().st_size,
        )
        doc_id = repository.register_item(item, scan_id)
        connector = _connector(root)
        return pipeline.process(
            connector,
            item,
            doc_id,
            workspace=workspace,
            control=control or JobControl(),
            scan_id=scan_id,
        )

    return run


@pytest.fixture
def docs_root(tmp_path: Path) -> Path:
    root = tmp_path / "zrodlo"
    root.mkdir(parents=True, exist_ok=True)
    return root


# --- sciezka podstawowa ----------------------------------------------------------


def test_poprawny_dokument_konczy_sie_stanem_indexed(
    app_config: AppConfig,
    make_pipeline: Callable[[AppConfig], DocumentPipeline],
    run_document: Callable[..., object],
    docs_root: Path,
    index_service: IndexService,
) -> None:
    """Zwykly plik tekstowy przechodzi caly potok i trafia do indeksu."""
    app_config.ocr.enabled = False
    (docs_root / "notatka.txt").write_text(
        "Notatka sluzbowa z dnia 24.07.2015.\n\nProcedura przelewow zostala zaktualizowana.\n",
        encoding="utf-8",
    )

    outcome = run_document(make_pipeline(app_config), docs_root, "notatka.txt")

    assert outcome.status is DocumentStatus.INDEXED  # type: ignore[attr-defined]
    assert outcome.is_success is True  # type: ignore[attr-defined]
    assert outcome.chunks >= 1  # type: ignore[attr-defined]
    assert outcome.used_ocr is False  # type: ignore[attr-defined]
    assert outcome.error_code is None  # type: ignore[attr-defined]

    record = index_service.repository.get_document(outcome.doc_id)  # type: ignore[attr-defined]
    assert record is not None
    assert record.status == DocumentStatus.INDEXED.value
    assert record.chunk_count == outcome.chunks  # type: ignore[attr-defined]


def test_pusty_plik_daje_status_empty(
    app_config: AppConfig,
    make_pipeline: Callable[[AppConfig], DocumentPipeline],
    run_document: Callable[..., object],
    docs_root: Path,
) -> None:
    """Plik bez tresci to dokument pusty, a nie blad przetwarzania."""
    app_config.ocr.enabled = False
    (docs_root / "pusty.txt").write_text("   \n\n", encoding="utf-8")

    outcome = run_document(make_pipeline(app_config), docs_root, "pusty.txt")

    assert outcome.status is DocumentStatus.EMPTY  # type: ignore[attr-defined]
    assert outcome.is_success is False  # type: ignore[attr-defined]


def test_nieobslugiwany_format_daje_status_unsupported(
    app_config: AppConfig,
    make_pipeline: Callable[[AppConfig], DocumentPipeline],
    run_document: Callable[..., object],
    docs_root: Path,
) -> None:
    """Plik binarny bez parsera konczy sie opisanym statusem."""
    app_config.ocr.enabled = False
    (docs_root / "dane.xyz").write_bytes(bytes(range(256)) * 4)

    outcome = run_document(make_pipeline(app_config), docs_root, "dane.xyz")

    assert outcome.status in {DocumentStatus.UNSUPPORTED, DocumentStatus.EMPTY}  # type: ignore[attr-defined]


# --- izolacja bledow -------------------------------------------------------------


@pytest.mark.parametrize(
    ("wyjatek", "oczekiwany"),
    [
        (CorruptedFileError("Uszkodzony."), DocumentStatus.CORRUPTED),
        (PasswordProtectedError("Zabezpieczony."), DocumentStatus.PASSWORD_PROTECTED),
        (ExtractionError("Blad parsera."), DocumentStatus.ERROR),
    ],
)
def test_blad_parsera_jest_tlumaczony_na_status(
    app_config: AppConfig,
    make_pipeline: Callable[[AppConfig], DocumentPipeline],
    run_document: Callable[..., object],
    docs_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    wyjatek: Exception,
    oczekiwany: DocumentStatus,
) -> None:
    """Kazdy rodzaj bledu odczytu ma swoj status, a potok nie rzuca wyjatku."""
    app_config.ocr.enabled = False
    (docs_root / "plik.txt").write_text("Tresc dokumentu testowego.\n", encoding="utf-8")

    def wybuchowy(*_args: object, **_kwargs: object) -> ExtractionResult:
        raise wyjatek

    monkeypatch.setattr(ExtractorRegistry, "extract", wybuchowy)

    outcome = run_document(make_pipeline(app_config), docs_root, "plik.txt")

    assert outcome.status is oczekiwany  # type: ignore[attr-defined]
    assert outcome.error_code is not None  # type: ignore[attr-defined]
    assert outcome.error_message  # type: ignore[attr-defined]


def test_nieoczekiwany_wyjatek_nie_wychodzi_z_potoku(
    app_config: AppConfig,
    make_pipeline: Callable[[AppConfig], DocumentPipeline],
    run_document: Callable[..., object],
    docs_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wyjatek spoza hierarchii aplikacji tez nie przerywa zadania."""
    app_config.ocr.enabled = False
    (docs_root / "plik.txt").write_text("Tresc dokumentu testowego.\n", encoding="utf-8")

    def wybuchowy(*_args: object, **_kwargs: object) -> ExtractionResult:
        raise ZeroDivisionError("celowy blad")

    monkeypatch.setattr(ExtractorRegistry, "extract", wybuchowy)

    outcome = run_document(make_pipeline(app_config), docs_root, "plik.txt")

    assert outcome.status is DocumentStatus.ERROR  # type: ignore[attr-defined]
    assert outcome.error_code == "FD-3000"  # type: ignore[attr-defined]


def test_blad_pobierania_daje_status_download_failed(
    app_config: AppConfig,
    make_pipeline: Callable[[AppConfig], DocumentPipeline],
    run_document: Callable[..., object],
    docs_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nieudane pobranie to osobny status, odrozniony od bledu odczytu."""
    app_config.ocr.enabled = False
    app_config.indexing.max_retries_per_document = 1
    (docs_root / "plik.txt").write_text("Tresc.\n", encoding="utf-8")

    def zepsute(*_args: object, **_kwargs: object) -> object:
        raise SourceUnavailableError("Zrodlo niedostepne.")

    monkeypatch.setattr(LocalDirectoryConnector, "fetch", zepsute)

    outcome = run_document(make_pipeline(app_config), docs_root, "plik.txt")

    assert outcome.status is DocumentStatus.DOWNLOAD_FAILED  # type: ignore[attr-defined]
    assert outcome.error_code == "FD-2001"  # type: ignore[attr-defined]


def test_blad_przejsciowy_jest_ponawiany(
    app_config: AppConfig,
    make_pipeline: Callable[[AppConfig], DocumentPipeline],
    run_document: Callable[..., object],
    docs_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pierwsza proba konczy sie bledem przejsciowym, druga sie udaje."""
    app_config.ocr.enabled = False
    app_config.indexing.max_retries_per_document = 3
    app_config.indexing.retry_backoff_seconds = 0.01
    (docs_root / "plik.txt").write_text("Tresc dokumentu testowego.\n", encoding="utf-8")

    oryginalny = LocalDirectoryConnector.fetch
    proby: list[int] = []

    def czasem_zepsute(self: LocalDirectoryConnector, *args: object, **kwargs: object) -> object:
        proby.append(1)
        if len(proby) == 1:
            raise TransientConnectorError("Chwilowy problem.")
        return oryginalny(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(LocalDirectoryConnector, "fetch", czasem_zepsute)

    outcome = run_document(make_pipeline(app_config), docs_root, "plik.txt")

    assert len(proby) == 2
    assert outcome.status is DocumentStatus.INDEXED  # type: ignore[attr-defined]


def test_anulowanie_wychodzi_z_potoku(
    app_config: AppConfig,
    make_pipeline: Callable[[AppConfig], DocumentPipeline],
    run_document: Callable[..., object],
    docs_root: Path,
) -> None:
    """Anulowanie jest jedynym wyjatkiem, ktory potok przepuszcza dalej."""
    app_config.ocr.enabled = False
    (docs_root / "plik.txt").write_text("Tresc.\n", encoding="utf-8")
    control = JobControl()
    control.cancel()

    with pytest.raises(JobCancelledError):
        run_document(make_pipeline(app_config), docs_root, "plik.txt", control=control)


def test_zbyt_duzy_plik_jest_pomijany(
    app_config: AppConfig,
    make_pipeline: Callable[[AppConfig], DocumentPipeline],
    docs_root: Path,
    index_service: IndexService,
    workspace: Path,
) -> None:
    """Plik oznaczony jako zbyt duzy nie jest w ogole pobierany."""
    app_config.ocr.enabled = False
    app_config.indexing.max_file_size_mb = 1
    target = docs_root / "wielki.txt"
    target.write_text("x", encoding="utf-8")

    repository = index_service.repository
    repository.upsert_source(
        SOURCE_ID, SourceKind.LOCAL_DIR, "Test", location=str(docs_root), enabled=True
    )
    scan_id = repository.next_scan_id()
    item = SourceItem(
        source_id=SOURCE_ID,
        external_id="wielki.txt",
        name="wielki.txt",
        logical_path="wielki.txt",
        size=99 * 1024 * 1024,
        extra={"too_large": True},
    )
    doc_id = repository.register_item(item, scan_id)

    outcome = make_pipeline(app_config).process(
        _connector(docs_root),
        item,
        doc_id,
        workspace=workspace,
        control=JobControl(),
        scan_id=scan_id,
    )

    assert outcome.status is DocumentStatus.SKIPPED


# --- zalaczniki ------------------------------------------------------------------


def test_zalacznik_jest_osobnym_dokumentem(
    app_config: AppConfig,
    make_pipeline: Callable[[AppConfig], DocumentPipeline],
    run_document: Callable[..., object],
    docs_root: Path,
    index_service: IndexService,
) -> None:
    """Zalacznik wiadomosci trafia do indeksu jako dokument powiazany z rodzicem."""
    from email.message import EmailMessage

    app_config.ocr.enabled = False
    message = EmailMessage()
    message["From"] = "nadawca@example.test"
    message["To"] = "odbiorca@example.test"
    message["Subject"] = "Zestawienie miesieczne"
    message.set_content("W zalaczeniu przesylam zestawienie transakcji.\n")
    message.add_attachment(
        b"data;kwota\n2015-07-24;1234,56\n2015-07-25;99,00\n",
        maintype="text",
        subtype="csv",
        filename="zestawienie.csv",
    )
    (docs_root / "wiadomosc.eml").write_bytes(message.as_bytes())

    outcome = run_document(make_pipeline(app_config), docs_root, "wiadomosc.eml")

    assert outcome.status is DocumentStatus.INDEXED  # type: ignore[attr-defined]
    rows = index_service.db.query_all(
        "SELECT name, attachment_of, status FROM documents ORDER BY doc_id"
    )
    nazwy = {str(row["name"]) for row in rows}
    assert "zestawienie.csv" in nazwy
    zalacznik = next(row for row in rows if str(row["name"]) == "zestawienie.csv")
    assert zalacznik["attachment_of"] == outcome.doc_id  # type: ignore[attr-defined]
    assert str(zalacznik["status"]) == DocumentStatus.INDEXED.value


def test_zalacznik_da_sie_wyszukac(
    app_config: AppConfig,
    make_pipeline: Callable[[AppConfig], DocumentPipeline],
    run_document: Callable[..., object],
    docs_root: Path,
    index_service: IndexService,
) -> None:
    """Tresc zalacznika jest w indeksie pelnotekstowym, nie tylko jego nazwa."""
    from email.message import EmailMessage

    from finddocs.search.service import SearchService
    from finddocs.types import SearchMode, SearchRequest

    app_config.ocr.enabled = False
    message = EmailMessage()
    message["From"] = "nadawca@example.test"
    message["Subject"] = "Przesylam plik"
    message.set_content("Tresc wiadomosci.\n")
    message.add_attachment(
        b"Numer rachunku 00 1234 5678 9012 3456 7890 1234 do rozliczenia.",
        maintype="text",
        subtype="plain",
        filename="rachunek.txt",
    )
    (docs_root / "wiadomosc.eml").write_bytes(message.as_bytes())

    run_document(make_pipeline(app_config), docs_root, "wiadomosc.eml")
    index_service.flush()

    response = SearchService(index_service).search(
        SearchRequest(query="00 1234 5678 9012 3456 7890 1234", mode=SearchMode.EXACT)
    )

    assert response.total_documents >= 1
    assert any(hit.name == "rachunek.txt" for hit in response.hits)


def test_zalaczniki_mozna_wylaczyc(
    app_config: AppConfig,
    make_pipeline: Callable[[AppConfig], DocumentPipeline],
    run_document: Callable[..., object],
    docs_root: Path,
    index_service: IndexService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wylaczenie zalacznikow w kontekscie ekstrakcji zostawia sama wiadomosc."""
    from email.message import EmailMessage

    app_config.ocr.enabled = False
    message = EmailMessage()
    message["From"] = "nadawca@example.test"
    message["Subject"] = "Przesylam plik"
    message.set_content("Tresc wiadomosci.\n")
    message.add_attachment(b"dane", maintype="text", subtype="plain", filename="plik.txt")
    (docs_root / "wiadomosc.eml").write_bytes(message.as_bytes())

    oryginalny = ExtractionContext.__init__

    def bez_zalacznikow(self: ExtractionContext, *args: object, **kwargs: object) -> None:
        kwargs["extract_attachments"] = False
        oryginalny(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(ExtractionContext, "__init__", bez_zalacznikow)

    run_document(make_pipeline(app_config), docs_root, "wiadomosc.eml")

    rows = index_service.db.query_all("SELECT name FROM documents")
    assert {str(row["name"]) for row in rows} == {"wiadomosc.eml"}


# --- porzadki --------------------------------------------------------------------


def test_katalog_tymczasowy_jest_sprzatany(
    app_config: AppConfig,
    make_pipeline: Callable[[AppConfig], DocumentPipeline],
    run_document: Callable[..., object],
    docs_root: Path,
    workspace: Path,
) -> None:
    """Po przetworzeniu dokumentu nie zostaja pliki robocze."""
    app_config.ocr.enabled = False
    (docs_root / "plik.txt").write_text("Tresc dokumentu testowego.\n", encoding="utf-8")

    run_document(make_pipeline(app_config), docs_root, "plik.txt")

    assert list(workspace.iterdir()) == []


def test_katalog_tymczasowy_jest_sprzatany_takze_po_bledzie(
    app_config: AppConfig,
    make_pipeline: Callable[[AppConfig], DocumentPipeline],
    run_document: Callable[..., object],
    docs_root: Path,
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Blad odczytu nie zostawia smieci w przestrzeni roboczej."""
    app_config.ocr.enabled = False
    (docs_root / "plik.txt").write_text("Tresc dokumentu testowego.\n", encoding="utf-8")

    def wybuchowy(*_args: object, **_kwargs: object) -> ExtractionResult:
        raise ExtractionError("Celowy blad.")

    monkeypatch.setattr(ExtractorRegistry, "extract", wybuchowy)

    run_document(make_pipeline(app_config), docs_root, "plik.txt")

    assert list(workspace.iterdir()) == []


@pytest.mark.parametrize(
    ("nazwa", "oczekiwane"),
    [
        ("zwykla.txt", "zwykla.txt"),
        ("../../etc/haslo", ".._.._etc_haslo"),
        ("plik: z ? znakami *.txt", "plik_ z _ znakami _.txt"),
        ("", "zalacznik"),
        ("   ", "zalacznik"),
        ("..", "zalacznik"),
        (r"C:\Windows\system32\config", "C__Windows_system32_config"),
    ],
)
def test_nazwa_zalacznika_jest_oczyszczana(nazwa: str, oczekiwane: str) -> None:
    """Nazwa z zalacznika nie moze wyprowadzic zapisu poza katalog roboczy."""
    wynik = _safe_filename(nazwa)

    assert wynik == oczekiwane
    assert "/" not in wynik
    assert "\\" not in wynik
